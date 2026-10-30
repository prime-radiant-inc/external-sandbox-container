"""Backend-neutral process interface and Apple Container lifecycle/transport."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import struct
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from .proxy_relay import ProxyRelay

MAX_FRAME = 24 * 1024 * 1024


class BusyError(RuntimeError):
    status_code = 429
    statusCode = 429


class GuestError(RuntimeError):
    def __init__(self, error):
        super().__init__(error.get("message", "Guest operation failed"))
        self.errno = error.get("errno")
        self.code = error.get("code")
        self.data = error.get("data")


@dataclass
class Mount:
    name: str
    hostPath: str
    mode: str = "rw"
    preservedPaths: list[str] = field(default_factory=list)

    @property
    def guestPath(self):
        return f"/mnt/{self.name}"

    def info(self):
        return {**asdict(self), "guestPath": self.guestPath}


def parse_mounts(specs: list[tuple[str, str]], preserve_paths=False) -> list[Mount]:
    mounts = []
    protected = ["/bin", "/sbin", "/etc", "/usr", "/lib", "/lib64", "/dev", "/proc", "/sys", "/run",
                 "/mnt", "/workspace", "/home", "/opt", "/tmp"]
    for spec, mode in specs:
        if mode not in ("ro", "rw"):
            raise ValueError("Mount mode must be ro or rw")
        name, sep, value = spec.partition("=")
        raw = value if sep else spec
        if not raw:
            raise ValueError("Mount path must not be empty")
        requested = Path(raw).expanduser().absolute()
        source = requested.resolve(strict=True)
        name = name if sep else requested.name
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", name):
            raise ValueError(f"Invalid mount name: {name}")
        if any(m.name == name for m in mounts):
            raise ValueError(f"Duplicate mount name: {name}")
        if not source.is_dir():
            raise ValueError(f"Mount is not a directory: {source}")
        if any(c in str(source) for c in (",", "\n", "\0")):
            raise ValueError("Mount paths cannot contain commas, newlines, or NUL")
        aliases = list(dict.fromkeys([str(requested), str(source)])) if preserve_paths else []
        for alias in aliases:
            if alias == "/" or any(alias == p or alias.startswith(p + "/") or p.startswith(alias + "/") for p in protected):
                raise ValueError(f"Cannot preserve guest system path {alias}; use /mnt/{name}")
            if any(c in alias for c in (",", "\n", "\0")):
                raise ValueError("Preserved paths cannot contain commas, newlines, or NUL")
        for previous in mounts:
            other = Path(previous.hostPath)
            if mode != previous.mode and (source == other or source.is_relative_to(other) or other.is_relative_to(source)):
                raise ValueError("Read-only and writable host mounts must not overlap")
        mounts.append(Mount(name, str(source), mode, aliases))
    return mounts


class Process:
    def __init__(self, backend, ident):
        self.backend, self.id = backend, ident
        self.events = asyncio.Queue(maxsize=64)  # <= ~1.4 MiB of encoded output
        self.finished = asyncio.get_running_loop().create_future()
        self.failed = False

    def feed(self, message):
        if self.failed:
            return
        if self.events.full():
            self.fail("Process output consumer exceeded the bounded output buffer")
            asyncio.create_task(self.backend._terminate_quietly(self.id))
            return
        self.events.put_nowait(message)
        if message["type"] in ("exit", "error") and not self.finished.done():
            self.finished.set_result(None)

    def fail(self, message):
        self.failed = True
        while not self.events.empty():
            self.events.get_nowait()
        self.events.put_nowait({"type": "error", "error": message})
        if not self.finished.done():
            self.finished.set_result(None)

    async def write(self, data: bytes):
        if len(data) > 32768:
            raise ValueError("stdin chunk exceeds 32 KiB")
        await self.backend._rpc("write", {"processId": self.id, "data": base64.b64encode(data).decode()}, timeout=300)

    async def close_stdin(self):
        await self.backend._rpc("eof", {"processId": self.id}, timeout=300)

    async def signal(self, sig):
        await self.backend._rpc("signal", {"processId": self.id, "signal": sig})

    async def terminate(self):
        if not self.finished.done():
            await self.backend._terminate_quietly(self.id)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(self.finished), 5)


class Backend(Protocol):
    """Public adapters depend only on this interface; a Docker backend can implement it."""
    def info(self) -> dict: ...
    def environment(self) -> dict: ...
    async def start(self, argv, cwd=None, env=None, stdin=True, timeout_ms=None, max_output_bytes=16777216, arg0=None) -> Process: ...
    async def fs(self, method, params, session_id) -> dict: ...
    async def close_fs_session(self, session_id): ...


class AppleContainerBackend:
    def __init__(self, mounts=None, image="python:3.13-slim", container_bin="container", cpus=2, memory=512, proxy=None):
        self.mounts = mounts or []
        self.image, self.container_bin = image, container_bin
        self.cpus, self.memory = cpus, memory
        self.name = "external-sandbox-container-" + uuid.uuid4().hex[:12]
        self.child = None
        self.processes = {}
        self.pending = {}
        self.counter = 0
        self.lock = asyncio.Lock()
        self.reader_task = self.stderr_task = None
        self.ready = None
        self.closed = False
        self.stderr_tail = b""
        self._env = {}
        self.architecture = "unknown"
        self.proxy = proxy
        self.proxy_relay = None

    @property
    def default_cwd(self):
        return self.mounts[0].guestPath if self.mounts else "/workspace"

    def environment(self):
        return dict(self._env)

    def info(self):
        return {"status": "stopped" if self.closed else "ready", "backend": "apple-container",
                "architecture": self.architecture, "shell": "/bin/bash", "network": False,
                "proxyEnabled": self.proxy is not None,
                "mounts": [m.info() for m in self.mounts], "defaultCwd": self.default_cwd,
                "activeCommands": len(self.processes), "containerId": self.name, "image": self.image}

    def command(self):
        args = [self.container_bin, "run", "--rm", "--interactive", "--name", self.name,
                "--network", "none", "--cap-drop", "ALL", "--cpus", str(self.cpus),
                "--memory", f"{self.memory}M", "--progress", "none", "--env", "EXTERNAL_SANDBOX_CONTAINER_GUEST=1",
                "--entrypoint", "python3"]
        for mount in self.mounts:
            for target in [mount.guestPath, *mount.preservedPaths]:
                spec = f"type=bind,source={mount.hostPath},target={target}"
                if mount.mode == "ro":
                    spec += ",readonly"
                args += ["--mount", spec]
        # Only runtime Python modules are shared, never the project or host home.
        runtime = str(Path(__file__).resolve().parent)
        if "," in runtime:
            raise ValueError("Runtime installation path cannot contain commas")
        args += ["--mount", f"type=bind,source={runtime},target=/opt/external-sandbox-container,readonly",
                 self.image, "-I", "-u", "/opt/external-sandbox-container/guest_agent.py"]
        return args

    async def boot(self):
        if self.proxy is not None:
            address = self.proxy.address
            if not isinstance(address, tuple) or len(address) != 2 or address[0] != "127.0.0.1":
                raise ValueError("Host proxy must listen on a fixed IPv4 loopback address")
            self.proxy_relay = ProxyRelay(self._send, address=address)
        self.ready = asyncio.get_running_loop().create_future()
        self.child = await asyncio.create_subprocess_exec(*self.command(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        self.reader_task = asyncio.create_task(self._read())
        self.stderr_task = asyncio.create_task(self._stderr())
        try:
            await asyncio.wait_for(asyncio.shield(self.ready), 120)
            if self.proxy is not None:
                result = await self._rpc("configure_proxy", {"caPem": self.proxy.ca_pem})
                self._env.update(self.proxy.guest_env)
                self._env.update(result["environment"])
        except BaseException:
            await self.close()
            raise
        return self

    async def _stderr(self):
        while chunk := await self.child.stderr.read(8192):
            self.stderr_tail = (self.stderr_tail + chunk)[-16384:]

    async def _read(self):
        try:
            while True:
                size = struct.unpack(">I", await self.child.stdout.readexactly(4))[0]
                if size > MAX_FRAME:
                    raise RuntimeError("Invalid container agent frame")
                value = json.loads(await self.child.stdout.readexactly(size))
                if value.get("event") == "proxy":
                    if self.proxy_relay is None:
                        raise ValueError("Unexpected proxy frame while proxy is disabled")
                    self.proxy_relay.feed(value)
                elif value.get("event") == "ready":
                    self._env = value["environment"]
                    self.architecture = value["architecture"]
                    if not self.ready.done():
                        self.ready.set_result(None)
                elif value.get("event") == "process":
                    ident, message = value["processId"], value["message"]
                    process = self.processes.get(ident)
                    if process:
                        process.feed(message)
                        if message["type"] in ("exit", "error"):
                            self.processes.pop(ident, None)
                else:
                    future = self.pending.get(value.get("id"))
                    if future and not future.done():
                        if "error" in value:
                            future.set_exception(GuestError(value["error"]))
                        else:
                            future.set_result(value.get("result"))
        except (Exception, asyncio.CancelledError) as exc:
            if self.child.returncode is None:
                await asyncio.sleep(0.05)
            reason = f"Container agent disconnected: {self.stderr_tail.decode(errors='replace').strip() or str(exc)}"
            if self.ready and not self.ready.done():
                self.ready.set_exception(RuntimeError(reason))
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RuntimeError(reason))
            for process in self.processes.values():
                process.fail(reason)
            self.processes.clear()
        finally:
            if self.proxy_relay is not None:
                await self.proxy_relay.close()
            # A malformed/closed private transport must not leave a live relay or
            # command channel behind. Closing stdin also shuts down the guest.
            if self.child.stdin:
                self.child.stdin.close()

    async def _send(self, value):
        if self.closed or not self.child or self.child.returncode is not None:
            raise RuntimeError("Container agent is not running")
        payload = json.dumps(value, ensure_ascii=True).encode()
        if len(payload) > MAX_FRAME:
            raise ValueError("Agent request exceeds frame limit")
        async with self.lock:
            self.child.stdin.write(struct.pack(">I", len(payload)) + payload)
            await self.child.stdin.drain()

    async def _rpc(self, method, params, timeout=30):
        if self.closed or not self.child or self.child.returncode is not None:
            raise RuntimeError("Container agent is not running")
        self.counter += 1
        ident = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        try:
            await self._send({"id": ident, "method": method, "params": params})
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(ident, None)
            if not future.done():
                future.cancel()

    async def start(self, argv, cwd=None, env=None, stdin=True, timeout_ms=None, max_output_bytes=16777216, arg0=None):
        if len(self.processes) >= 16:
            raise BusyError("Maximum 16 concurrent commands")
        ident = uuid.uuid4().hex
        process = Process(self, ident)
        self.processes[ident] = process
        # Never interpolate a command into a host shell. Exact argv crosses framed JSON.
        task = asyncio.create_task(self._rpc("start", {"processId": ident, "argv": argv,
            "cwd": cwd or self.default_cwd, "env": self.environment() if env is None else env,
            "stdin": stdin, "timeoutMs": timeout_ms, "maxOutputBytes": max_output_bytes, "arg0": arg0}))
        try:
            await asyncio.shield(task)
            return process
        except BaseException:
            # The spawn could have succeeded before cancellation reached this coroutine.
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), 30)
            await self._terminate_quietly(ident)
            self.processes.pop(ident, None)
            raise

    async def _terminate_quietly(self, ident):
        with contextlib.suppress(Exception):
            await self._rpc("terminate", {"processId": ident}, timeout=5)

    async def fs(self, method, params, session_id):
        return await self._rpc("fs", {"sessionId": session_id, "method": method, "params": params})

    async def close_fs_session(self, session_id):
        with contextlib.suppress(Exception):
            await self._rpc("close_fs", {"sessionId": session_id})

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self.proxy_relay is not None:
            await self.proxy_relay.close()
        if self.child:
            if self.child.stdin:
                self.child.stdin.close()
            try:
                await asyncio.wait_for(self.child.wait(), 3)
            except TimeoutError:
                # Only remove this uniquely named sandbox; never touch unrelated containers.
                cleanup = await asyncio.create_subprocess_exec(self.container_bin, "stop", "--time", "1", self.name,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(cleanup.wait(), 10)
                if cleanup.returncode is None:
                    cleanup.kill()
                    await cleanup.wait()
                if self.child.returncode is None:
                    self.child.kill()
                await self.child.wait()
            for task in (self.reader_task, self.stderr_task):
                if task and not task.done():
                    task.cancel()
            await asyncio.gather(*(t for t in (self.reader_task, self.stderr_task) if t), return_exceptions=True)

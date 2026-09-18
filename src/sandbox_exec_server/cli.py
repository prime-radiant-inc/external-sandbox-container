"""Start the compatible localhost APIs with a disposable Apple Container."""
import argparse
import asyncio
import contextlib
import json
import signal
import sys

from aiohttp import web

from .api import create_app
from .backend import AppleContainerBackend, parse_mounts


class MountAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        mounts = list(getattr(namespace, self.dest, None) or [])
        mounts.append((values, "ro" if option_string == "--mount-ro" else "rw"))
        setattr(namespace, self.dest, mounts)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("paths", nargs="*", help="Writable host directories (same as --mount-rw)")
    result.add_argument("--backend", choices=["apple"], default="apple")
    result.add_argument("--image", default="python:3.13-slim", help="Linux OCI image with python3 and /bin/bash")
    result.add_argument("--container-bin", default="container", help="Apple Container CLI executable")
    result.add_argument("--port", type=int, default=8686, help="Loopback TCP port; 0 selects an available port")
    result.add_argument("--cpus", type=int, default=2)
    result.add_argument("--memory", type=int, default=512, help="Container memory in MiB")
    result.add_argument("--mount", "--mount-ro", "--mount-rw", dest="mounts", action=MountAction,
                        metavar="[NAME=]PATH", help="Share a host directory; --mount is read-write")
    result.add_argument("--preserve-paths", action="store_true", help="Also mount host directories at their original absolute paths")
    return result


async def serve(args):
    if not 0 <= args.port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    if not 1 <= args.cpus <= 64 or not 128 <= args.memory <= 65536:
        raise ValueError("CPUs must be 1–64 and memory 128–65536 MiB")
    mounts = parse_mounts([*(args.mounts or []), *((path, "rw") for path in args.paths)], args.preserve_paths)
    backend = AppleContainerBackend(mounts, image=args.image, container_bin=args.container_bin,
                                    cpus=args.cpus, memory=args.memory)
    runner = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    boot = asyncio.create_task(backend.boot())
    stopping = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait([boot, stopping], return_when=asyncio.FIRST_COMPLETED)
        if stopping in done:
            boot.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await boot
            return
        await boot
        app = create_app(backend)
        runner = web.AppRunner(app, handler_cancellation=True, shutdown_timeout=5)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", args.port)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        print(json.dumps({"event": "listening", "url": f"http://127.0.0.1:{port}", **backend.info()}), flush=True)
        # Loss of the sandbox is fatal. Never keep serving against a missing backend.
        done, _ = await asyncio.wait([stopping, backend.reader_task], return_when=asyncio.FIRST_COMPLETED)
        if backend.reader_task in done and not stop.is_set():
            raise RuntimeError("Container agent stopped unexpectedly")
    finally:
        stopping.cancel()
        if runner:
            await runner.cleanup()
        await backend.close()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main():
    args = parser().parse_args()
    try:
        asyncio.run(serve(args))
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"sandbox-exec-server: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

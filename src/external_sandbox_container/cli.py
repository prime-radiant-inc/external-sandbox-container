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
from .images import MINIMAL_IMAGE, ensure_tools_image
from .proxy import HostProxy, load_policy


class MountAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        mounts = list(getattr(namespace, self.dest, None) or [])
        mounts.append((values, "ro" if option_string == "--mount-ro" else "rw"))
        setattr(namespace, self.dest, mounts)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("paths", nargs="*", help="Writable host directories (same as --mount-rw)")
    result.add_argument("--backend", choices=["apple"], default="apple")
    result.add_argument("--image", help="Linux OCI image with python3 and /bin/bash (default: the development tools "
                                         f"image, built on first run; {MINIMAL_IMAGE} is a smaller alternative)")
    result.add_argument("--prepare-image", action="store_true", help="Build the development tools image, then exit")
    result.add_argument("--container-bin", default="container", help="Apple Container CLI executable")
    result.add_argument("--port", type=int, default=8687, help="Loopback TCP port (default: 8687); 0 selects an available port")
    result.add_argument("--cpus", type=int, default=2)
    result.add_argument("--memory", type=int, default=512, help="Container memory in MiB")
    result.add_argument("--mount", "--mount-ro", "--mount-rw", dest="mounts", action=MountAction,
                        metavar="[NAME=]PATH", help="Share a host directory; --mount is read-write")
    result.add_argument("--preserve-paths", action="store_true", help="Also mount host directories at their original absolute paths")
    result.add_argument("--proxy-config", metavar="PATH", help="Enable host-enforced HTTP(S) egress using this allow-list JSON file")
    result.add_argument("--write-setup", metavar="DIR", help="Write the bundled image recipe and proxy policy, then exit")
    return result


async def select_image(args):
    return args.image or await ensure_tools_image(args.container_bin)


async def serve(args):
    if not 0 <= args.port <= 65535:
        raise ValueError("Port must be between 0 and 65535")
    if not 1 <= args.cpus <= 64 or not 128 <= args.memory <= 65536:
        raise ValueError("CPUs must be 1–64 and memory 128–65536 MiB")
    mounts = parse_mounts([*(args.mounts or []), *((path, "rw") for path in args.paths)], args.preserve_paths)
    proxy = HostProxy(load_policy(args.proxy_config)) if args.proxy_config else None
    backend = AppleContainerBackend(mounts, image=args.image, container_bin=args.container_bin,
                                    cpus=args.cpus, memory=args.memory, proxy=proxy)
    runner = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async def start_sandbox():
        backend.image = await select_image(args)
        if proxy:
            await proxy.start()
        await backend.boot()

    boot = asyncio.create_task(start_sandbox())
    stopping = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait([boot, stopping], return_when=asyncio.FIRST_COMPLETED)
        if stopping in done:
            boot.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await boot
            return
        await boot
        app = create_app(backend, proxy=proxy)
        runner = web.AppRunner(app, handler_cancellation=True, shutdown_timeout=5)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", args.port)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        info = {"event": "listening", "url": f"http://127.0.0.1:{port}", **backend.info()}
        if proxy:
            info["proxyManagementUrl"] = f"http://127.0.0.1:{port}/proxy"
        print(json.dumps(info), flush=True)
        # Loss of the sandbox is fatal. Never keep serving against a missing backend.
        done, _ = await asyncio.wait([stopping, backend.reader_task], return_when=asyncio.FIRST_COMPLETED)
        if backend.reader_task in done and not stop.is_set():
            raise RuntimeError("Container agent stopped unexpectedly")
    finally:
        stopping.cancel()
        if not boot.done():
            boot.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await boot
        try:
            if runner:
                await runner.cleanup()
        finally:
            try:
                await backend.close()
            finally:
                try:
                    if proxy:
                        await proxy.close()
                finally:
                    for sig in (signal.SIGINT, signal.SIGTERM):
                        loop.remove_signal_handler(sig)


def main():
    args = parser().parse_args()
    try:
        if args.write_setup is not None:
            from .setup_files import write_setup

            print(f"Setup files ready in {write_setup(args.write_setup)}")
            return
        if args.prepare_image:
            if args.image:
                raise ValueError("--prepare-image only builds the development tools image; omit --image")
            print(f"Image ready: {asyncio.run(ensure_tools_image(args.container_bin))}")
            return
        asyncio.run(serve(args))
    except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"external-sandbox-container: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

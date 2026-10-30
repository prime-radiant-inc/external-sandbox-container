"""Proxy opt-in, early validation, and lifecycle ownership."""
import asyncio

import pytest

from external_sandbox_container import cli


def test_proxy_is_explicit_and_default_port_is_unchanged():
    args = cli.parser().parse_args([])
    assert args.proxy_config is None and args.port == 8687
    args = cli.parser().parse_args(["--proxy-config", "policy.local.json", "--port", "0"])
    assert args.proxy_config == "policy.local.json" and args.port == 0


async def test_bad_policy_fails_before_container_creation(monkeypatch):
    calls = []

    def invalid_policy(path):
        raise ValueError("Invalid proxy configuration")

    monkeypatch.setattr(cli, "load_policy", invalid_policy)
    monkeypatch.setattr(cli, "AppleContainerBackend", lambda *a, **kw: calls.append(kw))
    with pytest.raises(ValueError, match="Invalid proxy configuration"):
        await cli.serve(cli.parser().parse_args(["--proxy-config", "invalid.json"]))
    assert calls == []


@pytest.mark.parametrize("failure", ["proxy", "container"])
async def test_startup_failure_closes_container_before_proxy(monkeypatch, failure):
    calls = []

    class Proxy:
        def __init__(self, policy):
            assert policy == "compiled-policy"

        async def start(self):
            calls.append("proxy.start")
            if failure == "proxy":
                raise RuntimeError("proxy failed")

        async def close(self):
            calls.append("proxy.close")

    class Backend:
        def __init__(self, *args, proxy=None, **kwargs):
            assert isinstance(proxy, Proxy)

        async def boot(self):
            calls.append("container.boot")
            raise RuntimeError("container failed")

        async def close(self):
            calls.append("container.close")

    monkeypatch.setattr(cli, "load_policy", lambda path: "compiled-policy")
    monkeypatch.setattr(cli, "HostProxy", Proxy)
    monkeypatch.setattr(cli, "AppleContainerBackend", Backend)
    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        await cli.serve(cli.parser().parse_args(["--proxy-config", "policy.json"]))
    expected = ["proxy.start"] + (["container.boot"] if failure == "container" else [])
    assert calls == expected + ["container.close", "proxy.close"]


async def test_cancel_during_startup_cancels_boot_and_closes_both(monkeypatch):
    calls = []
    started = asyncio.Event()

    class Proxy:
        def __init__(self, policy):
            pass

        async def start(self):
            started.set()
            try:
                await asyncio.sleep(60)
            finally:
                calls.append("proxy.start-cancelled")

        async def close(self):
            calls.append("proxy.close")

    class Backend:
        def __init__(self, *a, **kw):
            pass

        async def boot(self):
            pytest.fail("Container must not boot after startup cancellation")

        async def close(self):
            calls.append("container.close")

    monkeypatch.setattr(cli, "load_policy", lambda path: None)
    monkeypatch.setattr(cli, "HostProxy", Proxy)
    monkeypatch.setattr(cli, "AppleContainerBackend", Backend)
    task = asyncio.create_task(cli.serve(cli.parser().parse_args(["--proxy-config", "policy.json"])))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == ["proxy.start-cancelled", "container.close", "proxy.close"]

"""Explicit forward-proxy routing without external networking."""
import asyncio
import contextlib
import socket
import ssl

import aiohttp
import pytest

from external_sandbox_container import cli
from external_sandbox_container.proxy import HostProxy
from external_sandbox_container.proxy_certificates import CertificateAuthority
from external_sandbox_container.proxy_policy import PolicyConfigError, ProxyPolicy


@pytest.mark.parametrize("value", [
    "http://127.0.0.1:7890", "http://localhost:80", "http://[::1]:7890",
])
def test_upstream_proxy_option(value):
    proxy = cli.startup_proxy(cli.parser().parse_args(["--proxy", "--upstream-proxy", value]))
    assert proxy.upstream_proxy == value
    assert proxy.policy.configuration() == {"allow": []}


@pytest.mark.parametrize("value", [
    "", "https://localhost:7890", "socks5://localhost:7890", "http://localhost",
    "http://user:password@localhost:7890", "http://localhost:7890/",
    "http://localhost:7890/path", "http://localhost:7890?query",
    "http://localhost:7890#fragment", "http://localhost:0", "http://localhost:65536",
    "http://localhost:abc", "http://localhost:07890", "http://localhost:7890\n",
    " http://localhost:7890", "http://127.1:7890", "http://localhost:7890?",
])
def test_invalid_upstream_proxy_option(value):
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--proxy", "--upstream-proxy", value])
    with pytest.raises(ValueError, match="Upstream proxy must"):
        HostProxy(ProxyPolicy.from_config({"allow": []}), upstream_proxy=value)


async def test_upstream_requires_policy_before_container_creation(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "AppleContainerBackend", lambda *a, **kw: calls.append(kw))
    with pytest.raises(ValueError, match="requires --proxy"):
        await cli.serve(cli.parser().parse_args(["--upstream-proxy", "http://localhost:7890"]))
    assert calls == []


def test_upstream_proxy_with_policy_file(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text('{"allow": [{"origin": "https://example.test"}]}')
    proxy = cli.startup_proxy(cli.parser().parse_args([
        "--proxy-config", str(path), "--upstream-proxy", "http://localhost:7890",
    ]))
    assert proxy.upstream_proxy == "http://localhost:7890"
    assert "https://example.test" in proxy.policy.rules


def test_cidrs_rejected_at_startup_and_policy_update():
    policy = ProxyPolicy.from_config({"allow": [{"origin": "https://example.test",
                                               "allowCidrs": ["127.0.0.0/8"]}]})
    with pytest.raises(PolicyConfigError, match="allowCidrs"):
        HostProxy(policy, upstream_proxy="http://localhost:7890")
    empty = ProxyPolicy.from_config({"allow": []})
    proxy = HostProxy(empty, upstream_proxy="http://localhost:7890")
    with pytest.raises(PolicyConfigError, match="allowCidrs"):
        proxy.update_policy(policy.configuration())
    assert proxy.policy is empty


@pytest.fixture
async def public_dns(monkeypatch):
    loop = asyncio.get_running_loop()
    actual = loop.getaddrinfo
    calls = []

    async def resolve(host, port, **kwargs):
        if host == "target.example.test":
            calls.append(host)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]
        return await actual(host, port, **kwargs)

    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    return calls


@pytest.fixture
async def forward_proxy():
    ca = CertificateAuthority()
    requests = []
    tasks = set()

    async def handle(reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            requests.append(head)
            if head.startswith(b"CONNECT "):
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                await writer.start_tls(ca.server_context("target.example.test"))
                head = await reader.readuntil(b"\r\n\r\n")
                requests.append(head)
            if b"/redirect " in head:
                writer.write(b"HTTP/1.1 302 Found\r\nLocation: http://denied.example.test/\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            else:
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 16\r\nConnection: close\r\n\r\nsynthetic-secret")
            await writer.drain()
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def accept(reader, writer):
        task = asyncio.create_task(handle(reader, writer))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    endpoint = "http://localhost:%d" % server.sockets[0].getsockname()[1]
    try:
        yield endpoint, ca, requests
    finally:
        server.close()
        await server.wait_closed()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("scheme", ["http", "https"])
async def test_requests_use_forward_proxy_and_preserve_policy(scheme, forward_proxy, public_dns):
    endpoint, ca, requests = forward_proxy
    origin = f"{scheme}://target.example.test"
    rule = {"origin": origin, "methods": ["GET"], "paths": ["/allowed", "/redirect"]}
    headers = {}
    if scheme == "https":
        rule["credential"] = {"header": "Authorization", "placeholder": "placeholder", "secretEnv": "KEY"}
        headers["Authorization"] = "placeholder"
    policy = ProxyPolicy.from_config({"allow": [rule]}, {"KEY": "synthetic-secret"})
    proxy = HostProxy(policy, upstream_proxy=endpoint,
                      upstream_ssl_context=ssl.create_default_context(cadata=ca.pem))
    await proxy.start()
    try:
        async with aiohttp.ClientSession() as client:
            options = {"proxy": "http://%s:%d" % proxy.address,
                       "ssl": ssl.create_default_context(cadata=proxy.ca_pem), "headers": headers}
            async with client.get(origin + "/allowed", **options) as response:
                assert response.status == 200
                assert await response.text() == ("[REDACTED]" if scheme == "https" else "synthetic-secret")
            if scheme == "https":
                assert requests[0].startswith(b"CONNECT target.example.test:443 HTTP/1.1\r\n")
                assert b"Authorization: synthetic-secret\r\n" in requests[1] or b"authorization: synthetic-secret\r\n" in requests[1]
            else:
                assert requests[0].startswith(b"GET http://target.example.test/allowed HTTP/1.1\r\n")
            count = len(requests)
            for method, path in [("POST", "/allowed"), ("GET", "/denied")]:
                async with client.request(method, origin + path, **options) as response:
                    assert response.status == 403
                    await response.read()
            if scheme == "https":
                async with client.get(origin + "/allowed", **{**options, "headers": {}}) as response:
                    assert response.status == 403
                    await response.read()
            assert len(requests) == count
            async with client.get(origin + "/redirect", **options) as response:
                assert response.status == 403
                await response.read()
            assert len(requests) == count * 2  # Only the allowed redirect source reached the proxy.
        assert public_dns == ["target.example.test", "target.example.test"]
    finally:
        await proxy.close()


async def test_nonpublic_target_denied_before_upstream_contact(forward_proxy):
    endpoint, _, requests = forward_proxy
    proxy = HostProxy(ProxyPolicy.from_config({"allow": [{"origin": "http://127.0.0.1"}]}),
                      upstream_proxy=endpoint)
    await proxy.start()
    try:
        async with aiohttp.ClientSession() as client:
            async with client.get("http://127.0.0.1/", proxy="http://%s:%d" % proxy.address) as response:
                assert response.status == 403
                await response.read()
        assert requests == []
    finally:
        await proxy.close()


async def test_connect_still_verifies_target_certificate(forward_proxy, public_dns):
    endpoint, _, requests = forward_proxy
    proxy = HostProxy(ProxyPolicy.from_config({"allow": [{"origin": "https://target.example.test"}]}),
                      upstream_proxy=endpoint)
    await proxy.start()
    try:
        async with aiohttp.ClientSession() as client:
            async with client.get("https://target.example.test/", proxy="http://%s:%d" % proxy.address,
                                  ssl=ssl.create_default_context(cadata=proxy.ca_pem)) as response:
                assert response.status == 502
                await response.read()
        assert len(requests) == 1 and requests[0].startswith(b"CONNECT ")
    finally:
        await proxy.close()

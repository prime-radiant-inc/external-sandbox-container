"""Private proxy transport: fixed routing, bounded windows, lifecycle and guest setup."""
import asyncio
import base64
import contextlib
import json
import os
import ssl
import struct
from types import SimpleNamespace

import pytest

from external_sandbox_container.backend import AppleContainerBackend
from external_sandbox_container.guest_proxy import GuestProxy
from external_sandbox_container.proxy_relay import CHUNK_SIZE, MAX_STREAMS, ProxyRelay


def frame(action, ident=1, **fields):
    return {"event": "proxy", "action": action, "streamId": ident, **fields}


def framed(value):
    data = json.dumps(value).encode()
    return struct.pack(">I", len(data)) + data


async def eventually(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


class MemoryWriter:
    def __init__(self, blocked=False):
        self.transport = self
        self.closed = False
        self.data = bytearray()
        self.draining = asyncio.Event()
        self.release = asyncio.Event()
        if not blocked:
            self.release.set()

    def set_write_buffer_limits(self, **kwargs):
        self.limits = kwargs

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        self.draining.set()
        await self.release.wait()

    def can_write_eof(self):
        return True

    def write_eof(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


@contextlib.asynccontextmanager
async def relay_pair(endpoint):
    guest = host = None
    observations = []

    async def from_guest(value):
        observations.append(("guest", value))
        host.feed(value)

    async def from_host(value):
        observations.append(("host", value))
        guest.feed(value)

    host = ProxyRelay(from_host, address=endpoint)
    guest = ProxyRelay(from_guest)
    listener = await asyncio.start_server(guest.accept, "127.0.0.1", 0, limit=CHUNK_SIZE)
    try:
        yield host, guest, listener.sockets[0].getsockname(), observations
    finally:
        listener.close()
        await listener.wait_closed()
        await guest.close()
        await host.close()


async def test_binary_full_duplex_multiple_streams_and_half_close():
    handlers = set()

    async def echo(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        try:
            writer.write(b"ready")
            await writer.drain()
            while chunk := await reader.read(7919):
                writer.write(chunk)
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    endpoint = await asyncio.start_server(echo, "127.0.0.1", 0)
    try:
        async with relay_pair(endpoint.sockets[0].getsockname()) as (host, guest, address, seen):
            payload = os.urandom(512 * 1024)

            async def exchange():
                reader, writer = await asyncio.open_connection(*address)
                assert await reader.readexactly(5) == b"ready"
                writer.write(payload)
                await writer.drain()
                writer.write_eof()
                assert await reader.read() == payload
                writer.close()
                await writer.wait_closed()

            async with asyncio.timeout(10):
                await asyncio.gather(*(exchange() for _ in range(3)))
                await eventually(lambda: not host.streams and not guest.streams)
            for _, value in seen:
                if value["action"] == "data":
                    assert len(base64.b64decode(value["data"])) <= CHUNK_SIZE
                assert "host" not in value and "port" not in value and "address" not in value
    finally:
        endpoint.close()
        await endpoint.wait_closed()
        for handler in list(handlers):
            handler.cancel()
        await asyncio.gather(*handlers, return_exceptions=True)


async def test_one_chunk_credit_window_and_spoofed_ack_rejected():
    sent = []
    relay = None

    async def send(value):
        sent.append(value)
        if value["action"] == "open":
            relay.feed(frame("opened"))

    relay = ProxyRelay(send)
    reader = asyncio.StreamReader()
    reader.feed_data(b"x" * (CHUNK_SIZE * 3))
    reader.feed_eof()
    writer = MemoryWriter()
    relay.accept(reader, writer)
    try:
        await eventually(lambda: any(value["action"] == "data" for value in sent))
        await asyncio.sleep(0.01)
        assert sum(value["action"] == "data" for value in sent) == 1
        with pytest.raises(ValueError, match="acknowledgement"):
            relay.feed(frame("ack", seq=2))
        relay.feed(frame("ack", seq=1))
        await eventually(lambda: sum(value["action"] == "data" for value in sent) == 2)
        assert len(relay.streams) == 1
        assert relay.streams[1].incoming.maxsize == 2
    finally:
        await asyncio.wait_for(relay.close(), 1)
    assert writer.closed and not relay.streams and not relay.tasks


async def test_blocked_socket_drain_bounds_receive_window_without_blocking_other_streams():
    relay = None
    sent = []

    async def send(value):
        sent.append(value)
        if value["action"] == "open":
            relay.feed(frame("opened", value["streamId"]))

    relay = ProxyRelay(send)
    blocked, healthy = MemoryWriter(blocked=True), MemoryWriter()
    relay.accept(asyncio.StreamReader(), blocked)
    relay.accept(asyncio.StreamReader(), healthy)
    try:
        await eventually(lambda: len(sent) == 2)
        encoded = base64.b64encode(b"x" * CHUNK_SIZE).decode()
        relay.feed(frame("data", 1, seq=1, data=encoded))
        await blocked.draining.wait()
        assert relay.streams[1].receiving is True
        assert len(blocked.data) == CHUNK_SIZE
        with pytest.raises(ValueError, match="window"):
            relay.feed(frame("data", 1, seq=2, data="eA=="))
        relay.feed(frame("data", 2, seq=1, data="aGVhbHRoeQ=="))
        await eventually(lambda: any(value["action"] == "ack" and value["streamId"] == 2 for value in sent))
        assert healthy.data == b"healthy"
        assert not any(value["action"] == "ack" and value["streamId"] == 1 for value in sent)
    finally:
        await asyncio.wait_for(relay.close(), 1)
    assert blocked.closed and healthy.closed and not relay.tasks


@pytest.mark.parametrize("value", [
    frame("open", host="attacker.example", port=443),
    frame("open", address=["127.0.0.1", 22]),
    frame("open", True), frame("open", 0), frame("open", 2**53),
    frame("bogus"), frame("data", seq=1, data="eA=="),
])
async def test_host_rejects_malformed_frames_and_guest_target_selection(value):
    async def send(value):
        pass
    relay = ProxyRelay(send, address=("127.0.0.1", 12345))
    with pytest.raises(ValueError):
        relay.feed(value)
    assert not relay.streams
    await relay.close()


async def test_duplicate_open_and_replayed_ids_are_rejected():
    async def send(value):
        pass
    relay = ProxyRelay(send, address=("127.0.0.1", 12345))
    relay.feed(frame("open"))
    with pytest.raises(ValueError, match="open"):
        relay.feed(frame("open"))
    relay.feed(frame("close"))
    assert not relay.streams
    with pytest.raises(ValueError, match="open"):
        relay.feed(frame("open"))
    await relay.close()
    assert not relay.tasks


async def test_stream_count_caps_tasks_and_rejects_excess_connections():
    async def send(value):
        pass
    relay = ProxyRelay(send)
    writers = [MemoryWriter() for _ in range(MAX_STREAMS + 1)]
    for writer in writers:
        relay.accept(asyncio.StreamReader(), writer)
    assert len(relay.tasks) == len(relay.streams) == MAX_STREAMS
    assert writers[-1].closed
    await relay.close()
    assert all(writer.closed for writer in writers)
    assert not relay.tasks


@pytest.mark.parametrize("value", [
    frame("data", seq=1, data="!badbase64!"),
    frame("data", seq=1, data=""),
    frame("data", seq=1, data=base64.b64encode(b"x" * (CHUNK_SIZE + 1)).decode()),
    frame("data", seq=True, data="eA=="), frame("data", seq=2, data="eA=="),
    frame("ack", seq=1), frame("opened"),
])
async def test_bad_live_stream_frames_fail_closed(value):
    relay = None
    async def send(value):
        if value["action"] == "open":
            relay.feed(frame("opened"))
    relay = ProxyRelay(send)
    relay.accept(asyncio.StreamReader(), MemoryWriter())
    try:
        await eventually(lambda: relay.streams[1].opened.done())
        with pytest.raises(ValueError):
            relay.feed(value)
    finally:
        await relay.close()


async def test_guest_installs_only_public_ca_and_local_proxy_environment(tmp_path):
    certificates = ssl.create_default_context().get_ca_certs(binary_form=True)
    if not certificates:
        pytest.skip("System trust store has no CA certificates")
    pem = ssl.DER_cert_to_PEM_cert(certificates[0])
    async def send(value):
        pass
    proxy = GuestProxy(send)
    try:
        environment = await proxy.start(pem, str(tmp_path))
        assert environment["HTTP_PROXY"].startswith("http://127.0.0.1:")
        assert environment["HTTPS_PROXY"] == environment["http_proxy"] == environment["HTTP_PROXY"]
        assert environment["NO_PROXY"] == environment["no_proxy"] == ""
        assert environment["NODE_USE_ENV_PROXY"] == "1"
        assert environment["SSL_CERT_FILE"] == environment["NODE_EXTRA_CA_CERTS"]
        assert pem in (tmp_path / "ca-bundle.pem").read_text()
        assert "PRIVATE KEY" not in (tmp_path / "ca-bundle.pem").read_text()
        assert len(list(tmp_path.iterdir())) == 1
    finally:
        await proxy.close()
    assert not proxy.listener.is_serving()


async def test_invalid_ca_prevents_listener_start(tmp_path):
    async def send(value):
        pass
    proxy = GuestProxy(send)
    with pytest.raises(ValueError):
        await proxy.start("not a certificate", str(tmp_path))
    assert proxy.listener is None
    await proxy.close()


class FakeChild:
    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode = None
        self.done = asyncio.Event()
        self.stdin = self
        self.messages = []

    def write(self, data):
        size = struct.unpack(">I", data[:4])[0]
        value = json.loads(data[4:4 + size])
        self.messages.append(value)
        if value.get("method") == "configure_proxy":
            self.stdout.feed_data(framed({"id": value["id"], "result": {"environment": {
                "HTTP_PROXY": "http://127.0.0.1:3128", "SSL_CERT_FILE": "/run/external-sandbox-proxy/ca-bundle.pem"}}}))

    async def drain(self):
        pass

    def close(self):
        if self.returncode is None:
            self.returncode = 0
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self.done.set()

    async def wait(self):
        await self.done.wait()
        return self.returncode


async def test_backend_boot_waits_for_proxy_configuration_and_preserves_network_none(monkeypatch):
    child = FakeChild()
    child.stdout.feed_data(framed({"event": "ready", "environment": {"PATH": "/usr/bin"}, "architecture": "aarch64"}))
    async def spawn(*args, **kwargs):
        assert args[args.index("--network") + 1] == "none"
        assert args[args.index("--cap-drop") + 1] == "ALL"
        return child
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    proxy = SimpleNamespace(address=("127.0.0.1", 12345), ca_pem="PUBLIC CA", guest_env={"API_KEY": "placeholder"})
    backend = AppleContainerBackend(proxy=proxy)
    await backend.boot()
    try:
        assert backend.environment() == {"PATH": "/usr/bin", "API_KEY": "placeholder",
            "HTTP_PROXY": "http://127.0.0.1:3128", "SSL_CERT_FILE": "/run/external-sandbox-proxy/ca-bundle.pem"}
        assert child.messages == [{"id": 1, "method": "configure_proxy", "params": {"caPem": "PUBLIC CA"}}]
        assert backend.proxy_relay.address == proxy.address
        backend.proxy_relay.feed(frame("open"))
        future = asyncio.get_running_loop().create_future()
        backend.pending[123] = future
        child.stdout.feed_data(framed({"id": 123, "result": {"still": "responsive"}}))
        assert await asyncio.wait_for(future, 1) == {"still": "responsive"}
    finally:
        await backend.close()
    assert backend.proxy_relay.closed and not backend.proxy_relay.tasks


async def test_malformed_guest_frame_disconnects_transport_and_closes_relays(monkeypatch):
    child = FakeChild()
    child.stdout.feed_data(framed({"event": "ready", "environment": {}, "architecture": "aarch64"}))
    async def spawn(*args, **kwargs):
        return child
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    proxy = SimpleNamespace(address=("127.0.0.1", 12345), ca_pem="PUBLIC CA", guest_env={})
    backend = await AppleContainerBackend(proxy=proxy).boot()
    child.stdout.feed_data(framed(frame("open", host="127.0.0.1", port=22)))
    await asyncio.wait_for(backend.reader_task, 1)
    assert backend.proxy_relay.closed and child.returncode == 0
    await backend.close()


async def test_verified_https_and_credential_substitution_through_full_relay():
    """Default Python TLS verification must work through CONNECT and both relays."""
    from aiohttp import web
    import h11
    from external_sandbox_container.proxy import HostProxy, ProxyPolicy
    from external_sandbox_container.proxy_certificates import CertificateAuthority

    payload = os.urandom(256 * 1024)
    seen = []
    upstream_ca = CertificateAuthority()

    async def handle(request):
        seen.append((request.headers.get("Authorization"), await request.read()))
        return web.Response(body=b"upstream-ok:integration-fake-key")

    app = web.Application()
    app.router.add_post("/test", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=upstream_ca.server_context("127.0.0.1"))
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    authority = f"127.0.0.1:{port}"
    policy = ProxyPolicy.from_config({"allow": [{"origin": f"https://{authority}",
        "allowCidrs": ["127.0.0.1/32"], "credential": {"header": "Authorization",
        "placeholder": "placeholder", "secretEnv": "TEST_KEY", "prefix": "Bearer "}}]},
        {"TEST_KEY": "integration-fake-key"})
    proxy = HostProxy(policy, upstream_ssl_context=ssl.create_default_context(cadata=upstream_ca.pem))
    await proxy.start()
    writer = None
    try:
        async with relay_pair(proxy.address) as (_, _, address, _):
            reader, writer = await asyncio.open_connection(*address)
            writer.write(f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode())
            await writer.drain()
            reply = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 3)
            assert reply.startswith(b"HTTP/1.1 200")
            await writer.start_tls(ssl.create_default_context(cadata=proxy.ca_pem), server_hostname="127.0.0.1")
            connection = h11.Connection(h11.CLIENT)
            writer.write(connection.send(h11.Request(method="POST", target="/test", headers=[
                ("Host", authority), ("Authorization", "placeholder"),
                ("Content-Length", str(len(payload))), ("Connection", "close")])))
            writer.write(connection.send(h11.Data(data=payload)))
            writer.write(connection.send(h11.EndOfMessage()))
            await writer.drain()
            body = bytearray()
            async with asyncio.timeout(10):
                while True:
                    event = connection.next_event()
                    if event is h11.NEED_DATA:
                        connection.receive_data(await reader.read(32768))
                    elif isinstance(event, h11.Data):
                        body.extend(event.data)
                    elif isinstance(event, h11.Response):
                        assert event.status_code == 200
                    elif isinstance(event, h11.EndOfMessage):
                        break
            assert body == b"upstream-ok:[REDACTED]"
            assert seen == [("Bearer integration-fake-key", payload)]
    finally:
        if writer is not None:
            writer.close()
        await proxy.close()
        await runner.cleanup()

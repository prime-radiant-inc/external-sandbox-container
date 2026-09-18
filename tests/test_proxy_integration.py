"""Actual Apple Container -> framed pipe -> host proxy -> synthetic HTTPS service."""
import asyncio
import base64
import datetime
import ipaddress
import json
import os
import ssl

from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
import pytest
import pytest_asyncio

from sandbox_exec_server.backend import AppleContainerBackend
from sandbox_exec_server.proxy import HostProxy, ProxyPolicy

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module"),
              pytest.mark.skipif(os.environ.get("RUN_APPLE_CONTAINER_TESTS") != "1",
                                 reason="Set RUN_APPLE_CONTAINER_TESTS=1")]

SECRET = "synthetic-private-key-only-on-the-host-729cb1"
PLACEHOLDER = "public-demo-placeholder"


def tls_contexts(directory):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Proxy integration fixture")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), False)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False,
                content_commitment=False, data_encipherment=False, key_agreement=False,
                key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), True)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = directory / "fixture.pem", directory / "fixture.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    key_path.chmod(0o600)
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(cert_path, key_path)
    client = ssl.create_default_context(cafile=str(cert_path))
    return server, client


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def proxy_sandbox(tmp_path_factory):
    directory = tmp_path_factory.mktemp("proxy-upstream")
    server_tls, client_tls = tls_contexts(directory)
    received = []

    async def echo(request):
        body = await request.read()
        received.append({"path": request.path, "authorization": request.headers.get("Authorization"), "body": body})
        # Returning the injected header exercises defense-in-depth response redaction.
        return web.Response(body=request.headers.get("Authorization", "").encode() + b"\n" + body)

    async def stream(request):
        received.append({"path": request.path})
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        try:
            await response.write(b"data: first\n\n")
            await asyncio.sleep(0.5)
            await response.write(b"data: second\n\n")
        except ConnectionResetError:
            pass
        return response

    app = web.Application()
    app.router.add_route("*", "/echo", echo)
    app.router.add_get("/stream", stream)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_tls)
    await site.start()
    origin = f"https://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    config = {"allow": [{"origin": origin, "methods": ["GET", "POST"], "paths": ["/echo", "/stream"],
                         "allowCidrs": ["127.0.0.1/32"],
                         "credential": {"header": "Authorization", "placeholder": f"Bearer {PLACEHOLDER}",
                                        "secretEnv": "FIXTURE_KEY", "prefix": "Bearer "}}],
              "guestEnv": {"FIXTURE_KEY": PLACEHOLDER}}
    proxy = HostProxy(ProxyPolicy.from_config(config, secrets={"FIXTURE_KEY": SECRET}), upstream_ssl_context=client_tls)
    backend = AppleContainerBackend(proxy=proxy, image=os.environ.get("SANDBOX_TEST_IMAGE", "python:3.13-slim"))
    try:
        await proxy.start()
        await backend.boot()
        yield backend, proxy, origin, received, config
    finally:
        await backend.close()
        await proxy.close()
        await runner.cleanup()


async def collect(process):
    out, err = bytearray(), bytearray()
    async with asyncio.timeout(25):
        while True:
            event = await process.events.get()
            if event["type"] == "stdout":
                out.extend(base64.b64decode(event["data"]))
            elif event["type"] == "stderr":
                err.extend(base64.b64decode(event["data"]))
            elif event["type"] == "exit":
                assert event["exitCode"] == 0, bytes(err).decode(errors="replace")
                return bytes(out)
            else:
                pytest.fail(str(event))


async def run_python(backend, source):
    return await collect(await backend.start(["/usr/local/bin/python3", "-u", "-c", source],
                                             stdin=False, timeout_ms=20000))


async def test_verified_https_binary_post_and_hidden_credentials(proxy_sandbox):
    backend, proxy, origin, received, _ = proxy_sandbox
    source = f"""
import os, json, urllib.request, base64
body = bytes(range(256)) * 1024
request = urllib.request.Request({origin + '/echo'!r}, data=body,
    headers={{'Authorization': 'Bearer ' + os.environ['FIXTURE_KEY']}})
with urllib.request.urlopen(request, timeout=10) as response:
    data = response.read()
print(json.dumps({{'data':base64.b64encode(data).decode(), 'key':os.environ['FIXTURE_KEY'],
                  'interfaces':os.listdir('/sys/class/net'), 'ca':os.environ['SSL_CERT_FILE']}}))
"""
    result = json.loads(await run_python(backend, source))
    data = base64.b64decode(result["data"])
    assert SECRET.encode() not in data
    assert data.endswith(bytes(range(256)) * 1024)
    assert result["key"] == PLACEHOLDER
    assert result["interfaces"] == ["lo"]
    assert result["ca"].startswith("/run/")
    assert received[-1]["authorization"] == f"Bearer {SECRET}"
    assert received[-1]["body"] == bytes(range(256)) * 1024
    assert SECRET not in json.dumps(proxy.snapshot())
    assert SECRET not in json.dumps(backend.environment())


async def test_denied_destination_path_and_bad_placeholder_do_not_reach_upstream(proxy_sandbox):
    backend, _, origin, received, _ = proxy_sandbox
    before = len(received)
    source = f"""
import urllib.request, urllib.error, json
results=[]
for url, token in [({origin + '/not-allowed'!r}, 'Bearer {PLACEHOLDER}'),
                   ({origin + '/echo'!r}, 'wrong-token'),
                   ('http://not-allowed.invalid/', 'Bearer {PLACEHOLDER}')]:
    try:
        urllib.request.urlopen(urllib.request.Request(url, headers={{'Authorization':token}}), timeout=5)
        results.append('unexpected-success')
    except urllib.error.HTTPError as error:
        results.append(error.code)
print(json.dumps(results))
"""
    assert json.loads(await run_python(backend, source)) == [403, 403, 403]
    assert len(received) == before


async def test_proxy_environment_cannot_enable_direct_network_access(proxy_sandbox):
    backend, _, _, _, _ = proxy_sandbox
    source = """
import socket, os, json
for key in list(os.environ):
    if 'proxy' in key.lower(): del os.environ[key]
failures=[]
for target in [('1.1.1.1', 443), ('192.168.64.1', 8687)]:
    try:
        connection=socket.create_connection(target, timeout=1)
        connection.close()
        failures.append(False)
    except OSError:
        failures.append(True)
print(json.dumps(failures))
"""
    assert json.loads(await run_python(backend, source)) == [True, True]


async def test_streaming_and_simultaneous_command_rpc(proxy_sandbox):
    backend, _, origin, _, _ = proxy_sandbox
    source = f"""
import urllib.request, os
request=urllib.request.Request({origin + '/stream'!r}, headers={{'Authorization':'Bearer '+os.environ['FIXTURE_KEY']}})
with urllib.request.urlopen(request, timeout=10) as response:
    print(response.readline().decode().strip(), flush=True)
    print(response.read().decode().strip(), flush=True)
"""
    process = await backend.start(["/usr/local/bin/python3", "-u", "-c", source], stdin=False, timeout_ms=15000)
    first = await asyncio.wait_for(process.events.get(), 10)
    assert first["type"] == "stdout", first
    assert b"data: first" in base64.b64decode(first["data"])
    other = await run_python(backend, "print('command-rpc-still-works')")
    assert other == b"command-rpc-still-works\n"
    assert b"data: second" in await collect(process)


async def test_live_policy_change_revokes_next_request(proxy_sandbox):
    backend, proxy, origin, _, config = proxy_sandbox
    proxy.update_policy({"allow": [], "guestEnv": config["guestEnv"]})
    try:
        source = f"""
import urllib.request, urllib.error
try:
    urllib.request.urlopen({origin + '/echo'!r}, timeout=5)
    raise AssertionError('unexpected-success')
except urllib.error.URLError:
    print('blocked')
"""
        assert await run_python(backend, source) == b"blocked\n"
    finally:
        proxy.update_policy(config)

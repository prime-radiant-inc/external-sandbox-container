"""Guest loopback proxy endpoint. Policy and upstream networking remain on host."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import ssl

if __package__:
    from .proxy_relay import ProxyRelay
else:
    from proxy_relay import ProxyRelay


class GuestProxy:
    def __init__(self, send):
        self.relay = ProxyRelay(send)
        self.listener = None
        self.environment = {}

    async def start(self, ca_pem, directory="/run/remote-sandbox-proxy"):
        # Only public CA material reaches the guest. Preserve public system roots
        # for applications that also communicate with guest-local HTTPS services.
        if not isinstance(ca_pem, str) or len(ca_pem) > 65536 or "-----BEGIN CERTIFICATE-----" not in ca_pem:
            raise ValueError("Invalid proxy CA certificate")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=ca_pem)
        roots = ""
        system_ca = ssl.get_default_verify_paths().cafile
        if system_ca:
            roots = Path(system_ca).read_text()
        root = Path(directory)
        root.mkdir(mode=0o755, parents=True, exist_ok=True)
        bundle = root / "ca-bundle.pem"
        # Replace atomically; never follow a guest-created symlink to another path.
        temporary = root / f".ca-{os.getpid()}.pem"
        with temporary.open("x") as fp:
            fp.write(roots + "\n" + ca_pem)
        os.replace(temporary, bundle)
        self.listener = await asyncio.start_server(self.relay.accept, "127.0.0.1", 0, limit=32768)
        port = self.listener.sockets[0].getsockname()[1]
        endpoint = f"http://127.0.0.1:{port}"
        self.environment = {key: endpoint for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
        self.environment.update({"NO_PROXY": "", "no_proxy": ""})
        self.environment["NODE_USE_ENV_PROXY"] = "1"
        self.environment.update({key: str(bundle) for key in (
            "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")})
        return self.environment

    async def close(self):
        if self.listener:
            self.listener.close()
            await self.listener.wait_closed()
        await self.relay.close()

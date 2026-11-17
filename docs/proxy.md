# Host-managed HTTP(S) proxy

The proxy runs inside the server's Python process on the Mac. The container
continues to start with `--network none --cap-drop ALL`. A guest loopback
listener relays bytes over the existing framed stdin/stdout channel to that
one host proxy. The guest cannot supply a different host socket destination.

```text
guest command -> guest loopback proxy -> framed command pipe
              -> host Python proxy -> approved HTTP(S) service
```

## Start and inspect

```sh
uv run external-sandbox-container --proxy-config examples/proxy-public.json
```

The public example permits GET/HEAD requests to `https://example.com` and needs
no credentials. With the server running, try a command through the existing API:

```sh
curl -sS http://127.0.0.1:8687/exec -H 'Content-Type: application/json' --data-binary @- <<'JSON'
{"command":"python3 -c 'import urllib.request; print(urllib.request.urlopen(\"https://example.com\").status)'"}
JSON
```

Open `http://127.0.0.1:8687/proxy` to edit the JSON policy and view recent allowed
and blocked requests. UI edits are runtime-only. Copy the edited configuration
into your own file to keep it across restarts.

To begin with nothing allowed and build the policy on that page, start the
server with `--proxy` in place of a policy file:

```sh
uv run external-sandbox-container --proxy
```

`--proxy` starts the proxy with the policy `{"allow": []}`, which denies all
destinations. When both options are given, the file supplies the policy.
`guestEnv` cannot be changed on the page, so placeholder variables for
credential rules need a policy file. With neither `--proxy` nor
`--proxy-config`, the relay is disabled entirely and `/proxy` is not served.

The policy is validated before the container starts. The host proxy starts
first; the guest listener and CA bundle are ready before the execution API
opens. Shutdown stops API work, the guest/relay/container, and then the host
proxy. A broken proxy connection fails the request without falling back to
direct networking.

## Upstream forward proxy

For hosts that require a corporate proxy or a local proxy such as Clash/mihomo,
route allowed requests through an explicitly configured HTTP forward proxy:

```sh
uv run external-sandbox-container --proxy-config examples/proxy-public.json \
  --upstream-proxy http://127.0.0.1:7890
```

The option requires `--proxy` or `--proxy-config`. The URL must be
`http://host:port`, without credentials, a path (including a trailing slash),
query, or fragment. HTTPS and SOCKS proxy URLs are not supported. The endpoint
may be loopback or private; the target public-address checks do not apply to
the proxy itself. Without this option, direct, IP-pinned egress is unchanged.
Environment proxy variables are still ignored and proxy failure never falls
back to a direct connection.

Origin, method, path, placeholder authorization, credential replacement,
response redaction, and redirect reauthorization remain local. HTTP requests
use the forward proxy's absolute-URL form; HTTPS requests use CONNECT to the
target hostname and port, followed by TLS that verifies the target certificate
against the host trust store.

**Trust boundary:** local DNS resolution and public-address checks remain a
preflight requirement, but the forward proxy resolves the actual destination.
The checked IP cannot be pinned or verified through a hostname CONNECT tunnel.
Trust the forward proxy and its DNS/address controls; the local preflight
alone does not prevent a different remote DNS answer or DNS rebinding.
Proxy-only DNS names and local fake-IP DNS answers that are not public will
still be denied. To avoid silently weakening explicit IP restrictions,
`allowCidrs` is rejected both at startup and on policy updates in upstream
mode. Use direct mode when enforced IP ranges are required. Plain HTTP
requests are visible to the forward proxy; HTTPS payloads remain protected
by verified target TLS unless the host explicitly trusts an intercepting CA.

## Policy and credentials

Configuration uses the v86 proxy's `allow` and `guestEnv` JSON schema. An allow
rule contains an exact `origin` (scheme, host, port), optional `methods` and
exact `paths`, and optional `allowCidrs` for the resolved upstream IP. No rule
means no access. Without `allowCidrs`, only public addresses are permitted.
Private services require both an origin and an explicit IP range in direct
mode. In that mode, the actual connection uses an approved numeric address,
while TLS verifies the original hostname. Upstream mode has the different
DNS trust boundary and rejects IP ranges as described above. Redirects return
to the client and subsequent requests need their own authorization.

For example, [the credential example](../examples/proxy.json) permits only POST
to `https://api.openai.com/v1/responses` using a placeholder. Supply the real
`OPENAI_API_KEY` to the **host server's environment** using your normal secret
management, then start:

```sh
uv run external-sandbox-container --proxy-config examples/proxy.json
```

`guestEnv.OPENAI_API_KEY` is a literal placeholder, never a host environment
expansion. The credential rule requires a complete matching header value and
replaces it with `prefix + host_environment[secretEnv]` only after authorization.
Missing secrets or invalid configuration fail startup. Keys are never stored
in the example JSON. `*.local.json` and `.env*` are ignored by Git.

Credential substitution requires HTTPS interception. The host creates an
ephemeral CA, gives only the public certificate to the guest, terminates
guest TLS, checks the decrypted request and opens verified upstream TLS.
Nothing is installed in the host trust store. Guest commands receive standard
HTTP(S) proxy and CA environment variables. Clients using certificate pinning
or their own trust configuration may require adaptation.

## Boundary and scope

The helper and commands share the same untrusted container. The host owns
policy, upstream DNS, credentials, and authorization. Guest proxy settings and
its CA bundle are convenience settings, not the network boundary. Changing
them may break requests; it cannot create an external interface. The API and
Codex/Claude client protocols are unchanged.

The proxy supports HTTP/1.1 requests and streaming responses, including SSE.
It does not provide arbitrary TCP/UDP, SSH, WebSocket upgrades, or HTTP/2.
Each request uses a fresh connection. The host enforces request, response,
connection, and time limits, while acknowledged relay chunks bound queueing.
See [engine details](proxy-engine.md) and [transport details](proxy-transport.md).

Real keys remain outside the guest, but a placeholder can exercise the API
operations allowed by its rule. Scope origins, paths, and methods accordingly.
Literal secret echoes in upstream responses are redacted as defense in depth;
an allowed upstream that transforms a secret could still reveal it. Allowed
services must be trusted. The management log omits headers, bodies, and queries;
see [UI details](proxy-ui.md).

Host-side coding-agent tools remain outside this container. Keep server secrets
out of any directories exposed to those tools or mounted into the sandbox.
This is a local demonstration for trusted host users, not a multi-user service.

## Verification

```sh
uv run pytest -q -m 'not integration'
RUN_APPLE_CONTAINER_TESTS=1 uv run pytest -q tests/test_proxy_integration.py
```

Integration tests create a local HTTPS service with a synthetic credential and
test the real Apple Container, TLS trust, credential replacement, binary data,
streaming, blocked requests, policy changes, and direct-network failure. They
do not call paid APIs or use personal credentials.

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
uv run remote-sandbox-container --proxy-config examples/proxy-public.json
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
into your own file to keep it across restarts. The proxy denies all destinations
with an empty `allow` list; omitting `--proxy-config` disables the relay entirely.

The policy is validated before the container starts. The host proxy starts
first; the guest listener and CA bundle are ready before the execution API
opens. Shutdown stops API work, the guest/relay/container, and then the host
proxy. A broken proxy connection fails the request without falling back to
direct networking.

## Policy and credentials

Configuration uses the v86 proxy's `allow` and `guestEnv` JSON schema. An allow
rule contains an exact `origin` (scheme, host, port), optional `methods` and
exact `paths`, and optional `allowCidrs` for the resolved upstream IP. No rule
means no access. Without `allowCidrs`, only public addresses are permitted.
Private services require both an origin and an explicit IP range. The actual
connection uses an approved numeric address, while TLS verifies the original
hostname. Redirects return to the client and subsequent requests need their
own authorization.

For example, [the credential example](../examples/proxy.json) permits only POST
to `https://api.openai.com/v1/responses` using a placeholder. Supply the real
`OPENAI_API_KEY` to the **host server's environment** using your normal secret
management, then start:

```sh
uv run remote-sandbox-container --proxy-config examples/proxy.json
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

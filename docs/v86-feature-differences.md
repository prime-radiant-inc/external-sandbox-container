# Features added beyond the v86 prototype

Prepared 18 September 2026 as a handoff for another coding agent. All file links below contain absolute paths on this machine.

## Comparison baseline

The new Python project is at `/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server`. Its implementation through commit `ab2cc66` includes the browser terminal, proxy management UI, Apple Container backend, and expanded developer-tool image. This handoff also includes the subsequent Copy session button.

The reference v86 project is at `/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server`. Its current checkout is `e9c0462`; the Python project's provenance names `3b0002f1a511728b1f56638ea937a03447fbebbf`. The intervening change is documentation-only, so the runtime comparison applies to both.

The v86 version already had command execution over HTTP/WebSockets, a Codex exec-server adapter, streamed stdin/stdout/stderr, cancellation, a host-managed network proxy, destination allow-listing, HTTPS interception, and credential substitution. Those concepts are shared; this document distinguishes new user-facing features from replacement implementations.

Provenance: [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/PROVENANCE.md](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/PROVENANCE.md).

## 1. Browser terminal at `/` — new user-facing feature

The server homepage is an interactive command console implemented in plain browser JavaScript. It calls the existing `/exec/ws` protocol rather than introducing another command execution API. Users can select a working directory and timeout, run multiline shell commands, watch separate stdout/stderr streams, send stdin, close stdin with EOF, cancel commands, clear the transcript, and navigate command history. Example buttons populate useful commands, and a link opens the proxy controls.

The client preserves UTF-8 characters split across output chunks, bounds transcript/history/input memory, acknowledges stdin chunks, and avoids replaying commands after connection failures. It handles stale socket callbacks and browser back/forward cache restoration.

The **Copy session** button copies a plain-text snapshot of the retained transcript, including commands, sent input, stdout/stderr, and exit statuses. It supports copying while a command is running, reports success/failure, and uses a selected-text fallback in browsers without working Clipboard API access. It excludes unsent input and does not recover cleared or trimmed scrollback. The button is added by the JavaScript client, so an existing server can serve it after a browser refresh without restarting the container.

This is a pipe-based console, not a PTY. Each run starts a new Bash command; `cd` and environment changes do not persist between runs. Files persist for the container lifetime. Full-screen terminal programs are unsupported.

Implementation:

- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/terminal.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/terminal.py) — HTML, CSS, homepage and JavaScript asset routes, browser access checks.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/terminal.js](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/terminal.js) — WebSocket client, command/input controls, output decoding, history, bounded queues, lifecycle handling.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/api.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/api.py) — route installation and reuse of the existing streaming execution session.

Tests and usage:

- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_terminal_ui.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_terminal_ui.py)
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_terminal_js.mjs](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_terminal_js.mjs)
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/terminal.md](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/terminal.md)

The v86 HTTP implementation has no terminal homepage and rejects browser Origin requests: [/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/http.ts](/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/http.ts).

## 2. Authorized same-origin browser command sockets — new browser integration

The terminal receives a random token generated for the server lifetime. Browser WebSockets must present the exact same origin, including port, and the token through the offered subprotocols `sandbox-terminal` and `sandbox-token.<token>`. The server negotiates only `sandbox-terminal`, so the token is neither placed in a URL nor echoed as the selected protocol. Loopback Host validation, Fetch Metadata checks, CSP, and framing restrictions protect the local page from unrelated websites.

Existing command-line clients without browser Origin headers retain their API access. Other execution routes keep their browser restrictions. This is a browser cross-origin boundary for a trusted local service, not authentication between mutually untrusted host users.

Implementation and tests:

- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/terminal.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/terminal.py) — `check_terminal_access`, per-server token, response headers.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/api.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/api.py) — browser exception for `/exec/ws`, subprotocol negotiation.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_terminal_ui.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_terminal_ui.py) — invalid origins/tokens, ambiguous headers, cross-server token rejection, and legacy-client compatibility.

## 3. Live proxy policy editor and activity UI at `/proxy` — new user-facing feature

The management page displays the allow-list and a bounded activity log, and lets a user edit policy JSON without restarting the server. Its `/proxy/api` endpoint supports reading the current policy/activity and atomically replacing validated policy. Failed edits leave the previous policy intact. Policy replacement closes existing proxy connections so revoked access does not remain open.

Activity records include method, origin, path, status, allow/deny outcome, reason, duration, and whether a credential was injected. Headers, bodies, and query strings are omitted; configured secrets are redacted. The page uses safe text rendering and has its own same-origin/token protections.

Edits are runtime-only; saving a configuration file is separate. Changing `guestEnv` requires a restart. The UI references host secret environment variable names and guest placeholders rather than exposing real key values.

Implementation:

- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy_management.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy_management.py) — management HTML/JavaScript, `/proxy` and `/proxy/api`, token checks, bounded JSON input.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy.py) — `snapshot`, `update_policy`, connection revocation, sanitized request events.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy_policy.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy_policy.py) — validation, normalized configuration, redaction, host-owned policy enforcement.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/api.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/api.py) — management route installation.

Tests and docs:

- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_management.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_management.py)
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy.py)
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_integration.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_integration.py) — includes live policy revocation.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/proxy-ui.md](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/proxy-ui.md)

The v86 proxy already enforces a policy, but has no corresponding management page/API or user-facing activity ledger. Its existing implementation is [/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/network/managed-proxy.ts](/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/network/managed-proxy.ts) and [/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/network/proxy-policy.ts](/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/network/proxy-policy.ts).

## 4. Optional expanded developer-tool image — new packaging and guest capabilities

The optional `sandbox-demo:latest` OCI image retains Python and Bash and adds Node.js 24.21.0 with npm/npx, uv/uvx 0.12.15, ripgrep (`rg`), jq, curl, Git, procps (`ps`), GNU patch, unzip, and CA certificates. Node and uv are copied from versioned official runtime images; other tools come from Debian packages. The running demo uses this image. The application's default remains `python:3.13-slim` unless `--image` is supplied.

The v86 guest already includes Python, Bash, Git, CA certificates, and BusyBox. Some command names such as `ps`, `patch`, or `unzip` may already be available as BusyBox applets there. The difference is the expanded OCI tool image, including Node/npm, uv, ripgrep, jq, dedicated curl, and full Debian utility implementations; it is not a claim that every command is absent from v86.

Implementation and usage:

- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/examples/Containerfile](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/examples/Containerfile) — complete image recipe.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/cli.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/cli.py) — `--image` selection.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/demo.md](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/demo.md) — build/start instructions and tool examples.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_integration.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_integration.py) — opt-in tool-image checks and real Node/uv proxy integration.

## 5. Node's built-in networking automatically uses the proxy — new runtime setting

When the managed proxy is enabled, guest commands now receive `NODE_USE_ENV_PROXY=1`. This allows Node 24's built-in `fetch` and default HTTP(S) clients to use the proxy variables. The existing public CA bundle is passed through `NODE_EXTRA_CA_CERTS`. uv uses that same bundle through `SSL_CERT_FILE`.

The CA/proxy variables themselves already existed in the v86 design; `NODE_USE_ENV_PROXY` and its tested Node runtime integration are the additions. Tests verify both `fetch` and `node:https`, host-only credential injection, response redaction, denied destinations, and uv installation of a synthetic wheel over verified HTTPS. Programs that replace their HTTP agent or certificate settings may still need explicit configuration.

Implementation and tests:

- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/guest_proxy.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/guest_proxy.py) — guest proxy and command environment.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_relay.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_relay.py) — environment setup checks.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_integration.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_integration.py) — Node and uv end-to-end checks.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/proxy-transport.md](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/proxy-transport.md) — environment contract and upstream references.

## 6. Apple Container execution and command-pipe networking — replacement implementation

This is a separate Python application managed with uv, named generically so another backend can be added later. It runs a native Linux aarch64 OCI container managed by Apple's `container` CLI, instead of a v86 x86 virtual machine in Node.js/WebAssembly. Docker support is not implemented.

The container starts with the server and is removed on normal server shutdown. The backend supports selected OCI images, CPU/memory settings, and explicitly configured read-only/read-write host mounts. Default port 8687 lets this app run alongside v86 on 8686. The execution contracts remain compatible with the original clients.

The isolation details differ: the default Apple guest runs as UID 0 with capabilities dropped, while v86 uses UID/GID 1000. Apple mounts rely on the runtime's read-only mount protection and do not reproduce v86's conservative per-inode hardlink restrictions. Treat this as an alternative backend with documented differences, not an identical security implementation.

The workload starts with `--network none --cap-drop ALL`. A guest loopback proxy forwards bytes through the existing framed stdin/stdout control pipe. The host Python process performs HTTP/TLS proxying and policy enforcement. The relay has a fixed host destination, bounded chunks/windows/queues, acknowledgments, and concurrent streams; it does not expose arbitrary host TCP destinations. There is no external guest NIC or separate proxy container.

The v86 version achieves its networking boundary through its emulated network stack, network guard, and Wisp relay. Reusing the execution pipe for proxy transport is the new backend-specific mechanism; allow-listing and credential substitution are shared goals.

Implementation:

- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/pyproject.toml](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/pyproject.toml) and [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/uv.lock](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/uv.lock) — package/entry point/dependencies.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/cli.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/cli.py) — arguments and server/proxy/container lifecycle.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/backend.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/backend.py) — Apple Container command construction, mounts, process/filesystem RPC, lifecycle.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/guest_agent.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/guest_agent.py) — guest command agent and framed RPC.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/guest_fs.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/guest_fs.py) — guest filesystem operations for the compatible adapter.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/guest_proxy.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/guest_proxy.py) — guest listener and CA/environment setup.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy_relay.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy_relay.py) — bounded multiplexed relay transport.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy.py) — host HTTP/HTTPS engine.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy_policy.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy_policy.py) — allow-list, resolved-address checks, credential rules.
- [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy_certificates.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/proxy_certificates.py) — ephemeral proxy CA and host certificates.

Relevant v86 source:

- [/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/vm.ts](/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/vm.ts)
- [/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/network/v86-network-guard.ts](/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/network/v86-network-guard.ts)
- [/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/network/wisp-relay.ts](/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/network/wisp-relay.ts)
- [/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/network/managed-proxy.ts](/Users/simon/Documents/Codex/2026-09-17/find/outputs/v86-shell-server/src/network/managed-proxy.ts)

Tests: [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_apple_integration.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_apple_integration.py), [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_real_clients.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_real_clients.py), [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_relay.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_relay.py), and [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_integration.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/tests/test_proxy_integration.py).

## Compatibility, limits, and suggested porting order

Do not present the HTTP/WebSocket API, Codex adapter, filesystem RPC, allow-list, or API-key substitution as entirely new features. The original Python command client remains unchanged: [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/clients/v86_exec.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/clients/v86_exec.py). The Python adapters are [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/api.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/api.py) and [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/codex.py](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/src/sandbox_exec_server/codex.py). Protocol details: [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/protocol.md](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/protocol.md).

The browser terminal and management UI are the most directly portable additions to v86. Start with the terminal client and page, add the narrowly scoped browser authorization exception, then add the management snapshot/update/event interface around v86's existing proxy. Keep runtime/image and command-pipe transport differences separate.

Package installation still depends on explicitly allowing package registries. Installing npm or uv does not automatically grant registry access. Full-screen terminals, arbitrary TCP/UDP, SSH transport, WebSocket proxy upgrades, and HTTP/2 are not added by this work. Existing Codex local-only `!command` limitations are not solved by the new UI or backend.

## Verification and handoff state

The expanded image passed 254 Python tests in two runs, including real Apple Container and Node/uv proxy tests. The terminal client has 21 passing JavaScript tests, including six clipboard checks. The two real Codex CLI/App Server tests passed in the earlier baseline and were not rerun with the expanded image. Lint, package builds, and earlier live browser/WebSocket smoke checks also passed; the clipboard change was checked automatically because the Mac was locked. Detailed commands and qualifications: [/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/verification.md](/Users/simon/Documents/Codex/2026-09-18/briefly-look-at-v86-wasm-for/outputs/sandbox-exec-server/docs/verification.md).

The running demo is available at `http://127.0.0.1:8687/`, with proxy management at `http://127.0.0.1:8687/proxy`. Browser pages need refreshing after a server restart to obtain new tokens.

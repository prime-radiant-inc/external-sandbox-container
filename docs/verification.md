# Verification — 18 September 2026

Before the terminal homepage was added, the combined proxy suite passed:
**220 tests, zero failures, zero skips**
(`220 passed in 7.92s`). The Codex tests ran against a proxy-enabled server.

| Layer | Tests | Evidence |
| --- | ---: | --- |
| HTTP/WebSocket protocol, original client, Codex schemas, filesystem and backend unit tests | 76 | Validation, ordering, bounds, environment policies, replay, EOF, cancellation, shutdown |
| Real Apple Container backend | 7 | Binary streaming, exact argv, environment replacement, live RO/RW mounts, no eth0, signals, timeouts, output limits, filesystem RPC, concurrent processes, descendant cleanup |
| Original Python client + real container API | 4 | 256 KiB all-byte-values round trip, separate binary stderr, exit 23, mount cwd translation, timeout, abrupt/graceful disconnect cleanup |
| Real Codex CLI / App Server | 2 | Remote execution, native apply_patch success and read-only denial; local-only shell shortcut rejected |
| Host proxy policy and HTTP/TLS engine | 63 | Exact rules, checked/pinned DNS, strict TLS trust and hostname validation, credential substitution, redaction, SSE, malformed requests, bounds, policy revocation |
| Guest proxy transport | 24 | Fixed destination, bounded ACK windows, hostile frames, concurrent binary streams, public CA setup, HTTPS through both relays |
| Management UI/API | 34 | Origin and token checks, safe rendering, bounded input, atomic policy edits, unchanged execution API browser restrictions |
| Proxy CLI lifecycle | 5 | Explicit opt-in, early configuration failure, startup failure cleanup, cancellation |
| Real Apple Container proxy route | 5 | Verified HTTPS, 256 KiB binary upload, host-only credentials, response redaction, denied destinations/paths, no direct network, SSE plus command RPC, live policy changes |

A separate public-network smoke test ran an ordinary guest Python `urllib`
request to the explicitly allowed `https://example.com` origin and received
HTTP 200 with external container networking still disabled. Browser verification
opened the actual management page, applied an empty allow-list, executed a
blocked guest request, and confirmed its 403 entry appeared in the activity log.
Proxy credential tests used synthetic credentials and local HTTPS fixtures.

The Codex CLI test uses deterministic responses from a temporary localhost model
fixture. The CLI, transport, filesystem operations and container are real; no
paid inference or live Claude conversation is claimed. The App Server test
checks the precise `local environment is not configured` error for
`thread/shellCommand`, with no command execution events and no inference call.
Both use isolated temporary Codex configurations.

## Terminal homepage

After adding the browser terminal, **250 Python tests passed** (`250 passed in
6.70s`), including the real Apple Container and original client integration
tests. This run included 32 new terminal tests and excluded the two Codex CLI
tests, which require a separately configured server with host mounts and had
passed in the proxy baseline above. The existing no-mount demo server was left
available for interactive use.

The terminal tests cover streamed stdout/stderr, stdin acknowledgments, EOF,
cancellation, disconnect cleanup, browser origin and token checks, ambiguous
headers, cross-server token rejection, safe HTML rendering, and compatibility
with existing command-line clients. **15 JavaScript tests passed** under Node
26.3.0, covering split UTF-8 output, bounded scrollback and history, stdin flow
control, cancellation races, browser timer callbacks, and page-cache restoration.
The actual browser homepage was also checked visually and used to run commands
through the WebSocket API.

Reproduce the terminal verification without a separately configured Codex server:

```sh
RUN_APPLE_CONTAINER_TESTS=1 uv run pytest -q --ignore=tests/test_codex_cli.py
node --test tests/test_terminal_js.mjs
```

The subsequent **Copy session** addition passed all **21 JavaScript tests**.
Its six new checks cover plain-text serialization, retained/cleared scrollback,
copying during an active command without including drafts or tokens, clipboard
fallback and failure, and focus/selection restoration. The live server was
verified to serve the new JavaScript without a container restart. A fresh
browser click check was unavailable because the host Mac was locked.

## Versions

- Host: Apple silicon, macOS 26.4; Python 3.14.3; uv 0.12.9.
- Apple Container CLI/server: 1.4.1, commit `9a8917ca2da5cd6ba059b9ba5ca5a74892e9bb7d`.
- Codex CLI: 0.154.0.
- Default guest: Linux aarch64, `python:3.13-slim`, Python 3.13.15.
- Image index digest: `sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285`.
- arm64 image manifest: `sha256:c89921a0c7b42f27338ed8c279fb370e69e941c92460f91895d08304e844b0b4`.

To repeat with exactly that image, pass
`--image python@sha256:9d2e5553305c7c7b0097999bb17187c69b921ccd6bc9d40e4bb5ebe652c00285`.
The default tag may advance in the registry.

## Initial tool image

Built `sandbox-demo:latest` from `examples/Containerfile`, adding curl, Git,
procps (`ps`), and CA certificates to the Python base. The resulting image
index digest was
`sha256:25a276ba2d475db6e56ef4f85a31278bc75685302603fc992381c2007540fb91`.
All **16 existing container, original-client, and proxy integration tests**
passed against this image (`16 passed in 5.80s`):

```sh
container build --tag sandbox-demo:latest --file examples/Containerfile .
RUN_APPLE_CONTAINER_TESTS=1 SANDBOX_TEST_IMAGE=sandbox-demo:latest \
uv run pytest -q tests/test_apple_integration.py tests/test_real_clients.py \
  tests/test_proxy_integration.py
```

The running demo was then restarted with `--image sandbox-demo:latest`,
preserving its live proxy policy. A smoke check used the browser terminal's
same-origin, token-protected WebSocket route and confirmed curl 8.14.1,
Git 2.47.3, and procps-ng 4.0.4. `ps -ef` listed the guest processes.
`curl -fsS https://example.com` received HTTP 200 using the configured proxy
and CA; a request to the unlisted `https://example.org` received HTTP 403.
A curl request with the proxy bypassed and a supplied destination IP failed
to connect, and `/sys/class/net` still contained only `lo`.

## Expanded tool image

Rebuilt `sandbox-demo:latest` with Node 24.21.0 (npm/npx 11.19.0), uv/uvx
0.12.15, ripgrep 14.1.1, jq, GNU patch 2.8, and unzip, retaining the previous
tools. The new image index digest is
`sha256:3e05fc6fbcf94d63ed9aa245e2f062e463cda2aa1acfe0e3f1831cfecaa7871e`.
Node and uv are copied from versioned official images; Debian supplies the
other tools. The proxy now sets `NODE_USE_ENV_PROXY=1` alongside its existing
public CA environment variables.

**254 Python tests passed in two runs**: 245 server/container/client tests
(`245 passed in 5.12s`) and nine proxy integration tests (`9 passed in 1.87s`).
The two separately configured Codex CLI tests were not repeated. Four new
opt-in tool-image tests check runnable tools, Node's `fetch` and `node:https`
with verified proxy TLS, allowed and denied requests, host-only credentials,
response redaction, and uv installation/import of a tiny synthetic wheel
served by the local HTTPS fixture. These tests require the expanded image;
they are skipped with the minimal default image.

```sh
RUN_APPLE_CONTAINER_TESTS=1 RUN_SANDBOX_TOOL_IMAGE_TESTS=1 \
SANDBOX_TEST_IMAGE=sandbox-demo:latest \
uv run pytest -q --ignore=tests/test_codex_cli.py
```

After restarting the demo with its unchanged live proxy policy, a smoke check
through the terminal's authenticated WebSocket API verified all new tool
versions, ran Python with `uv run --offline --no-project`, and received HTTP
200 from `https://example.com` using Node's built-in `fetch`. No package-registry
origins were added to the live allow-list. Lint, whitespace checks, and package
build also passed.

## Reproduce

Run the local protocol tests:

```sh
uv run pytest -q -m 'not integration'
```

Start no separate server for the self-contained container/client tests; each
fixture creates and removes its own container and temporary mounts:

```sh
RUN_APPLE_CONTAINER_TESTS=1 uv run pytest -q \
  tests/test_apple_integration.py tests/test_real_clients.py
```

For the full Python suite, start a server with `project` (rw) and
`reference` (ro) mounts using [the demo instructions](demo.md). Add
`--proxy-config examples/proxy-public.json` to reproduce the proxy-enabled
Codex run, then run:

```sh
RUN_APPLE_CONTAINER_TESTS=1 \
SANDBOX_EXEC_SERVER_URL=ws://127.0.0.1:8687/codex \
SANDBOX_TEST_RW=/absolute/path/to/project \
SANDBOX_TEST_RO=/absolute/path/to/reference \
uv run pytest -q
```

`SANDBOX_TEST_IMAGE` optionally selects the image for self-contained tests.
Tests create unique fixture directories beneath the two shared mount roots and
remove them afterward.

The self-contained proxy integration suite can also run on its own:

```sh
RUN_APPLE_CONTAINER_TESTS=1 uv run pytest -q tests/test_proxy_integration.py
```

## Packaging and cleanup

`uv run ruff check .`, `git diff --check`, and `uv build` passed. The rebuilt
proxy-enabled wheel was installed in a separate uv environment, with no import
from the source checkout. That installed app booted an Apple Container, served
the health and management UI endpoints, and completed a verified guest HTTPS
request through the proxy with HTTP 200. The earlier base-server wheel check
also covered HTTP command execution and binary Codex filesystem operations.
Normal shutdown removed the containers. Source distributions include the
clients, docs, examples, tests and lockfile.

The terminal update also passed lint, whitespace checks, and `uv build`.
Archive inspection confirmed that the wheel contains both `terminal.py` and
`terminal.js`, and that the source distribution includes the terminal docs and
both Python and JavaScript tests.

No global agent configuration was changed. Test-owned containers were removed;
the pre-existing v86 server and unrelated Apple containers were left alone.
See [the protocol differences](protocol.md#deliberate-differences) for
networking, mount, and runtime scope.

## Shared Claude client relocation — 9 October 2026

After moving the Claude shell-prefix implementation and its configuration tests to `remote-sandbox/claude-code`, the ordinary backend suite passed 241 tests, skipped five optional external-client checks, and deselected 22 integration tests. Supplying the central streaming client through `REMOTE_SANDBOX_CLIENT` passed all nine targeted API/client and real Apple Container compatibility checks. The three direct WebSocket lifecycle tests remain independent of the external client.

```sh
uv run pytest -q -m 'not integration'
RUN_APPLE_CONTAINER_TESTS=1 \
REMOTE_SANDBOX_CLIENT=/absolute/path/to/remote-sandbox/claude-code/remote_sandbox_exec.py \
  uv run pytest -q tests/test_legacy_client.py tests/test_real_clients.py
```

Ruff, whitespace checks, and `uv build` passed. The rebuilt wheel was installed in an isolated uv environment, where CLI help described only the image recipe and proxy policy and `--write-setup` exported exactly `Containerfile` and `proxy.json`. Archive inspection confirmed that neither the wheel nor the source distribution contains shell-prefix wrapper/client copies or the relocated settings tests. Earlier counts and bundled-client references above describe their historical revisions.

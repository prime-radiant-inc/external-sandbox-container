# Verification — 18 September 2026

The final combined suite passed: **89 tests, zero failures, zero skips**
(`89 passed in 5.89s`).

| Layer | Tests | Evidence |
| --- | ---: | --- |
| HTTP/WebSocket protocol, original client, Codex schemas, filesystem and backend unit tests | 76 | Validation, ordering, bounds, environment policies, replay, EOF, cancellation, shutdown |
| Real Apple Container backend | 7 | Binary streaming, exact argv, environment replacement, live RO/RW mounts, no eth0, signals, timeouts, output limits, filesystem RPC, concurrent processes, descendant cleanup |
| Original Python client + real container API | 4 | 256 KiB all-byte-values round trip, separate binary stderr, exit 23, mount cwd translation, timeout, abrupt/graceful disconnect cleanup |
| Real Codex CLI / App Server | 2 | Remote execution, native apply_patch success and read-only denial; local-only shell shortcut rejected |

The Codex CLI test uses deterministic responses from a temporary localhost model
fixture. The CLI, transport, filesystem operations and container are real; no
paid inference or live Claude conversation is claimed. The App Server test
checks the precise `local environment is not configured` error for
`thread/shellCommand`, with no command execution events and no inference call.
Both use isolated temporary Codex configurations.

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

For the full 89-test suite, start a server with preserved `project` (rw) and
`reference` (ro) mounts using [the demo instructions](demo.md), then run:

```sh
RUN_APPLE_CONTAINER_TESTS=1 \
SANDBOX_EXEC_SERVER_URL=ws://127.0.0.1:8686/codex \
SANDBOX_TEST_RW=/absolute/path/to/project \
SANDBOX_TEST_RO=/absolute/path/to/reference \
uv run pytest -q
```

`SANDBOX_TEST_IMAGE` optionally selects the image for self-contained tests.
Tests create unique fixture directories beneath the two shared mount roots and
remove them afterward.

## Packaging and cleanup

`uv run ruff check .` and `uv build` passed. A built wheel was installed in a
separate temporary uv environment, with no import from the source checkout.
That installed app successfully booted an Apple Container and served both
HTTP command execution and binary Codex filesystem operations. SIGTERM shut it
down normally. Source distributions include the clients, docs, examples, tests
and lockfile.

No global agent configuration was changed. Test-owned containers were removed;
the pre-existing v86 server and unrelated Apple containers were left alone.
The optional Git/curl image recipe is supplied but was not built during these
checks. See [the protocol differences](protocol.md#deliberate-differences) for
networking, mount, and runtime scope.

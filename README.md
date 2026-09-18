# sandbox-exec-server

A Python execution server for coding agents, managed with `uv`. It implements
the HTTP and WebSocket interfaces of the separate `v86-shell-server` prototype,
but executes commands in a Linux container managed by Apple's `container` CLI.
The application name leaves room for future backends, including Docker; this
version implements Apple Container only.

The experiment: keep the coding-agent integration and client protocol constant,
and change the execution sandbox. Claude Code uses the existing shell-prefix
client at `/exec/ws`. Codex uses its exec-server protocol at `/codex`, including
filesystem operations and native `apply_patch`.

## Start

Requirements: an Apple silicon Mac with Apple's
[`container`](https://github.com/apple/container) installed and running, and
[`uv`](https://docs.astral.sh/uv/). The container image must provide `python3` and
`bash`; the default is `python:3.13-slim`.

```sh
container system start
container image pull python:3.13-slim
uv sync
uv run sandbox-exec-server --port 8687 --preserve-paths \
  --mount-rw project=/absolute/path/to/project \
  --mount-ro reference=/absolute/path/to/reference
```

The server defaults to `127.0.0.1:8687`, so it can run alongside the v86 server
on port `8686`. It creates its own container with two CPUs,
512 MiB of memory, and `--network none`. Stop the server with Ctrl-C to remove
that container. Files in writable mounts persist on the host; other container
changes are disposable. Host changes to mounted files remain visible.

The mounts appear at `/mnt/project` and `/mnt/reference` in Linux.
`--preserve-paths` also makes their original host paths available inside the
container, for clients that send absolute paths. The first mount is the default
working directory; without mounts, it is `/workspace`.

Run `uv run sandbox-exec-server --help` for image, resource, and container CLI
options. `--container-bin` selects a particular Apple `container` executable.

## Try the existing API

```sh
curl -sS http://127.0.0.1:8687/health
curl -sS http://127.0.0.1:8687/exec \
  -H 'Content-Type: application/json' \
  --data '{"command":"uname -s; printf hello; printf problem >&2; exit 7"}'
```

`POST /exec` returns `stdout`, `stderr`, `exitCode`, `signal`, `timedOut`,
`outputLimitExceeded`, and `durationMs`. A nonzero program exit is a successful
HTTP request with a nonzero `exitCode`. `GET /mounts` returns mount mappings for
the existing client's working-directory translation.

The original Python streaming client is retained as
`clients/v86_exec.py`. Its historical filename and `V86_*` environment
variables are intentional compatibility details; it works with this backend.

```sh
V86_API_URL=http://127.0.0.1:8687 V86_CWD=/mnt/project uv run --quiet --script clients/v86_exec.py \
  --no-stdin 'uname -s; pwd'
```

See [agent setup](docs/agents.md), [protocol compatibility](docs/protocol.md),
and [a repeatable team demo](docs/demo.md).

## Scope

- Submitted commands and Codex filesystem operations run inside the container.
  The host launches the `container` CLI with argument arrays; it does not
  evaluate submitted command text in a host shell.
- The default image runs as UID 0 inside the guest, with all Linux capabilities
  dropped. The environment's `USER=agent` label does not change the kernel UID.
- Mounts deliberately expose selected host directories. Read-write mounts allow
  immediate host changes; read-only mounts use the runtime's read-only setting.
  Do not expose a writable hardlink alias of a file in a read-only mount. This
  backend does not reproduce v86's per-inode hardlink restrictions.
- Container networking is disabled. Image acquisition occurs on the host.
  The v86 prototype's managed proxy, credential substitution, and network
  allowlists are **not implemented** here.
- Codex and Claude themselves, model traffic, and host extensions remain on the
  host. Claude's native Read/Edit tools are not redirected by a shell prefix.
- Codex is configured with `include_local = false`. Its local-only `!command`
  shortcut must fail. Do not add a local executor to make it work.
- The listener is for trusted local clients, without authentication. It rejects
  browser Origin requests; other processes on the machine can access it.

This demonstrates interchangeable execution routes, not a claim that every
operation performed by an agent is contained. Isolation and filesystem details
differ between Apple's container runtime and the v86 prototype.

For an image with Git and curl in addition to Python and Bash, see
[the example Containerfile](examples/Containerfile) and
[image build instructions](docs/demo.md#optional-tool-image). The default image
remains deliberately small.

## Test

The recorded run passed **89 tests**, including real Apple Containers, the
unchanged Python client, and Codex CLI 0.154.0. See [verification](docs/verification.md)
for the tested image digest, package checks, and reproducible commands.

```sh
uv run pytest -m 'not integration'
```

Tests marked `integration` use the real container runtime or installed agent
CLI. See [verification instructions](docs/demo.md#verification). The Codex CLI
fixture uses deterministic loopback model responses and an isolated temporary
configuration; it does not call a paid model or change user configuration.

The Codex adapter targets the experimental protocol exercised with
`codex-cli 0.154.0`. Other versions require compatibility testing.

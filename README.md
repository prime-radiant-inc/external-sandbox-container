# external-sandbox-container

A Python execution server for coding agents, managed with `uv`. It implements the shared [external sandbox protocol](https://github.com/prime-radiant-inc/external-sandbox/blob/main/PROTOCOL.md), alongside [external-sandbox-v86](https://github.com/prime-radiant-inc/external-sandbox-v86) and [external-sandbox-quicksand](https://github.com/prime-radiant-inc/external-sandbox-quicksand), and executes commands in a Linux container managed by Apple's `container` CLI. This version implements Apple Container only.

The experiment: keep the coding-agent integration and client protocol constant,
and change the execution sandbox. Claude Code uses the existing shell-prefix
client at `/exec/ws`. Codex uses its exec-server protocol at `/codex`, including
filesystem operations and native `apply_patch`.

Pi uses the shared [Pi extension](https://github.com/prime-radiant-inc/external-sandbox/tree/main/pi), which routes its shell, file, and search tools plus `!`/`!!` commands through `/exec/ws`. Set `--sandbox-url http://127.0.0.1:8687` for this backend.

## Renamed project

This project was previously `sandbox-exec-server` with Python module `sandbox_exec_server`. The distribution, command, and module are now `external-sandbox-container`, `external-sandbox-container`, and `external_sandbox_container`. Run `uv sync --locked --reinstall` after moving or updating an existing checkout, update command/import paths, and obtain Claude shell-prefix helpers from the shared `external-sandbox` repository. Ports and wire protocol identifiers are unchanged. Historical provenance and verification records retain the names used when those results were recorded.

## Start

Requirements: an Apple silicon Mac with Apple's
[`container`](https://github.com/apple/container) installed and running, and
[`uv`](https://docs.astral.sh/uv/). The container image must provide `python3` and
`bash`; the default is `python:3.13-slim`.

```sh
container system start
container image pull python:3.13-slim
uv sync
uv run external-sandbox-container --port 8687 --preserve-paths \
  --mount-rw project=/absolute/path/to/project \
  --mount-ro reference=/absolute/path/to/reference
```

The server defaults to `127.0.0.1:8687`, so it can run alongside the v86 server
on port `8686` and the Quicksand server on port `8688`. It creates its own
container with two CPUs,
512 MiB of memory, and `--network none`. Stop the server with Ctrl-C to remove
that container. Files in writable mounts persist on the host; other container
changes are disposable. Host changes to mounted files remain visible.

The mounts appear at `/mnt/project` and `/mnt/reference` in Linux.
`--preserve-paths` also makes their original host paths available inside the
container, for clients that send absolute paths. The first mount is the default
working directory; without mounts, it is `/workspace`.

Run `uv run external-sandbox-container --help` for image, resource, and container CLI
options. `--container-bin` selects a particular Apple `container` executable.

## Export setup files

Use `--write-setup DIR` to copy the bundled setup files into a directory, including when running from an installed package without a source checkout:

```sh
uv run external-sandbox-container --write-setup ./sandbox-config
```

The command creates the directory if needed, writes the files below, and exits without starting a server or building a container image. Apple Container does not need to be running for this step.

| File | Purpose |
| --- | --- |
| `Containerfile` | Image recipe with Python, Bash, Node.js/npm, uv/uvx, Git, curl, ripgrep, jq, and other development tools. |
| `proxy.json` | Starter policy allowing only GET/HEAD requests to `https://example.com`; edit it for your required destinations. |

Rerunning the command accepts files whose contents are unchanged. It refuses to overwrite edited files, directories in place of files, or symlinks at the destination or output filenames; use a new destination if you have customized the setup. Conflicts are checked before any files are written.

See [image build instructions](docs/demo.md#optional-tool-image) for the exported image recipe and [agent setup](docs/agents.md) for connecting coding agents. Claude shell-prefix helpers live in the shared [external-sandbox integration](https://github.com/prime-radiant-inc/external-sandbox/tree/main/claude-code); `--write-setup` exports only the image recipe and proxy policy.

## Browser terminal

Open `http://127.0.0.1:8687/` to run commands through the existing WebSocket API.
Output appears as it arrives. While a command runs, the input box sends lines
to its stdin; **Send EOF** closes stdin and **Cancel** stops the command.
The page also provides command history, a working-directory field, a time
limit, and examples for streaming output, interactive input, and HTTPS access.

Each run starts a new shell in the same container. Files persist between runs;
use the working-directory field instead of expecting a previous `cd` to carry
over. This uses pipes, not a PTY. For a Python REPL, run `python3 -u -i`.
See [terminal controls and behavior](docs/terminal.md).

The HTML, CSS, JavaScript, and frontend tests are a pinned bundle from the independent `external-sandbox-ui` project. Normal installs include all runtime assets. See [shared UI development](docs/ui.md) for the update command, integrity checks, and packaging details.

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

The [shared Claude Code integration](https://github.com/prime-radiant-inc/external-sandbox/tree/main/claude-code) and [Codex setup instructions](https://github.com/prime-radiant-inc/external-sandbox/tree/main/codex) are maintained in `external-sandbox`. Use `EXTERNAL_SANDBOX_API_URL=http://127.0.0.1:8687` for Claude Code and `ws://127.0.0.1:8687/codex` for Codex, with the mounted project paths described in [agent setup](docs/agents.md).

See [agent setup](docs/agents.md), [protocol and deliberate differences](docs/protocol.md),
and [a repeatable team demo](docs/demo.md).

## Controlled network access

The container remains offline unless you opt into a host-enforced HTTP(S) proxy:

```sh
uv run external-sandbox-container --proxy-config examples/proxy-public.json
```

This example permits GET/HEAD requests to `https://example.com` only. Open
`http://127.0.0.1:8687/proxy` to edit the policy and inspect recent requests.
Changes in the UI apply to the running server; save your JSON separately to
reuse it after restarting. See [proxy setup and security](docs/proxy.md).

Commands receive ordinary proxy environment variables and a public CA
certificate. A small guest listener relays traffic over the existing command
pipe to the proxy in the host Python process. The container still uses
`--network none`; removing proxy settings cannot enable direct network access.

[examples/proxy.json](examples/proxy.json) also demonstrates substituting a placeholder with an API key from the host environment. It requires `OPENAI_API_KEY` on the host before startup. Real keys are not provisioned to the container or displayed by the management UI. An allowed upstream can transform and echo a credential despite literal response redaction; use credential rules only with trusted services and narrow their methods and paths. See [proxy scope](docs/proxy.md#boundary-and-scope).

## Scope

- Submitted commands and Codex filesystem operations run inside the container.
  The host launches the `container` CLI with argument arrays; it does not
  evaluate submitted command text in a host shell.
- The default image runs as UID 0 inside the guest, with all Linux capabilities
  dropped. The environment's `USER=agent` label does not change the kernel UID.
- Mounts deliberately expose selected host directories. Read-write mounts allow immediate host changes; read-only mounts use the runtime's read-only setting. A pre-existing host hardlink in a writable mount remains editable even if another name for the same file is in a read-only mount; avoid that alias if the file must stay unchanged. This backend does not reproduce v86's per-inode hardlink restrictions.
- Container networking is disabled. Optional HTTP(S) egress travels over the
  command pipe to the host proxy, which enforces the allow-list and substitutes
  credentials. Image acquisition occurs on the host.
- Codex and Claude themselves, model traffic, and host extensions remain on the
  host. Claude's native Read/Edit tools are not redirected by a shell prefix.
- Codex is configured with `include_local = false`. Its local-only `!command`
  shortcut must fail. Do not add a local executor to make it work.
- The execution listener is for trusted local clients. The browser terminal
  requires a same-origin WebSocket and a per-run token; other execution routes
  reject browser Origin requests. The proxy management UI has its own token.
  Trusted local command-line clients retain their existing API access.

This demonstrates interchangeable execution routes, not a claim that every
operation performed by an agent is contained. Isolation and filesystem details
differ between Apple's container runtime and the v86 prototype.

For an image with Node.js 24 LTS/npm, uv/uvx, ripgrep (`rg`), jq, patch, unzip,
curl, Git, procps (`ps`), and CA certificates in addition to Python and Bash, see
[the example Containerfile](examples/Containerfile) and
[image build instructions](docs/demo.md#optional-tool-image). The default image
remains deliberately small.

## Test

The proxy baseline passed **220 tests**, including real Apple Containers, the
unchanged Python client, and Codex CLI 0.154.0. The terminal update passed **250
Python tests and 15 JavaScript tests**; the two separately configured Codex tests
were not repeated in that run. The expanded tool image subsequently passed
**254 Python tests**, including Node and uv requests through the managed proxy.
See [verification](docs/verification.md) for the tested image digests, package
checks, and reproducible commands.

```sh
uv run pytest -m 'not integration'
node --test tests/test_terminal_js.mjs
```

Client compatibility checks are optional because the client is maintained separately. Set `EXTERNAL_SANDBOX_CLIENT` to its absolute path to enable those checks:

```sh
EXTERNAL_SANDBOX_CLIENT=/absolute/path/to/external-sandbox/claude-code/external_sandbox_exec.py \
  uv run pytest -q tests/test_legacy_client.py

RUN_APPLE_CONTAINER_TESTS=1 \
EXTERNAL_SANDBOX_CLIENT=/absolute/path/to/external-sandbox/claude-code/external_sandbox_exec.py \
  uv run pytest -q tests/test_real_clients.py
```

Tests marked `integration` use the real container runtime or installed agent CLI. See [verification instructions](docs/demo.md#verification). The Codex CLI fixture uses deterministic loopback model responses and an isolated temporary configuration; it does not call a paid model or change user configuration.

The Codex adapter targets the experimental protocol exercised with
`codex-cli 0.164.0`. Other versions require compatibility testing.

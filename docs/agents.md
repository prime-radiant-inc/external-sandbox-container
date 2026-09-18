# Agent setup

Start the server with the writable project first and `--preserve-paths`:

```sh
uv run sandbox-exec-server --preserve-paths \
  --mount-rw project=/absolute/path/to/project \
  --mount-ro reference=/absolute/path/to/reference
```

These recipes change the execution route. The coding-agent process and its
model connection continue running on the Mac. The container has no external
network connection, so install required tools into the image before the demo.

## Claude Code

The included wrapper and Python client use the existing `/exec/ws` protocol.
The `V86_*` variable names remain unchanged to preserve client compatibility.
Run the client once to prepare its `uv` dependency before starting Claude:

```sh
APP=/absolute/path/to/sandbox-exec-server
V86_CWD=/mnt/project uv run --quiet --script "$APP/clients/v86_exec.py" \
  --no-stdin 'uname -s; pwd'
```

From the mounted project directory:

```sh
mkdir -p .sandbox-claude-tmp
CLAUDE_CODE_SHELL=/bin/bash \
CLAUDE_CODE_TMPDIR="$PWD/.sandbox-claude-tmp" \
CLAUDE_CODE_SHELL_PREFIX="$APP/clients/claude-shell-prefix.sh" \
V86_API_URL=http://127.0.0.1:8686 \
claude
```

The temporary directory must be within the mount because Claude's command
wrapper writes a cwd bookkeeping file there. Add `.sandbox-claude-tmp/` to the
project's ignore file if desired. The default image includes Python and Bash;
it is not intended to contain every language toolchain.

The shell prefix redirects shell commands, including wrapper bookkeeping,
through the container. Claude's native Read/Edit tools still access the host.
A read-only mount constrains container operations; it does not impose a new
permission policy on Claude's host file tools. No live Claude model call is
needed to test the wrapper:

```sh
"$APP/clients/claude-shell-prefix.sh" 'uname -s; pwd; printf "container stdout\n"'
"$APP/clients/claude-shell-prefix.sh" 'printf "container stderr\n" >&2; exit 7'
```

The shell-prefix integration originates from the v86 prototype and Anthropic's
[`CLAUDE_CODE_SHELL_PREFIX` setting](https://code.claude.com/docs/en/env-vars).

## Codex CLI

The compatibility target is **Codex CLI 0.154.0**. Its experimental exec-server
connection sends process and filesystem requests to
`ws://127.0.0.1:8686/codex`. It does not need the shell-prefix client.

Merge the following into the Codex environment configuration for the profile
you intend to use. The file is normally `~/.codex/environments.toml`; keep a
separate profile for this experiment if you already have environment settings.
These are setup instructions, not changes performed by the server.

```toml
default = "sandbox"
include_local = false

[[environments]]
id = "sandbox"
url = "ws://127.0.0.1:8686/codex"
connect_timeout_sec = 5
initialize_timeout_sec = 10
```

Launch Codex from the mounted project:

```sh
codex --sandbox danger-full-access \
  -c features.shell_snapshot=false \
  -c features.unified_exec_tty=false \
  --cd /absolute/path/to/project
```

Here `danger-full-access` allows execution within the selected remote
environment. Container mount modes and disabled networking remain in effect.
The adapter does not claim to implement an additional Codex platform sandbox.
Keep the remote-only configuration above when using this command.

Ordinary requests that invoke `exec_command` run in Linux. Native `apply_patch`
uses remote filesystem operations. In the tested Codex version, `!command`
requires a local execution environment: with `include_local = false` it fails,
which is the intended behavior. That version can also exit the TUI on the
error. Do not enable a local environment to work around the failure.

The server implements an exec-server, not the Codex App Server.
`thread/shellCommand` is an App Server method and is not a route to add here.
PTY launches, extra platform sandbox requirements, and remote extension
launches are unsupported and return errors.

The local integration fixtures test the installed CLI, remote shell execution,
native writable `apply_patch`, and read-only rejection using deterministic
model responses. A second fixture calls the real App Server's
`thread/shellCommand` and verifies rejection before execution, without starting
a model turn. These do not establish that every future CLI release uses these
routes unchanged.

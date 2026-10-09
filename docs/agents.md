# Agent setup

Start the server with the writable project first and `--preserve-paths`:

```sh
uv run remote-sandbox-container --preserve-paths \
  --mount-rw project=/absolute/path/to/project \
  --mount-ro reference=/absolute/path/to/reference
```

These recipes change the execution route. The coding-agent process and its
model connection continue running on the Mac. The container has no external
network connection, so install required tools into the image before the demo.

## Claude Code

The shared [Claude shell-prefix integration](https://github.com/prime-radiant-inc/remote-sandbox/tree/main/claude-shell-prefix) is maintained in the `remote-sandbox` repository. Follow its setup instructions using `REMOTE_SANDBOX_API_URL=http://127.0.0.1:8687` for this backend. Start the container with the project mounted and `--preserve-paths` as above; Claude's temporary bookkeeping directory must be inside a writable mount. The backend package no longer bundles the shell wrapper or Python client.

## Codex CLI

The compatibility target is **Codex CLI 0.154.0**. Its experimental exec-server
connection sends process and filesystem requests to
`ws://127.0.0.1:8687/codex`. It does not need the shell-prefix client.

Merge the following into the Codex environment configuration for the profile
you intend to use. The file is normally `~/.codex/environments.toml`; keep a
separate profile for this experiment if you already have environment settings.
These are setup instructions, not changes performed by the server.

```toml
default = "sandbox"
include_local = false

[[environments]]
id = "sandbox"
url = "ws://127.0.0.1:8687/codex"
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

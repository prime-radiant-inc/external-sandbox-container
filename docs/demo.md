# Team demo

Use the same coding task and client protocol with each prototype. All three
servers can run at the same time: v86 defaults to port `8686`, this Apple
Container server to port `8687`, and Quicksand to port `8688`. Select the backend
by setting the shell client `REMOTE_SANDBOX_API_URL` to `http://127.0.0.1:8686`,
`http://127.0.0.1:8687` or `http://127.0.0.1:8688`, or by setting
the Codex environment URL to the corresponding `ws://127.0.0.1:PORT/codex`
endpoint. The demo project has a deliberate arithmetic bug and uses Python's
standard library, so it works without package downloads.

## Prepare a fresh workspace

From this application's root:

```sh
DEMO_ROOT=$(mktemp -d /private/tmp/sandbox-demo.XXXXXX)
cp -R examples/demo-project "$DEMO_ROOT/project"
cp -R examples/reference "$DEMO_ROOT/reference"
uv run remote-sandbox-container --port 8687 --preserve-paths \
  --mount-rw "project=$DEMO_ROOT/project" \
  --mount-ro "reference=$DEMO_ROOT/reference"
```

Use the reported project path in another terminal to launch the agent using
[the setup instructions](agents.md). The mounted project is a disposable copy;
the repository's deliberately broken fixture remains ready for another run.

Ask the agent:

> Run `uname -s` and `pwd` using your shell tool. Read
> `/mnt/reference/requirements.md`, then run `python3 check_average.py`.
> Fix the implementation and rerun the checks. Report where your commands ran.

Expected observations:

1. The shell reports Linux and the mounted working directory.
2. The initial checks fail on fractional averages.
3. The fix appears immediately in the host's project copy.
4. Rerunning the checks passes.

To demonstrate the read-only mount through the shell path, ask the shell to
attempt `printf forbidden > /mnt/reference/blocked.txt`; it should fail. With
Codex, native `apply_patch` also uses the remote filesystem and must fail there.
Claude's host file tools have a different scope, as described in the setup
document. Do not use `!command` in Codex to run the demo: its local-only shortcut
is intentionally unavailable.

## Optional tool image

The default Python image is enough for this arithmetic demo. The included
`examples/Containerfile` adds Node.js 24 LTS/npm/npx, uv/uvx, ripgrep (`rg`), jq,
patch, unzip, curl, Git, procps (including `ps`), and CA certificates for broader
coding tasks. Node 24.21.0 and uv 0.12.15 are copied from their official images;
the runtime image remains based on `python:3.13-slim`. Build it while host
networking is available:

```sh
container build --tag sandbox-demo:latest --file examples/Containerfile .
```

The build options follow Apple's
[container command reference](https://github.com/apple/container/blob/main/docs/command-reference.md#container-build).

Then pass `--image sandbox-demo:latest` to `uv run remote-sandbox-container` alongside
the same mount options. Image building and package downloads happen before the
execution sandbox starts; commands still run with `--network none`. Having curl
installed does not give the offline container network access. To grant selected
HTTP(S) access without enabling a network interface, use the optional
[host-managed proxy](proxy.md).

In the browser terminal at `http://127.0.0.1:8687/`, check the installed tools:

```sh
curl --version
git --version
ps -ef
node --version
npm --version
uv --version
rg --version
echo '{"ready":true}' | jq .ready
patch --version
unzip -v
```

With the managed proxy enabled, Node receives `NODE_USE_ENV_PROXY=1` and
`NODE_EXTRA_CA_CERTS`; uv uses the same public CA bundle through `SSL_CERT_FILE`.
For example, the public proxy policy permits this Node request:

```sh
node -e 'fetch("https://example.com").then(r => console.log(r.status))'
```

Adding tools does not add allowed destinations. To install packages, grant the
needed registry origins in `/proxy` or your proxy configuration: ordinarily
`https://registry.npmjs.org` for npm, and `https://pypi.org` plus
`https://files.pythonhosted.org` for Python packages. Packages that fetch from
other hosts need corresponding rules. Existing Python is available to uv, so
Python downloads are unnecessary for projects compatible with Python 3.13.

## Verification

Run the server tests:

```sh
uv run pytest -m 'not integration'
```

The real Codex CLI fixtures require Codex **0.154.0** and a running server with
`project` and `reference` mounts. The fixture creates uniquely named test files
within those mounts and removes them afterward. In another terminal, set the
paths to the same copied directories used above:

```sh
SANDBOX_EXEC_SERVER_URL=ws://127.0.0.1:8687/codex \
SANDBOX_TEST_RW=/absolute/path/to/demo/project \
SANDBOX_TEST_RO=/absolute/path/to/demo/reference \
uv run pytest -q -m integration tests/test_codex_cli.py
```

Set `CODEX_CLI_BIN` to select a different executable path for that pinned
version. If the URL or mount paths are missing, these tests skip. The execution
fixture uses the real CLI, WebSocket server, container process execution, and
filesystem RPCs. Only model inference is simulated, by a temporary localhost Responses server
that requests one command, one writable patch, and one rejected read-only patch.
No API key is inherited and no real model request is made. The temporary Codex
profile has `include_local = false`.

A separate App Server fixture initializes a real Codex thread and calls
`thread/shellCommand`, the route used by `!command`. It asserts the specific
`local environment is not configured` error, no execution events, and no
sentinel command output. No model turn is started; a local provider guard also
verifies that no inference request occurs. This checks the client's intended
failure behavior with `include_local = false`.

This fixture verifies compatibility with one pinned CLI version. A successful
run should be recorded with the container CLI and image versions when sharing
results. No live Claude model session is claimed by these tests.

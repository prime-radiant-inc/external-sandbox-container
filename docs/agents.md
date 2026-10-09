# Agent setup

Start the server with the writable project first and `--preserve-paths`:

```sh
uv run remote-sandbox-container --preserve-paths \
  --mount-rw project=/absolute/path/to/project \
  --mount-ro reference=/absolute/path/to/reference
```

The coding-agent process and its model connection continue running on the Mac. The container has no external network connection, so install required tools into the image before the demo.

## Claude Code

The shared [Claude shell-prefix integration](https://github.com/prime-radiant-inc/remote-sandbox/tree/main/claude-code) is maintained in the `remote-sandbox` repository. Follow its setup instructions using `REMOTE_SANDBOX_API_URL=http://127.0.0.1:8687` for this backend. Start the container with the project mounted and `--preserve-paths` as above; Claude's temporary bookkeeping directory must be inside a writable mount. The backend package no longer bundles the shell wrapper or Python client.

## Codex

Follow the shared [Codex setup instructions](https://github.com/prime-radiant-inc/remote-sandbox/tree/main/codex), using `ws://127.0.0.1:8687/codex` for this backend. Launch the server with the writable and read-only mounts above and run Codex from the mounted project. See [protocol compatibility](protocol.md) for the backend's supported operations and [verification](demo.md#verification) for its opt-in Codex CLI tests.

## Pi

Use the backend's [Pi extension](../pi-extension/README.md), which defaults to `http://127.0.0.1:8687`.

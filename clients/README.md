# Streaming client

`remote_sandbox_exec.py` speaks the shared `/exec/ws` protocol and works with both remote-sandbox backends. It originated as `scripts/v86_exec.py` in the v86 prototype; the historical source hashes are recorded in [provenance](../PROVENANCE.md).

The canonical settings are `REMOTE_SANDBOX_API_URL`, `REMOTE_SANDBOX_CWD`, `REMOTE_SANDBOX_TIMEOUT_MS`, `REMOTE_SANDBOX_MAX_OUTPUT_BYTES`, and `REMOTE_SANDBOX_FORWARD_STDIN`. Each accepts the corresponding `V86_*` variable as a fallback alias. The new setting wins when both names are present, including when its value is empty; existing validation still applies.

The client retains its default port `8686`. Select the container server explicitly:

```sh
REMOTE_SANDBOX_API_URL=http://127.0.0.1:8687 uv run clients/remote_sandbox_exec.py --no-stdin 'uname -a'
```

`claude-shell-prefix.sh` defaults `REMOTE_SANDBOX_API_URL` to `http://127.0.0.1:8687`, using `V86_API_URL` first when only that legacy setting exists. An explicit URL selects either server. The wrapper locates the Python client beside itself and passes Claude's complete command argument through without evaluating it in a host shell. See [agent setup](../docs/agents.md) for the Claude environment variables.

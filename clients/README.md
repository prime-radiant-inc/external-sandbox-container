`v86_exec.py` is copied unchanged from the v86-shell-server prototype's
`scripts/v86_exec.py`. Its existing `V86_API_URL`, `V86_CWD`, `V86_TIMEOUT_MS`,
and `V86_MAX_OUTPUT_BYTES` settings work with this server too. Keeping the
original client demonstrates compatibility across the two execution backends.

The original client defaults to v86 on port `8686`. Select this server explicitly:

```sh
V86_API_URL=http://127.0.0.1:8687 uv run clients/v86_exec.py --no-stdin 'uname -a'
```

`claude-shell-prefix.sh` is adapted from the prototype to default `V86_API_URL`
to `http://127.0.0.1:8687` when unset. An explicit URL selects either server.
It locates the Python client beside itself and passes Claude's complete command argument
through without evaluating it in a host shell. See
[agent setup](../docs/agents.md) for the Claude environment variables.

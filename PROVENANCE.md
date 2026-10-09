# Provenance

This separate Python app began with the requested command:

```sh
uv init uv-init-app --app
```

The generated directory/package was renamed `sandbox-exec-server` /
`sandbox_exec_server` so that future Docker support will not require a rename.
The existing TypeScript/v86 project was read as a protocol reference and was
not modified.

Reference: `v86-shell-server` 0.2.0 at commit
`3b0002f1a511728b1f56638ea937a03447fbebbf`, produced in the
“v86 WASM for Claude Code” research conversation. The HTTP, streaming WebSocket,
and Codex adapters are Python implementations of those existing contracts.

The Python client is copied unchanged from that project. The shell wrapper was
initially copied unchanged, then given a default `V86_API_URL` of
`http://127.0.0.1:8687` so both servers can run side by side. The hashes below
identify the original source files:

| File | SHA-256 |
| --- | --- |
| `clients/v86_exec.py` | `2b1979be5733409d2761a493556622584ed7b1b8fe089c1812d6895f1aa0ca46` |
| `clients/claude-shell-prefix.sh` | `e41b327d7087080c79f232cd133915d36e80c8a431b31551dcf8fe818b917a72` |

The historical `v86` client name and `V86_*` environment settings are retained
on purpose to demonstrate client compatibility. The server app/package name
is backend-neutral.

The Codex protocol target is its experimental `rust-v0.154.0` exec-server
protocol. This project does not bundle a Codex binary, an Apple Container
binary, or a Linux image. The selected OCI image is obtained independently by
Apple Container. Python dependencies are recorded in `uv.lock`.

## Rename — 9 October 2026

The project is now `remote-sandbox-container`, its Python module is `remote_sandbox_container`, and the streaming helper is `clients/remote_sandbox_exec.py`. The client now prefers `REMOTE_SANDBOX_*` environment settings while retaining `V86_*` as fallback aliases. The historical names, paths, and source hashes above describe the original import and have been preserved. The shared UI is now `remote-sandbox-ui`; protocol strings and default ports are unchanged.

## Shared client relocation — 9 October 2026

The Claude shell-prefix wrapper, Python streaming client, and their configuration tests are now maintained in [remote-sandbox/claude-code](https://github.com/prime-radiant-inc/remote-sandbox/tree/main/claude-code). Their implementation copies were removed from this repository and from Python package resources. The source hashes and earlier paths above remain historical records. `--write-setup` now exports only `Containerfile` and `proxy.json`; optional backend compatibility tests use an explicitly selected external client.

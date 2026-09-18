# Compatibility contract

The reference is `v86-shell-server` 0.2.0's existing client protocol. Endpoints
and message shapes stay the same while the process and filesystem backend
changes. Runtime identity, architecture, available binaries, timing, and mount
implementation naturally differ.

| Route | Behavior |
| --- | --- |
| `GET /health` | Runtime readiness, mount mappings, default cwd, active commands |
| `GET /mounts` | `{ "mounts": [...] }` with host/guest paths and modes |
| `POST /exec` | Buffered Bash command execution |
| `WS /exec/ws` | One streaming shell command per connection |
| `WS /codex` | Codex exec-server JSON-RPC process and filesystem operations |

## Shell API

`POST /exec` accepts `command`, `cwd`, `env`, `stdin`, `timeoutMs`, and
`maxOutputBytes`. `stdin` is a UTF-8 string for HTTP and a boolean for the
WebSocket start message. The command runs under Bash inside Linux.

Streaming clients send:

```json
{"type":"start","command":"printf ready; cat; printf problem >&2; exit 7","cwd":"/mnt/project","stdin":true,"timeoutMs":120000,"maxOutputBytes":4194304}
```

The server sends `started` before output. stdout and stderr are separate
base64-encoded byte streams:

```json
{"type":"started","processId":"example"}
{"type":"stdout","data":"cmVhZHk="}
```

Send stdin incrementally, with strictly increasing nonnegative integer IDs:

```json
{"type":"stdin","id":0,"data":"aGVsbG8K"}
{"type":"stdin_eof"}
```

The corresponding acknowledgements are `stdin_ack` with the matching `id` and
`stdin_closed`. Acknowledgement means queued, not necessarily read by the
program. Output and acknowledgements may interleave. A command finishes with
one event after all its output:

```json
{"type":"exit","exitCode":7,"signal":null,"timedOut":false,"outputLimitExceeded":false,"durationMs":123}
```

Send `{"type":"cancel"}` or close the WebSocket to cancel the process group.
Timeouts and output caps also stop the process group. A process that deliberately
escapes its process group is outside per-command cleanup; removing the server's
container ends its remaining processes. If an escaped descendant retains output
pipes after the command leader exits, the server returns an explicit error
after a bounded drain period rather than waiting indefinitely.

An error is `{"type":"error","error":"Explanation"}`. A close without an
`exit` event is a failed execution, even with close code 1000. Normal command
exit codes are preserved by the existing Python client; signals map to
`128 + signal`, timeout to 124, and API/output-limit failure to 125.

No host or image environment is implicitly passed to submitted commands. The
guest agent supplies a fixed minimal environment with Linux `PATH`, `HOME`,
`SHELL`, `USER`, `LOGNAME`, and locale settings. Explicit request environment
fields control guest variables. Passing an API key in an explicit request would still
put that key inside the container; this backend has no credential substitution.

## Codex exec-server

The adapter supports `initialize`, `initialized`, `environment/info`,
`environment/status`, process start/read/write/signal/terminate, and the
filesystem operations needed for native `apply_patch`. Process requests use
literal argument arrays, cwd, and environment settings. Command output is
streamed, with sequence numbers for read/replay requests.

Filesystem paths are guest `file://` URIs. The backend resolves them inside the
container, including paths in its disposable filesystem; they are not host
filesystem paths interpreted by the Python server. Read-only mounts constrain
both commands and filesystem RPCs.

The experimental protocol target is Codex CLI 0.154.0. Unsupported requests
fail explicitly. In particular, this server does not add PTYs, Codex's local
platform sandboxes, remote extension execution, or the App Server's
`thread/shellCommand` method.

## Deliberate differences

- Linux runs in Apple's container runtime rather than an x86 emulator.
- Docker is a possible future backend, not an accepted backend in this version.
- The v86 managed network proxy is absent. The container starts with
  `--network none`; proxy/credential-policy options are not silently accepted.
- Filesystem ownership, permissions, links, and metadata follow Apple's shared
  filesystem behavior. v86-specific host filesystem guarantees are not claimed.
  Read-only protection belongs to each mount, rather than v86's per-inode host
  bridge. Overlapping host roots with mixed read-only/read-write modes are
  rejected, but pre-existing writable hardlink aliases in separate mounted
  directories are not detected. Do not share such aliases when relying on a
  read-only mount: writes through the writable name can change the same inode.
- The default image is intentionally small. Tools must be present in the image
  before offline execution begins.

# Protocol and deliberate differences

This server implements the shared External Sandbox protocol. The normative
definition is [SPEC.md](https://github.com/prime-radiant-inc/external-sandbox/blob/main/SPEC.md)
in the `external-sandbox` repository, and
[COVERAGE.md](https://github.com/prime-radiant-inc/external-sandbox/blob/main/COVERAGE.md)
maps each requirement to the conformance test that exercises it. Run the
conformance runner against a server to check this backend; see
[verification](verification.md).

The `/codex` route follows the experimental exec-server protocol of Codex CLI
0.164.0. Unsupported requests fail explicitly. In particular, this server does
not add PTYs, Codex's local platform sandboxes, remote extension execution, or
the App Server's `thread/shellCommand` method.

## Guest environment

No host or image environment is implicitly passed to submitted commands. The
guest agent supplies a fixed minimal environment with Linux `PATH`, `HOME`,
`SHELL`, `USER`, `LOGNAME`, and locale settings. Explicit request environment
fields control guest variables. With the optional managed proxy, defaults also
include proxy/CA settings and configured placeholders. Passing a real API key
in an explicit request still puts that key inside the container; use
[host proxy credential substitution](proxy.md) to keep it outside instead.

## Deliberate differences

Where the specification permits implementation variation, this backend chooses:

- Linux runs in Apple's container runtime rather than an x86 emulator.
- Docker is a possible future backend, not an accepted backend in this version.
- The container starts with `--network none`. Optional `--proxy-config` enables
  HTTP(S) egress through the command pipe to a host Python proxy, using the
  shared allow-list/credential configuration schema. See [proxy details](proxy.md).
- Filesystem ownership, permissions, links, and metadata follow Apple's shared
  filesystem behavior. Read-only protection belongs to each mount, rather than
  v86's per-inode host bridge. Overlapping host roots with mixed read-only and
  read-write modes are rejected, but pre-existing writable hardlink aliases in
  separate mounted directories are not detected. Do not share such aliases when
  relying on a read-only mount: writes through the writable name can change the
  same inode.
- The default image is intentionally small. Tools must be present in the image
  for offline execution, or their download destinations explicitly allowed by
  the optional proxy.

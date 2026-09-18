# Proxy transport across the guest control pipe

The Apple Container backend always starts the workload with `--network none
--cap-drop ALL`. Enabling the managed proxy does not add an external interface,
change host firewall rules, or give the guest a general-purpose TCP tunnel.

The Python server starts its host proxy first. `AppleContainerBackend(proxy=...)`
accepts that already-running proxy's fixed `('127.0.0.1', port)` address, public CA
certificate (`ca_pem`), and placeholder-only `guest_env`. The host keeps credentials
and private CA keys outside the guest. The backend launches the container, waits
for its helper's initial `ready` event, then sends a `configure_proxy` RPC containing
only the public CA certificate. Boot completes only after that RPC succeeds.

The helper writes a public CA bundle at
`/run/sandbox-exec-proxy/ca-bundle.pem`, including the image's existing system roots,
and starts a listener on a dynamically allocated guest loopback port. The default
command environment adds:

- `HTTP_PROXY`, `HTTPS_PROXY`, `http_proxy`, and `https_proxy`, all pointing to that
  guest loopback listener.
- Empty `NO_PROXY` and `no_proxy` values.
- `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, and
  `NODE_EXTRA_CA_CERTS`, all pointing at the public bundle.
- Configured placeholder environment variables. Real credentials never cross this
  setup RPC or enter the guest command environment.

Explicit environment replacement in the execution API retains its existing
meaning. A client that supplies its own environment must preserve these values if
it wants proxy access. Removing proxy settings cannot create direct network access.
The health response retains `network: false` to describe the absent external NIC;
`proxyEnabled` separately reports whether the managed relay is configured.

## Private frames and flow control

Proxy traffic shares the existing length-prefixed JSON stdin/stdout channel with
process and filesystem RPC. Frames have `event: "proxy"`, an integer `streamId`,
and an `action`:

| Action | Direction | Additional fields | Meaning |
| --- | --- | --- | --- |
| `open` | Guest → host | None | Open the host's fixed policy proxy endpoint |
| `opened` | Host → guest | None | Fixed endpoint connection is ready |
| `data` | Either | `seq`, base64 `data` | Next numbered data chunk |
| `ack` | Either | `seq` | That chunk has drained to the destination socket |
| `eof` | Either | None | Close this direction of the stream |
| `close` | Either | None | Cancel and clean up the complete stream |

The guest allocates monotonically increasing stream IDs. IDs are never reused;
replayed or duplicate opens are invalid. `open` has no hostname, port, URL, or
address field. The host always connects to the address configured before the
container started. All domain, destination-IP, HTTP and credential policy is
applied by the host proxy to the traffic arriving there.

At most 32 streams (including closing tasks) are active. Each direction may have
only one unacknowledged chunk, at most 32 KiB. A receiver sends its ACK only after
socket `drain()` completes. The receive queue contains at most a data chunk and an
EOF marker. Socket read and write buffers are bounded independently. Socket
connection/open waits time out after 10 seconds; a stalled chunk ACK or socket
drain times out after 120 seconds. These timeouts close that stream.

Frame dispatch never awaits an individual socket. A blocked proxy destination
therefore does not stop processing command output, RPC replies, or another proxy
stream. The pipe is still a shared finite transport: a guest that stops consuming
it can interrupt the server's work, but cannot bypass the host's network policy.

Malformed fields, excessive data, out-of-window sequence numbers, forged ACKs,
unknown future IDs, and excessive opens fail the private transport closed. Late
frames for already closed stream IDs are ignored to allow concurrent shutdown.
Ordinary endpoint failures close the affected stream without any fallback route.

## Lifecycle and trust

On server or agent shutdown, the guest closes its listener and the host and guest
cancel relay tasks and close open sockets. A malformed or disconnected agent pipe
also closes the host relay and the agent's stdin. Existing container cleanup then
handles removal of the disposable workload.

The helper shares the guest's user and filesystem with executed commands. Guest
code may disrupt or replace it, its public trust bundle, or its protocol messages.
It is a transport convenience, not an enforcement boundary. The fixed host
endpoint and the independent host policy are the enforcement boundary.

`tests/test_proxy_relay.py` covers concurrent binary full-duplex streams, half
close, bounded credit and stream counts, slow receivers, forged/oversized frames,
fixed routing, public CA installation, setup ordering, RPC responsiveness, and
cleanup. The core relay and guest listener use only the Python standard library.

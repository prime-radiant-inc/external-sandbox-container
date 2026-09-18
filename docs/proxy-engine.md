# Embedded HTTP and HTTPS proxy

The proxy is part of the host Python server. It does not run another daemon or
proxy container. The Apple workload container remains on `--network none`.
Its loopback listener forwards bytes through the existing framed command pipe;
the host relay connects only to this proxy's fixed loopback address. The guest
cannot ask that relay to connect to an arbitrary host or port.

Changing guest proxy variables, replacing its listener, or forging relay
messages does not change the host's policy. Real credentials and the CA signing
key remain in the host process. The guest receives only public trust material
and literal placeholder values. As with the rest of this demo, the host API and
other host-side agent tools must be restricted to trusted local users.

## Policy format

The configuration uses the v86 proxy's `allow` and optional `guestEnv` format.
An empty `allow` list denies all egress. Unknown fields, malformed entries,
duplicate origins, missing host secrets, and accidental real keys copied into
guest placeholders cause configuration to fail before a container starts.

```json
{
  "allow": [{
    "origin": "https://api.example.com",
    "methods": ["POST"],
    "paths": ["/v1/messages"],
    "credential": {
      "header": "authorization",
      "placeholder": "Bearer public-demo-placeholder",
      "secretEnv": "EXAMPLE_API_KEY",
      "prefix": "Bearer "
    }
  }],
  "guestEnv": {"EXAMPLE_API_KEY": "public-demo-placeholder"}
}
```

`origin` is an exact canonical HTTP or HTTPS origin, optionally with a
non-default port. Wildcards, credentials, paths, fragments, and ambiguous IP
spellings are rejected. Optional `methods` and `paths` restrict HTTP methods and
exact URL pathnames; path matching does not include query strings. A missing
method/path list allows all supported methods/paths on that origin. No rule
allows CONNECT tunneling to arbitrary protocols or WebSocket upgrades.

`allowCidrs`, when present, is a nonempty list of permitted IP CIDR ranges. It
replaces the default public-address-only restriction. Loopback, private,
link-local, multicast, documentation, and transition addresses are denied by
default. A private service needs both its exact origin and its IP range allowed.
IPv4-mapped IPv6 addresses use the IPv4 policy.

The host resolves DNS after request authorization, selects an allowed numeric
address, and pins that address for the connection. DNS is not consulted again
by the upstream HTTP connector. HTTPS still verifies the original hostname and
certificate chain. Redirects are returned to the client rather than followed;
each subsequent request passes through policy independently.

Credentials can be attached only to HTTPS rules. The entire incoming credential
header must equal `placeholder`, with exactly one occurrence of the header. The
outgoing value is `prefix + host_environment[secretEnv]`. A missing or incorrect
placeholder is denied. `guestEnv` is a literal map; strings such as `$API_KEY`
are never expanded from the host environment. Host secrets are captured at
startup and reused for live policy validation.

Live policy updates validate completely before replacing the current policy.
A successful update closes active proxy connections, including streaming
responses, so removing a rule revokes existing streams. Updating `guestEnv`
requires restarting the server, because the running guest environment has
already been initialized. Other rule changes apply without a restart. An
invalid update preserves both the policy and active connections.

## TLS and credentials

HTTPS uses CONNECT followed by TLS interception. The proxy issues short-lived
certificates from a new CA created when the server starts. Only its public CA
certificate enters the guest; nothing is added to the host trust store.
Certificates expire after 30 days, so restart the server before then. Pinned
certificate clients or clients that ignore the supplied trust settings can fail.
Neither client nor upstream certificate verification is disabled to work around
that limitation.

Python's TLS API requires filenames to load a certificate and private key.
The proxy writes each **leaf** key into a mode-0600 file in a mode-0700 temporary
directory, loads the TLS context, and immediately removes those files. The CA
private signing key stays in memory. These temporary files are not part of the
normal runtime mount. Do not mount the host temporary directory, its ancestors,
or directories containing host secrets into the guest: broad host mounts can
expose files independently of the proxy. Private keys are never included in
protocol messages or management responses.

Known literal credential values are redacted from response headers and bodies,
including when a secret spans multiple response chunks. Ordinary SSE events
stream immediately; only a suffix that could be the beginning of a credential
is held for the next chunk. The proxy requests identity content encoding and
rejects compressed responses before forwarding their headers. Response sizes
are reframed after redaction, and upstream hop-by-hop headers are removed.

Literal redaction is defense in depth. An allowed upstream can encode or
transform a secret and evade literal matching, so allowed services must still
be trusted. A placeholder also grants the ability to use whatever API actions
the policy permits: hiding a key does not implement spending limits or account
authorization beyond those rules.

## Bounds and activity

The engine accepts HTTP/1.1 and processes one request per connection, plus an
optional CONNECT/TLS handshake. It advertises `Connection: close`; normal HTTP
clients reconnect as needed. HTTP/2, HTTP/3, request trailers, arbitrary TCP/UDP,
incoming connections, and WebSocket upgrades are not supported. This affects
connection reuse but supports ordinary clients, binary bodies, and SSE.

Limits are 64 simultaneous connections, 64 KiB of headers and 100 header fields,
16 MiB per request body, 64 MiB of collectively accounted request bodies, and
256 MiB per response body. Request bodies are buffered before upstream
transmission; response bodies stream with transport backpressure. Python may
briefly make an additional copy while finalizing a request body, so the request
accounting limit is not a total process-memory limit. A request has a five-minute
lifetime and a two-minute idle limit; DNS and connection establishment have
15-second limits. The pipe relay has its own bounded queues and flow control.

Activity retains the most recent 500 completed/denied requests, including
timestamp, method, origin, path, status, duration, result, and whether a
credential was inserted. It excludes query strings, request/response bodies,
headers, resolver details, and exception messages. Known secrets are redacted
from metadata too. Events are in memory only and disappear on shutdown.

## Validation

`tests/test_proxy_policy.py` covers configuration validation, credential and
path rules, special-address rejection, mapped addresses, and DNS selection.
`tests/test_proxy.py` uses local HTTP and TLS servers with synthetic credentials
to check verified upstream TLS, hostname/IP pinning, CONNECT/Host mismatches,
binary traffic, immediate SSE delivery, cross-chunk redaction, blocked origins,
methods and paths, unchanged redirects, denied compression/upgrades, size
limits, and atomic policy updates that revoke active streams.

The relay and Apple integration tests additionally exercise the same engine
through the existing command pipe. No test requires paid API calls or personal
credentials.

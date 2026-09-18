# Local proxy management

When the server has a managed proxy, open
`http://127.0.0.1:8687/proxy` in your browser. Use the configured API port if you
changed it. The page is served by the existing local HTTP server and does not
load scripts, styles, fonts, or other resources from the Internet.

The page shows the current allowed origins, method and path restrictions, and
the host environment variable name associated with each credential rule. The
JSON editor accepts the same policy object used by the proxy configuration.
Click **Apply policy** to validate and atomically replace the active policy. An
invalid edit leaves the current policy unchanged. **Discard edits** restores
the latest active policy shown by the server.

Changes are **runtime only** and do not rewrite your configuration file.
Applying a policy closes active proxy connections so that new requests use the
updated rules. Update your configuration file separately to preserve changes
after restarting the server. Changes to `guestEnv` require a server restart;
runtime policy updates that change this field are rejected.

## Credentials

The editor is for credential **references**, never real credential values.
For example, `secretEnv: "EXAMPLE_API_KEY"` refers to the environment variable
available to the host server. `placeholder` and `guestEnv` contain guest-visible
dummy tokens. Do not paste a real API key into any of these fields, including
`guestEnv`. Missing host secrets or invalid credential rules cause the policy
update to fail.

The page never requests or displays the values of the host environment
variables. The proxy's snapshot contains a safe policy representation and a
bounded list of sanitized events. Activity shows request metadata and decisions;
it excludes authentication headers, request/response bodies, and real keys.
The list refreshes every three seconds without overwriting edits in progress.

## Local access boundary

This is a management interface for trusted local users, not a remotely exposed
administration service. Keep the server bound to loopback.

The HTML page contains a fresh random token for this server instance. Its
JavaScript sends that token in `X-Proxy-Token` with every JSON API request. The
server accepts only loopback Host headers and same-origin browser requests,
does not enable CORS, and rejects cross-origin Fetch Metadata. Frame embedding
is disabled. Policy/event text is inserted as text, not HTML. A restrictive
Content Security Policy allows only the page's bundled script/style and
same-origin API requests. Responses are not cached.

Any local process capable of fetching the page can obtain the token; it is a
browser cross-origin protection, not authentication between mutually untrusted
host users. The execution and Codex APIs retain their existing browser Origin
restriction. The only exceptions are `/proxy` and `/proxy/api`, which perform
their own origin and token checks.

For programmatic local management, fetch `/proxy`, extract its `proxy-token`
meta value, then send the token in `X-Proxy-Token` to:

- `GET /proxy/api`: the safe `{enabled, policy, events}` snapshot.
- `PUT /proxy/api`: replace the policy with an `application/json` object; the
  response is the updated snapshot. The body is limited to 256 KiB.

No endpoint returns or sets a real host secret. Validation errors intentionally
omit the underlying exception text so supplied credentials cannot leak through
error messages.

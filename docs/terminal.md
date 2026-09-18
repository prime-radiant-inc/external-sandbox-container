# Browser terminal

Open `http://127.0.0.1:8687/` while the server is running. The homepage is a
browser client for the same streaming `/exec/ws` protocol used by the existing
command-line client. Commands run in the server's container, with its existing
mounts, environment, and network policy.

Choose a **Working directory** and time limit, then type a command and select
**Run command**. Enter submits; Shift+Enter adds a line. The arrow keys browse
command history. While a command is running, the same text box sends input to
that command. **Send EOF** closes stdin; **Cancel** stops the active command.
**Clear output** clears the displayed transcript without stopping a command.

Try these commands:

```sh
uname -s; pwd; whoami
```

```sh
python3 -u -c 'import time; print("first line", flush=True); time.sleep(1); print("second line")'
```

```sh
cat
```

The first command identifies the Linux environment. The second demonstrates
streaming output. With `cat`, send text to the running command, then close
stdin to let it exit. You can also cancel an active command. The server reports
its exit status, signal, timeout, or output-limit failure.

## Command sessions

Each run starts a fresh Bash command in the selected working directory. A `cd`
or `export` in one run does not change later runs. Files written inside the
shared container persist until server shutdown; writable host mounts retain
changes afterward. A command such as `cd /mnt/project && python3 check.py`
works within one run.

Input and output use pipes, not a pseudo-terminal. Line-oriented programs such
as `cat` or the Python REPL (`python3 -u -i`) work; full-screen terminal applications and programs
that require a TTY are not supported. Programs may buffer stdout when it is a
pipe, so use their unbuffered option when demonstrating live output.

Closing the page disconnects its active WebSocket and cancels that command.
It does not stop the shared container or commands owned by other clients.
The command protocol permits one execution per WebSocket connection; the page
opens a new connection for each run.

## Network experiments

When started with `--proxy-config examples/proxy-public.json`, the server
allows requests to `https://example.com`:

```sh
python3 -c 'import urllib.request; print(urllib.request.urlopen("https://example.com", timeout=15).status)'
```

Changing the URL to `https://example.org` demonstrates a denied destination.
Open `/proxy` to inspect activity or change the allow-list. Changes apply to
the same container used by this terminal and the command-line/agent clients.
The container still has no external network interface; `ls /sys/class/net`
shows its loopback interface. See [proxy details](proxy.md).

## Browser access

The homepage is for trusted local use and must remain on the server's loopback
address. Browser WebSocket requests require the exact same origin, including
the port, and a random token embedded in the homepage. The token is carried in
the WebSocket subprotocol request rather than the URL. Only `sandbox-terminal`
is negotiated in the response; the token is not echoed as the selected
subprotocol. Reload the page after restarting the server to obtain a fresh
token.

Unrelated websites cannot read the token or open an authorized command socket.
Local processes can fetch the page, so this is a browser cross-origin boundary,
not authentication between mutually untrusted host users. Existing clients
without a browser Origin header keep using the unchanged `/exec/ws` API.
The buffered execution API and Codex API retain their existing browser
restrictions.

# Deliberately broken demo project

`average.py` contains a small arithmetic bug. The checks intentionally fail until
the agent fixes it. Copy this directory before each demo; do not treat these
checks as the server's test suite.

Suggested agent prompt:

> Run `uname -s` and `pwd` using your shell tool. Read
> `/mnt/reference/requirements.md`, then run `python3 check_average.py`.
> Fix the implementation and rerun the checks. Report where your commands ran.

The expected operating system is Linux. For Codex, process and filesystem tools
use the remote executor. Claude's shell prefix redirects shell execution; its
native file tools still run on the host, where the writable project is shared.

#!/bin/sh
# Claude supplies its complete shell command as one argument. Never evaluate it here.
SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd) || exit 125
: "${REMOTE_SANDBOX_API_URL=${V86_API_URL-http://127.0.0.1:8687}}"
export REMOTE_SANDBOX_API_URL
exec uv run --quiet --script "$SCRIPT_DIR/remote_sandbox_exec.py" "$@"

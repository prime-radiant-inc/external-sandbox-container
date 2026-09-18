#!/bin/sh
# Claude supplies its complete shell command as one argument. Never evaluate it here.
SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd) || exit 125
: "${V86_API_URL:=http://127.0.0.1:8687}"
export V86_API_URL
exec uv run --quiet --script "$SCRIPT_DIR/v86_exec.py" "$@"

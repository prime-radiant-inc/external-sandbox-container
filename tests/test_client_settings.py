"""Client renaming keeps legacy configuration usable with explicit precedence."""

import os
from pathlib import Path
import runpy
import subprocess

import pytest


CLIENTS = Path(__file__).resolve().parents[1] / "clients"
CLIENT = runpy.run_path(str(CLIENTS / "remote_sandbox_exec.py"))


@pytest.mark.parametrize("suffix", ["API_URL", "CWD", "TIMEOUT_MS", "MAX_OUTPUT_BYTES", "FORWARD_STDIN"])
def test_new_client_settings_override_legacy_aliases(suffix, monkeypatch):
    current = "REMOTE_SANDBOX_" + suffix
    legacy = "V86_" + suffix
    monkeypatch.delenv(current, raising=False)
    monkeypatch.delenv(legacy, raising=False)
    assert CLIENT["environment_setting"](current, "fallback") == "fallback"
    monkeypatch.setenv(legacy, "legacy")
    assert CLIENT["environment_setting"](current) == "legacy"
    monkeypatch.setenv(current, "current")
    assert CLIENT["environment_setting"](current) == "current"
    monkeypatch.setenv(current, "")
    assert CLIENT["environment_setting"](current) == ""


@pytest.mark.parametrize("current,legacy,expected", [
    (None, None, "http://127.0.0.1:8687"),
    (None, "http://127.0.0.1:8686", "http://127.0.0.1:8686"),
    ("http://127.0.0.1:9876", "http://127.0.0.1:8686", "http://127.0.0.1:9876"),
    ("", "http://127.0.0.1:8686", ""),
])
def test_shell_wrapper_uses_renamed_client_and_setting_precedence(tmp_path, current, legacy, expected):
    fake_uv = tmp_path / "uv"
    fake_uv.write_text('#!/bin/sh\nprintf "%s\\n" "$REMOTE_SANDBOX_API_URL" "$@"\n')
    fake_uv.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if key not in {"REMOTE_SANDBOX_API_URL", "V86_API_URL"}}
    env["PATH"] = str(tmp_path) + os.pathsep + env["PATH"]
    if current is not None:
        env["REMOTE_SANDBOX_API_URL"] = current
    if legacy is not None:
        env["V86_API_URL"] = legacy
    result = subprocess.run([str(CLIENTS / "claude-shell-prefix.sh"), "printf unchanged"], env=env, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [expected, "run", "--quiet", "--script", str(CLIENTS / "remote_sandbox_exec.py"), "printf unchanged"]

"""Setup export works without a server and preserves existing user files."""
import os
import sys
from importlib.resources import files

import pytest

from remote_sandbox_container import cli
from remote_sandbox_container.setup_files import SETUP_FILES, write_setup


def test_cli_exports_bundled_files_without_starting_server(tmp_path, monkeypatch, capsys):
    target = tmp_path / "nested" / "setup"
    monkeypatch.setattr(sys, "argv", ["remote-sandbox-container", "--write-setup", str(target)])
    monkeypatch.setattr(cli, "serve", lambda args: pytest.fail("Must not start the server"))
    cli.main()
    assert str(target.resolve()) in capsys.readouterr().out
    assert {p.name for p in target.iterdir()} == set(SETUP_FILES)
    for name in SETUP_FILES:
        assert (target / name).read_bytes() == files("remote_sandbox_container").joinpath("resources", name).read_bytes()
    assert "remote_sandbox_exec.py" in SETUP_FILES
    assert "remote_sandbox_exec.py" in (target / "claude-shell-prefix.sh").read_text()
    assert os.access(target / "claude-shell-prefix.sh", os.X_OK)
    mtimes = {p.name: p.stat().st_mtime_ns for p in target.iterdir()}
    assert write_setup(target) == target.resolve()
    assert {p.name: p.stat().st_mtime_ns for p in target.iterdir()} == mtimes


@pytest.mark.parametrize("kind", ["edited", "directory", "symlink", "dangling-symlink"])
def test_output_conflicts_fail_before_writing_any_files(tmp_path, kind):
    target = tmp_path / "setup"
    target.mkdir()
    conflict = target / "remote_sandbox_exec.py"
    original = tmp_path / "original"
    original.write_text("keep me")
    if kind == "edited":
        conflict.write_text("custom client")
    elif kind == "directory":
        conflict.mkdir()
    else:
        conflict.symlink_to(original if kind == "symlink" else tmp_path / "missing")
    with pytest.raises(ValueError, match="Refusing to overwrite"):
        write_setup(target)
    assert list(target.iterdir()) == [conflict]
    assert original.read_text() == "keep me"
    if kind == "edited":
        assert conflict.read_text() == "custom client"


@pytest.mark.parametrize("kind", ["file", "symlink", "dangling-symlink"])
def test_rejects_invalid_destination(tmp_path, kind):
    target = tmp_path / "setup"
    if kind == "file":
        target.write_text("keep me")
    else:
        destination = tmp_path / "destination"
        if kind == "symlink":
            destination.mkdir()
        target.symlink_to(destination)
    with pytest.raises(ValueError, match="Setup destination must be a directory"):
        write_setup(target)
    if kind == "file":
        assert target.read_text() == "keep me"
    elif kind == "symlink":
        assert list(destination.iterdir()) == []
    else:
        assert not destination.exists()

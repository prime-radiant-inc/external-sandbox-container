import stat
from importlib.resources import files
from pathlib import Path

import pytest

from external_sandbox_container import cli
from external_sandbox_container.images import ensure_tools_image, tools_image_tag

def fake_container(tmp_path: Path, *, present=False, build_exit=0) -> tuple[str, Path]:
    log = tmp_path / "calls.log"
    script = tmp_path / "container"
    script.write_text(f"""#!/bin/sh
printf '%s\\n' "$*" >> '{log}'
case "$1 $2" in
  "image inspect") exit {0 if present else 1} ;;
esac
if [ "$1" = build ]; then
  while [ $# -gt 0 ]; do
    [ "$1" = --file ] && cp "$2" '{tmp_path}/built-recipe'
    context="$1"; shift
  done
  printf '%s\\n' "$context" > '{tmp_path}/built-context'
  echo build-stdout-line
  echo build-stderr-line >&2
  exit {build_exit}
fi
exit 99
""")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script), log

def recipe() -> bytes:
    return files("external_sandbox_container").joinpath("resources/Containerfile").read_bytes()

def test_tag_is_derived_from_the_recipe():
    assert tools_image_tag(b"one") == tools_image_tag(b"one")
    assert tools_image_tag(b"one") != tools_image_tag(b"two")
    assert tools_image_tag().startswith("external-sandbox-container-tools:")
    assert tools_image_tag() == tools_image_tag(recipe())

async def test_existing_image_is_not_rebuilt(tmp_path):
    binary, log = fake_container(tmp_path, present=True)
    assert await ensure_tools_image(binary) == tools_image_tag()
    assert log.read_text().splitlines() == [f"image inspect {tools_image_tag()}"]

async def test_missing_image_is_built_from_the_bundled_recipe(tmp_path):
    binary, log = fake_container(tmp_path)
    assert await ensure_tools_image(binary) == tools_image_tag()
    calls = log.read_text().splitlines()
    assert calls[0] == f"image inspect {tools_image_tag()}"
    assert calls[1].startswith(f"build --progress plain --tag {tools_image_tag()} --file ")
    assert (tmp_path / "built-recipe").read_bytes() == recipe()

async def test_build_context_is_temporary(tmp_path):
    binary, _ = fake_container(tmp_path)
    await ensure_tools_image(binary)
    context = Path((tmp_path / "built-context").read_text().strip())

    assert not context.exists()
    assert context != Path.cwd()

async def test_build_output_never_reaches_stdout(tmp_path, capfd):
    binary, _ = fake_container(tmp_path)
    await ensure_tools_image(binary)
    captured = capfd.readouterr()
    assert captured.out == ""
    assert "build-stdout-line" in captured.err
    assert "build-stderr-line" in captured.err
    assert "first run" in captured.err

async def test_failed_build_names_the_way_out(tmp_path):
    binary, _ = fake_container(tmp_path, build_exit=3)
    with pytest.raises(RuntimeError, match=r"--image python:3\.13-slim"):
        await ensure_tools_image(binary)

def test_image_defaults_to_the_tools_image():
    assert cli.parser().parse_args([]).image is None
    assert cli.parser().parse_args(["--image", "python:3.13-slim"]).image == "python:3.13-slim"

async def test_explicit_image_skips_the_build(tmp_path):
    binary, log = fake_container(tmp_path)
    args = cli.parser().parse_args(["--image", "custom:1", "--container-bin", binary])
    assert await cli.select_image(args) == "custom:1"
    assert not log.exists()

async def test_default_selection_builds_the_tools_image(tmp_path):
    binary, _ = fake_container(tmp_path)
    args = cli.parser().parse_args(["--container-bin", binary])
    assert await cli.select_image(args) == tools_image_tag()

def test_prepare_image_builds_and_exits(tmp_path, monkeypatch, capsys):
    binary, log = fake_container(tmp_path)
    monkeypatch.setattr("sys.argv", ["external-sandbox-container", "--prepare-image", "--container-bin", binary])
    cli.main()
    assert capsys.readouterr().out.strip() == f"Image ready: {tools_image_tag()}"
    assert "build" in log.read_text()

def test_prepare_image_rejects_an_explicit_image(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["external-sandbox-container", "--prepare-image", "--image", "custom:1"])
    with pytest.raises(SystemExit):
        cli.main()
    assert "--prepare-image" in capsys.readouterr().err

"""Optional compatibility checks against the separately maintained client."""

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def external_streaming_client():
    setting = os.environ.get("EXTERNAL_SANDBOX_CLIENT")
    if not setting:
        pytest.skip("Set EXTERNAL_SANDBOX_CLIENT to the shared external_sandbox_exec.py")
    path = Path(setting).expanduser().resolve()
    if not path.is_file():
        pytest.fail(f"EXTERNAL_SANDBOX_CLIENT does not name a file: {path}")
    return path


@pytest.fixture(autouse=True)
def no_real_image_build(request, monkeypatch):
    """Unit tests must never start a real image build through the CLI default."""
    if request.node.get_closest_marker("integration") or request.path.name == "test_images.py":
        return

    async def refuse(container_bin="container"):
        return "unit-test-image:1"

    monkeypatch.setattr("external_sandbox_container.cli.ensure_tools_image", refuse)

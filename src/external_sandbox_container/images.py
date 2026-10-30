"""Build the development tools image the first time it is needed."""
import asyncio
import hashlib
import sys
import tempfile
from importlib.resources import files
from pathlib import Path

MINIMAL_IMAGE = "python:3.13-slim"


def bundled_recipe() -> bytes:
    return files("external_sandbox_container").joinpath("resources/Containerfile").read_bytes()


def tools_image_tag(recipe: bytes | None = None) -> str:
    digest = hashlib.sha256(bundled_recipe() if recipe is None else recipe).hexdigest()[:12]
    return f"external-sandbox-container-tools:{digest}"


async def _run(*args, **kwargs) -> int:
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL, **kwargs)
    try:
        return await process.wait()
    except BaseException:
        # Interrupting startup must not leave a build running behind the server.
        if process.returncode is None:
            process.kill()
            await process.wait()
        raise


async def ensure_tools_image(container_bin: str = "container") -> str:
    recipe = bundled_recipe()
    tag = tools_image_tag(recipe)
    missing = await _run(container_bin, "image", "inspect", tag,
                         stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    if not missing:
        return tag
    print(f"external-sandbox-container: building {tag} on first run; this needs host network access",
          file=sys.stderr, flush=True)
    with tempfile.TemporaryDirectory(prefix="external-sandbox-container-image-") as context:
        recipe_path = Path(context) / "Containerfile"
        recipe_path.write_bytes(recipe)
        # Clients read the listening event from stdout, so build output goes to stderr.
        status = await _run(container_bin, "build", "--progress", "plain", "--tag", tag,
                            "--file", str(recipe_path), context, stdout=2)
    if status:
        raise RuntimeError(f"Building {tag} failed with status {status}. Check that `container system start` "
                           f"has run and the host has network access, or start without the development tools "
                           f"using --image {MINIMAL_IMAGE}")
    return tag

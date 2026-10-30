"""Export the bundled demo setup without requiring a source checkout."""
from importlib.resources import files
from pathlib import Path


SETUP_FILES = ("Containerfile", "proxy.json")


def write_setup(directory: str | Path) -> Path:
    target = Path(directory).expanduser()
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError(f"Setup destination must be a directory, not a symlink or file: {target}")
    resources = files("external_sandbox_container").joinpath("resources")
    contents = {name: resources.joinpath(name).read_bytes() for name in SETUP_FILES}
    # Preflight every existing file before creating anything. Never replace a
    # user's edited policy or image recipe with a bundled default.
    for name, data in contents.items():
        path = target / name
        if path.is_symlink() or (path.exists() and (not path.is_file() or path.read_bytes() != data)):
            raise ValueError(f"Refusing to overwrite existing setup file: {path}; choose a new directory")
    target.mkdir(parents=True, exist_ok=True)
    for name, data in contents.items():
        path = target / name
        if not path.exists():
            with path.open("xb") as output:
                output.write(data)
    return target.resolve()

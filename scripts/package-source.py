"""Package reviewed backend/build inputs without local credentials or Git data."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    files = []
    for directory in ("app", "alembic", "tests"):
        files.extend(
            path for path in (root / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
            and path.suffix not in (".pyc", ".pyo")
        )
    files.extend(root / name for name in (
        "requirements.txt", "requirements-dev.txt", "pytest.ini", "alembic.ini",
        "Dockerfile.prod", ".dockerignore", "scripts/start-production.sh",
        "infrastructure/buildspec.yml",
    ))
    output = root / "dist/backend-source.zip"
    output.parent.mkdir(exist_ok=True)
    with ZipFile(output, "w", ZIP_DEFLATED) as bundle:
        for path in sorted(files):
            if path.is_symlink():
                raise ValueError(f"Source symlinks are not supported: {path}")
            name = path.relative_to(root).as_posix()
            if any(part.startswith(".env") or part == ".git" for part in path.parts):
                raise ValueError(f"Unexpected sensitive source path: {name}")
            bundle.write(path, name)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(json.dumps({"file": str(output), "sha256": digest, "files": len(files)}))


if __name__ == "__main__":
    main()

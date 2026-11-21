"""Build a source-bound research CLI wheel from the exact committed Git head."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = "docs/operations/RES-747-RESEARCH-CLI.md"
CONFIG = "packaging/research-cli.toml"
PATHS = (
    "src/dynamislm",
    "scripts/__init__.py",
    "scripts/research_cli.py",
    "scripts/a02_v3_contract.py",
    "scripts/a03_scientific_admission.py",
    "scripts/a03_token_decoder.py",
    "LICENSE",
    "NOTICE.md",
    DOC,
    CONFIG,
)


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def canonical(data: object) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


def build(out: Path) -> None:
    commit = git("rev-parse", "HEAD").decode().strip()
    tree = git("rev-parse", f"{commit}^{{tree}}").decode().strip()
    epoch = git("show", "-s", "--format=%ct", commit).decode().strip()
    archive = git("archive", "--format=tar", commit, *PATHS)
    out.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="dynamislm-cli-build-") as temporary:
        source = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(source, filter="data")
        (source / CONFIG).rename(source / "pyproject.toml")
        (source / DOC).rename(source / "RESEARCH-CLI.md")
        files = {
            str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(source.rglob("*"))
            if path.is_file()
        }
        identity = {
            "source_commit": commit,
            "source_tree": tree,
            "source_selection_archive_sha256": hashlib.sha256(archive).hexdigest(),
            "artifact_content_sha256": hashlib.sha256(canonical(files)).hexdigest(),
            "included_source_file_sha256": files,
            "mode": "SYNTHETIC_DETERMINISTIC_CPU",
        }
        (source / "scripts/_research_identity.json").write_bytes(canonical(identity))
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(out)],
            cwd=source,
            env={**os.environ, "SOURCE_DATE_EPOCH": epoch},
            check=True,
        )
    (wheel,) = out.glob("*.whl")
    (out / "build-receipt.json").write_bytes(
        canonical(
            {
                "source_commit": commit,
                "artifact_content_sha256": identity["artifact_content_sha256"],
                "wheel": wheel.name,
                "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="new output directory")
    args = parser.parse_args()
    build(args.out.resolve())


if __name__ == "__main__":
    main()

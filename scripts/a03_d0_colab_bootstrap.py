"""Unpack the sealed D0 input and return a single evidence archive from Colab."""

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path


def main() -> None:
    started = time.monotonic()
    seconds = int(os.environ["D0_SECONDS"])
    expected = os.environ["D0_PROPOSAL"]
    root = Path("/content/d0-work")
    root.mkdir()
    with tarfile.open("/content/d0-input.tar") as archive:
        archive.extractall(root, filter="data")
    if hashlib.sha256((root / "proposal.json").read_bytes()).hexdigest() != expected:
        raise ValueError("remote D0 proposal bytes differ")
    proposal = json.loads((root / "proposal.json").read_bytes())
    with (root / "source.tar").open("rb") as handle:
        if (
            hashlib.file_digest(handle, "sha256").hexdigest()
            != proposal["source"]["archive_sha256"]
        ):
            raise ValueError("remote D0 source archive differs")
    source = root / "source"
    source.mkdir()
    with tarfile.open(root / "source.tar") as archive:
        archive.extractall(source, filter="data")

    def remaining() -> float:
        return max(0.0, seconds - (time.monotonic() - started) - 3)

    try:
        env = {**os.environ, "PYTHONPATH": str(source / "src")}
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path\n"
                "from scripts import a02_remote as r\n"
                "r.WORK.mkdir()\n"
                "r._setup_inference(r._install_uv(), Path.cwd())",
            ],
            cwd=source,
            env=env,
            timeout=min(180, remaining()),
            check=True,
        )
        python = "/content/a02/inference-venv/bin/python"
        subprocess.run(
            [
                "/content/a02/uv-venv/bin/uv",
                "pip",
                "install",
                "--python",
                python,
                "--no-deps",
                "--only-binary=:all:",
                "-r",
                "experiments/a02/training-requirements-v1.txt",
            ],
            cwd=source,
            env=env,
            timeout=min(120, remaining()),
            check=True,
        )
        subprocess.run(
            [
                python,
                "-m",
                "scripts.a03_d0_runtime",
                str(root),
                expected,
                "--seconds",
                str(max(0.0, remaining() - 2)),
            ],
            cwd=source,
            timeout=remaining(),
            check=True,
            env=env,
        )
    finally:
        with tarfile.open("/content/d0-output.tar", "x") as archive:
            for path in (
                root / "runtime.json",
                root / "terminal.json",
                root / "checkpoint.jsonl",
                *sorted(root.glob("divergence-*.json")),
            ):
                if path.is_file():
                    archive.add(path, arcname=path.name)


if __name__ == "__main__":
    main()

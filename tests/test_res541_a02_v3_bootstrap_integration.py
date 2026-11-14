from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

from huggingface_hub import snapshot_download

TOKENIZER = Path("/mnt/e/DynamisLM-A0/a01/tokenizer")

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORTS = [
    "scripts.a02_dev_runtime",
    "scripts.a02_remote",
    "scripts.a02_v3_contract",
    "scripts.a02_v3_decision",
    "scripts.a02_v3_worker",
]


def _run_colab_entrypoint(
    entrypoint: Path,
    content_root: Path,
    *,
    stage: str,
    bootstrap_test: bool,
) -> subprocess.CompletedProcess[str]:
    driver = (
        "from pathlib import Path\n"
        f"entrypoint = Path({str(entrypoint)!r})\n"
        "namespace = {'__name__': '__main__', '__builtins__': __builtins__}\n"
        "exec(compile(entrypoint.read_text(), str(entrypoint), 'exec'), namespace)\n"
    )
    stage_timeout = 660 if stage == "prepare" else 540
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(content_root),
        "PYTHONNOUSERSITE": "1",
        "A02_V3_CONTENT_ROOT": str(content_root),
        "A02_V3_REMOTE_STAGE": stage,
        "A02_V3_REMOTE_STAGE_TIMEOUT": str(stage_timeout),
    }
    if bootstrap_test:
        environment["A02_V3_BOOTSTRAP_TEST"] = "1"
        environment["A02_V3_CPU_TOKENIZER"] = str(TOKENIZER)
    assert "PYTHONPATH" not in environment
    assert "PYTHONHOME" not in environment
    return subprocess.run(
        [sys.executable, "-c", driver],
        cwd=content_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=stage_timeout + 30,
        check=False,
    )


def _binding(archive: Path, commit: str, tree: str) -> dict[str, Any]:
    with tarfile.open(archive) as source:
        protocol = source.extractfile("experiments/a02/model-comparison-protocol-v3.json")
        assert protocol is not None
        protocol_sha256 = hashlib.sha256(protocol.read()).hexdigest()
    return {
        "schema": "RES541_A02_V3_REMOTE_BINDING_V1",
        "source_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "source_revision": commit,
        "source_identity": {"commit": commit, "tree": tree},
        "plan_sha256": hashlib.sha256(b"synthetic CPU bootstrap plan").hexdigest(),
        "protocol_sha256": protocol_sha256,
        "session_index": 1,
        "item_cost_bounds": {
            "QUALIFICATION": 1,
            "ZERO_SHOT_CONSTRAINED": 1,
            "ZERO_SHOT_UNCONSTRAINED": 1,
        },
    }


def _assert_stage(
    status: dict[str, Any], binding: dict[str, Any], stage: str, source_root: Path
) -> None:
    bootstrap = status["bootstrap_test"]
    assert status["binding"] == {**binding, "session_index": 1}
    assert bootstrap["stage"] == stage
    assert bootstrap["child_stage"] == stage
    assert bootstrap["cwd"] == str(source_root)
    assert bootstrap["pythonpath"] == f"{source_root}:{source_root}/src"
    assert bootstrap["source_revision"] == binding["source_revision"]
    assert bootstrap["source_archive_sha256"] == binding["source_archive_sha256"]
    assert bootstrap["imports"] == IMPORTS
    assert bootstrap["torch_imported"] is False
    assert bootstrap["transformers_imported"] is True
    assert status["cpu_rehearsal"]["items"] == 581
    assert status["cpu_rehearsal"]["actual_model_evaluations"] == 0
    assert Path(bootstrap["python_executable"]).resolve() == Path(sys.executable).resolve()


def test_colab_archive_prepare_and_work_use_real_bounded_child(tmp_path: Path) -> None:
    global TOKENIZER
    if not TOKENIZER.is_dir():
        TOKENIZER = Path(
            snapshot_download(
                repo_id="HuggingFaceTB/SmolLM3-3B",
                revision="a07cc9a04f16550a088caea529712d1d335b0ac1",
                allow_patterns=["tokenizer*", "special_tokens_map.json", "chat_template.jinja"],
            )
        )
    repo = REPO_ROOT
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=repo, text=True).strip()
    archive = tmp_path / "source.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", f"--output={archive}", commit],
        cwd=repo,
        check=True,
    )
    with tarfile.open(archive) as source:
        entrypoint_member = source.extractfile("scripts/a02_v3_remote.py")
        assert entrypoint_member is not None
        entrypoint = tmp_path / "uploaded-a02-v3-remote.py"
        entrypoint.write_bytes(entrypoint_member.read())

    content_root = tmp_path / "content"
    content_root.mkdir()
    remote_archive = content_root / "a02-v3-source.tar"
    remote_archive.write_bytes(archive.read_bytes())
    binding = _binding(remote_archive, commit, tree)
    (content_root / "a02-v3-binding.json").write_text(json.dumps(binding))
    python = content_root / "a02/inference-venv/bin/python"
    python.parent.mkdir(parents=True)
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(python.parent.parent)],
        check=True,
    )
    project_site = subprocess.check_output(
        [sys.executable, "-c", "import site; print(site.getsitepackages()[0])"],
        text=True,
    ).strip()
    child_site = subprocess.check_output(
        [str(python), "-c", "import site; print(site.getsitepackages()[0])"],
        text=True,
    ).strip()
    (Path(child_site) / "res541-test-site.pth").write_text(project_site + "\n")

    # Negative control: the original work boundary cannot import from an empty prepared tree.
    negative_root = tmp_path / "negative-content"
    negative_root.mkdir()
    (negative_root / "a02-v3-source.tar").write_bytes(archive.read_bytes())
    (negative_root / "a02-v3-binding.json").write_text(json.dumps(binding))
    (negative_root / "a02/v3-source").mkdir(parents=True)
    (negative_root / "a02-v3-status.json").write_text(
        json.dumps({"status": "READY", "plan_sha256": binding["plan_sha256"], "binding": binding})
    )
    negative = _run_colab_entrypoint(entrypoint, negative_root, stage="work", bootstrap_test=False)
    assert negative.returncode != 0
    failure = json.loads((negative_root / "a02-v3-status.json").read_text())
    assert failure["error_type"] == "ModuleNotFoundError"
    assert failure["error_detail"] == "No module named 'scripts'"

    prepare = _run_colab_entrypoint(entrypoint, content_root, stage="prepare", bootstrap_test=True)
    assert prepare.returncode == 0, prepare.stderr
    status_path = content_root / "a02-v3-status.json"
    prepared = json.loads(status_path.read_text())
    assert prepared["status"] == "BOOTSTRAP_TEST_READY"
    extracted = content_root / "a02/v3-source"
    _assert_stage(prepared, binding, "prepare", extracted)
    assert (extracted / "scripts/__init__.py").is_file()
    assert (extracted / "scripts/a02_v3_remote.py").read_bytes() == entrypoint.read_bytes()

    work = _run_colab_entrypoint(entrypoint, content_root, stage="work", bootstrap_test=True)
    assert work.returncode == 0, work.stderr
    completed = json.loads(status_path.read_text())
    assert completed["status"] == "BOOTSTRAP_TEST_COMPLETE"
    _assert_stage(completed, binding, "work", extracted)
    assert [stage["stage"] for stage in completed["stages"]] == ["prepare", "work"]


def test_session_002_exact_archive_reproduces_git_root_failure(tmp_path: Path) -> None:
    archive = tmp_path / "session-002.tar"
    subprocess.run(
        [
            "git",
            "archive",
            "--format=tar",
            f"--output={archive}",
            "ffad2a8ec58392b026f97a5cb0d724a8f1213d5a",
        ],
        cwd=REPO_ROOT,
        check=True,
    )
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == (
        "9512e261d2ee19c9767837f32fc8e549a05d6554d36e258bfe49260f9cbc63ad"
    )
    extracted = tmp_path / "source"
    extracted.mkdir()
    with tarfile.open(archive) as source:
        source.extractall(extracted, filter="data")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from scripts.a02_v3_contract import build_tool_schema; build_tool_schema()",
        ],
        cwd=extracted,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": f"{extracted}:{extracted}/src",
        },
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert "mendeley_rpl.py" in result.stderr
    assert "could not resolve a Git repository root" in result.stderr

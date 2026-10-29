from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
from scripts import repository_policy as policy
from scripts.repository_policy import (
    MAX_FIXTURE_SIZE_BYTES,
    evaluate_paths,
    tracked_path_sizes,
)


def test_forbidden_dataset_path_is_rejected() -> None:
    assert evaluate_paths((("datasets/foo.parquet", 1),)) == (
        "FORBIDDEN_PATH=datasets/foo.parquet",
    )


def test_forbidden_data_path_rejects_csv() -> None:
    assert evaluate_paths((("data/foo.csv", 1),)) == ("FORBIDDEN_PATH=data/foo.csv",)


def test_model_weights_are_rejected() -> None:
    assert evaluate_paths((("model-weights/model.safetensors", 1),)) == (
        "FORBIDDEN_PATH=model-weights/model.safetensors",
    )


def test_bin_model_or_data_file_is_rejected() -> None:
    assert evaluate_paths((("model.bin", 1),)) == ("FORBIDDEN_EXTENSION=model.bin",)


def test_nested_bin_model_or_data_file_is_rejected() -> None:
    assert evaluate_paths((("weights/model.bin", 1),)) == ("FORBIDDEN_EXTENSION=weights/model.bin",)


def test_env_file_is_rejected() -> None:
    assert evaluate_paths(((".env", 1),)) == ("SECRET_LIKE_FILE=.env",)


def test_env_example_is_explicitly_permitted() -> None:
    assert evaluate_paths(((".env.example", 1),)) == ()


def test_allowlisted_synthetic_csv_within_size_limit_passes() -> None:
    path = "tests/fixtures/synthetic/example.csv"
    assert evaluate_paths(((path, MAX_FIXTURE_SIZE_BYTES),), allowlisted_fixtures=(path,)) == ()


def test_synthetic_csv_without_allowlist_is_rejected() -> None:
    path = "tests/fixtures/synthetic/example.csv"
    assert evaluate_paths(((path, 1),)) == (f"UNALLOWLISTED_FIXTURE={path}",)


def test_allowlisted_synthetic_csv_over_size_limit_is_rejected() -> None:
    path = "tests/fixtures/synthetic/example.csv"
    assert evaluate_paths(
        ((path, MAX_FIXTURE_SIZE_BYTES + 1),),
        allowlisted_fixtures=(path,),
    ) == (f"OVERSIZED_FIXTURE={path}",)


def test_allowlisted_synthetic_tab_within_size_limit_passes() -> None:
    path = "tests/fixtures/synthetic/source-a/source-a.tab"
    assert evaluate_paths(((path, MAX_FIXTURE_SIZE_BYTES),), allowlisted_fixtures=(path,)) == ()


def test_real_tab_outside_synthetic_fixture_root_is_rejected() -> None:
    path = "source.tab"
    assert evaluate_paths(((path, 1),), allowlisted_fixtures=(path,)) == (
        f"UNALLOWLISTED_FIXTURE={path}",
    )


def test_public_dataset_registry_json_is_narrowly_permitted() -> None:
    path = "registries/datasets/source.json"
    assert evaluate_paths(((path, 1),)) == ()


def test_dataset_registry_tab_is_not_permitted_as_real_data() -> None:
    path = "registries/datasets/source.tab"
    assert evaluate_paths(((path, 1),)) == (f"FORBIDDEN_PATH={path}",)


def test_ordinary_source_files_pass() -> None:
    assert (
        evaluate_paths(
            (
                ("docs/example.md", 1),
                ("pyproject.toml", 1),
                ("src/example.py", 1),
            )
        )
        == ()
    )


def test_existing_tracked_repository_passes_live_policy() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    allowlisted_fixture = "tests/fixtures/synthetic/source-a/source-a.tab"
    assert (
        evaluate_paths(
            tracked_path_sizes(repo_root),
            allowlisted_fixtures=(allowlisted_fixture,),
        )
        == ()
    )


@pytest.mark.parametrize(
    "path",
    [
        "notebooks/run.ipynb",
        ".cache/snapshot.json",
        "DATA/rows.json",
        "research/rows.jsonl",
        "weights/model.gguf",
        "credentials.json",
        "cache/secret.key",
        "src/__pycache__/run.pyc",
        "x/model.onnx",
        "research/rows.ndjson",
    ],
)
def test_additional_artifacts_are_rejected(path: str) -> None:
    assert evaluate_paths(((path, 10),))


def test_all_files_have_a_size_limit() -> None:
    assert evaluate_paths((("research/large.pdf", MAX_FIXTURE_SIZE_BYTES + 1),))


def _stage(root: Path, *paths: str) -> None:
    subprocess.run(["git", "add", "--", *paths], cwd=root, check=True, capture_output=True)


@pytest.fixture
def policy_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "docs/decisions").mkdir(parents=True)
    (tmp_path / ".repo-policy").mkdir()
    evidence = "docs/decisions/synthetic-authority.md"
    (tmp_path / evidence).write_text("Synthetic immutable authority\n")
    inventory = tmp_path / policy.INVENTORY
    inventory.write_text(
        "path\tclassification\tsha256\treason\n"
        f"{policy.INVENTORY}\tconfiguration\t-\tAdmission list\n"
        f"{evidence}\tauthority\t"
        f"{hashlib.sha256((tmp_path / evidence).read_bytes()).hexdigest()}"
        "\tSynthetic baseline evidence\n"
    )
    _stage(tmp_path, ".")
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "synthetic baseline",
        ],
        cwd=tmp_path,
        check=True,
    )
    baseline = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    monkeypatch.setattr(policy, "BASELINE", baseline)
    return tmp_path


def test_clean_synthetic_policy_repo_passes(policy_repo: Path) -> None:
    assert policy.repository_failures(policy_repo) == ()


def test_staged_secret_cannot_hide_behind_clean_working_bytes(policy_repo: Path) -> None:
    path = policy_repo / "innocent.py"
    path.write_text('secret = "' + "ghp_" + "X" * 36 + '"\n')
    _stage(policy_repo, "innocent.py")
    path.write_text("# clean replacement after staging\n")
    failures = policy.repository_failures(policy_repo)
    assert "SECRET_CONTENT=innocent.py" in failures
    assert "INDEX_WORKTREE_MISMATCH=innocent.py" in failures
    tree = subprocess.check_output(["git", "write-tree"], cwd=policy_repo, text=True).strip()
    assert "SECRET_CONTENT=innocent.py" in policy.repository_failures(policy_repo, tree)


def test_uninventoried_research_json_is_rejected(policy_repo: Path) -> None:
    (policy_repo / "uncontrolled.json").write_text('{"synthetic": true}\n')
    _stage(policy_repo, "uncontrolled.json")
    assert "NONCODE_INVENTORY_MISMATCH" in policy.repository_failures(policy_repo)


def test_evidence_cannot_be_rehashed_to_obtain_pass(policy_repo: Path) -> None:
    path = policy_repo / "docs/decisions/synthetic-authority.md"
    old_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_text("Altered synthetic authority\n")
    inventory = policy_repo / policy.INVENTORY
    inventory.write_text(
        inventory.read_text().replace(old_digest, hashlib.sha256(path.read_bytes()).hexdigest())
    )
    _stage(policy_repo, ".")
    failures = policy.repository_failures(policy_repo)
    assert "BASELINE_EVIDENCE_CHANGED=docs/decisions/synthetic-authority.md" in failures
    assert "BASELINE_EVIDENCE_UNPINNED=docs/decisions/synthetic-authority.md" in failures


def test_deleted_evidence_is_rejected(policy_repo: Path) -> None:
    (policy_repo / "docs/decisions/synthetic-authority.md").unlink()
    _stage(policy_repo, ".")
    assert "BASELINE_EVIDENCE_CHANGED=docs/decisions/synthetic-authority.md" in (
        policy.repository_failures(policy_repo)
    )


def test_symlinks_and_binary_code_disguise_are_rejected(policy_repo: Path) -> None:
    (policy_repo / "link.py").symlink_to("/etc/passwd")
    (policy_repo / "binary.py").write_bytes(b"synthetic\0data")
    _stage(policy_repo, "link.py", "binary.py")
    failures = policy.repository_failures(policy_repo)
    assert "NON_REGULAR_OR_UNMERGED_FILE=link.py" in failures
    assert "BINARY_FILE=binary.py" in failures


def test_authority_cannot_be_downgraded_in_inventory(policy_repo: Path) -> None:
    inventory = policy_repo / policy.INVENTORY
    inventory.write_text(inventory.read_text().replace("\tauthority\t", "\tdocumentation\t"))
    _stage(policy_repo, ".")
    assert "UNCLASSIFIED_OR_UNPINNED_AUTHORITY=docs/decisions/synthetic-authority.md" in (
        policy.repository_failures(policy_repo)
    )


def test_registry_exception_cannot_admit_nested_cache_or_dataset_paths() -> None:
    for path in ("registries/datasets/.cache/file.json", "registries/datasets/data/rows.json"):
        assert evaluate_paths(((path, 1),)) == (f"FORBIDDEN_PATH={path}",)

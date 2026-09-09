from __future__ import annotations

from pathlib import Path

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
    assert evaluate_paths(tracked_path_sizes(repo_root)) == ()

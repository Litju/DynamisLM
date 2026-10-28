"""Synthetic CPU falsification of runtime authority; never allocates compute."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a01_protocol as protocol
from scripts import a01_runtime as runtime


def observed() -> dict[str, Any]:
    spec = dict(runtime.PROFILE["requirements"])
    spec.pop("python_final_release_pattern")
    return dict(
        spec,
        python="3.13.16",
        python_build=["synthetic", "synthetic"],
        python_compiler="synthetic",
        python_full_version="synthetic",
        python_executable="/synthetic/python",
        gpu_uuid="synthetic",
        driver_inventory="synthetic",
        total_vram_bytes=15 * 1024**3,
    )


def activate(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = copy.deepcopy(runtime.PROFILE)
    profile.update(
        active=True,
        approved_python_patches=list(profile["candidate_python_patches"]),
        independent_review={"identity": "synthetic-reviewer", "evidence": "synthetic-review"},
        owner_approval={"identity": "synthetic-owner", "evidence": "synthetic-approval"},
    )
    monkeypatch.setattr(runtime, "PROFILE", profile)


def test_shipped_profile_has_attributed_automated_review_and_owner_consent() -> None:
    assert runtime.PROFILE["active"] is True
    assert runtime.PROFILE["approved_python_patches"] == runtime.PROFILE[
        "candidate_python_patches"
    ]
    assert runtime.PROFILE["independent_review"]["identity"] == "coderabbitai[bot]"
    assert "pullrequestreview-5677323707" in runtime.PROFILE["independent_review"]["evidence"]
    assert runtime.PROFILE["owner_approval"]["identity"] == "Litju"
    assert "issuecomment-6458914435" in runtime.PROFILE["owner_approval"]["evidence"]
    runtime.require_approval()
    runtime.qualify(observed())


@pytest.mark.parametrize(
    "change",
    [
        {"python": "3.14.0"},
        {"python": "3.13.16rc1"},
        {"python": "3.13.016"},
        {"python": None},
        {"implementation": "PyPy"},
        {"soabi": None},
        {"gil_disabled": True},
        {"gil_enabled": None},
        {"debug_build": True},
        {"torch": "2.11.1+cu130"},
        {"torch_cuda_runtime": "12.8"},
        {"gpu_name": "A100"},
        {"device_count": True},
        {"device_count": 2},
        {"compute_capability": [8, 0]},
        {"weight_dtype": "bfloat16"},
        {"python_build": []},
        {"driver_inventory": ""},
        {"inventory_error": "OSError"},
        {"python": "3.13.14"},
        {"python": "3.13.19"},
        {"python": "3.12.13"},
        {"python": "3.13.18rc1"},
        {"torch": "2.11.0"},
        {"torch": "2.11.0+cu128"},
        {"soabi": "cpython-313t-x86_64-linux-gnu"},
        {"gil_disabled": None},
        {"debug_build": None},
        {"total_vram_bytes": True},
    ],
)
def test_incompatible_runtime(change: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    with pytest.raises(ValueError):
        runtime.qualify({**observed(), **change})


@pytest.mark.parametrize(
    "field", ["active", "approved_python_patches", "independent_review", "owner_approval"]
)
def test_missing_approval(field: str, monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    runtime.PROFILE[field] = None
    with pytest.raises(ValueError):
        runtime.require_approval()


def test_independent_identity_and_inventory_agreement(monkeypatch: pytest.MonkeyPatch) -> None:
    activate(monkeypatch)
    runtime.agree(observed(), {**observed(), "python_executable": "/synthetic/venv/python"})
    with pytest.raises(ValueError, match="mismatch"):
        runtime.agree(observed(), {**observed(), "python_build": ["other", "synthetic"]})
    runtime.PROFILE["owner_approval"]["identity"] = "synthetic-reviewer"
    with pytest.raises(ValueError):
        runtime.require_approval()


@pytest.mark.parametrize(
    "name,function", [("a0_colab_entry", "_preflight"), ("a0_colab_inference", "run_inference")]
)
def test_both_private_gates_are_audited(name: str, function: str) -> None:
    module = protocol.isolated_a0(name)
    source = (protocol.ROOT / "scripts" / (name + ".py")).read_bytes()
    original = getattr(module, function)
    runtime.adapt_gate(module, name, source, lambda: True)
    assert getattr(module, function) is not original
    assert "_a01_runtime_check" in getattr(module, function).__code__.co_names
    with pytest.raises(ValueError, match="SHA-256"):
        runtime.adapt_gate(module, name, source + b"\n", lambda: True)


def test_immutable_report(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    runtime.immutable(path, observed())
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        runtime.immutable(path, {})
    assert path.read_bytes() == before


def test_missing_review_stops_before_host_or_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import a0_colab
    from scripts import a01_execution as execution

    profile = copy.deepcopy(runtime.PROFILE)
    profile["independent_review"] = None
    monkeypatch.setattr(runtime, "PROFILE", profile)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("missing review must not touch host setup or transport")

    monkeypatch.setattr(a0_colab, "_prepare_host_storage", forbidden)
    with pytest.raises(ValueError, match="inactive"):
        execution.run("a0_diagnostic", 16, Path("unused"), Path("unused"))


@pytest.mark.parametrize("name", ["a0_colab_entry", "a0_colab_inference"])
@pytest.mark.parametrize("python_patch", ["3.13.15", "3.13.16", "3.13.17", "3.13.18"])
@pytest.mark.parametrize("failure", [None, "python", "torch", "cuda"])
def test_executed_gates_keep_torch_and_cuda_guards(
    name: str, python_patch: str, failure: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ast
    import sys
    from types import SimpleNamespace

    activate(monkeypatch)
    sample = {**observed(), "python": python_patch}
    if failure == "python":
        sample["python"] = "3.14.0"
    if failure == "cuda":
        sample["torch_cuda_runtime"] = "12.0"

    def check() -> bool:
        runtime.qualify(sample)
        return True

    module = protocol.isolated_a0(name)
    source = (protocol.ROOT / "scripts" / (name + ".py")).read_bytes()
    runtime.adapt_gate(module, name, source, check)
    fake_torch = SimpleNamespace(
        version=SimpleNamespace(cuda="13.0"),
        __version__="wrong" if failure == "torch" else "2.11.0+cu130",
        cuda=SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            get_device_properties=lambda _: SimpleNamespace(
                name="Tesla T4", total_memory=15 * 1024**3
            ),
            get_device_capability=lambda _: (7, 5),
            mem_get_info=lambda _: (10 * 1024**3, 15 * 1024**3),
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    if name == "a0_colab_entry":
        monkeypatch.setattr(
            module,
            "shutil",
            SimpleNamespace(disk_usage=lambda _: SimpleNamespace(free=20 * 1024**3)),
        )
        if failure:
            with pytest.raises((ValueError, module.A0Error)):
                module._preflight()
        else:
            assert module._preflight()[1]["python"] == module.platform.python_version()
        return

    class BeforeDownloadError(Exception):
        pass

    def stop() -> Any:
        raise BeforeDownloadError

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=stop))
    monkeypatch.setitem(
        sys.modules, "transformers", SimpleNamespace(AutoModelForCausalLM=None, AutoTokenizer=None)
    )
    expected = next(
        n.value
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "expected_packages" for t in n.targets)
    )
    module.__dict__["_package_versions"] = lambda: ast.literal_eval(expected)
    module.__dict__["_load_prepared"] = lambda _: []
    with pytest.raises((ValueError, RuntimeError) if failure else BeforeDownloadError):
        module.run_inference(Path("unused"), Path("unused"))


def test_inventory_records_partial_failure_without_installing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import platform
    import sys
    from types import SimpleNamespace

    def unavailable() -> Any:
        raise RuntimeError("synthetic missing GPU")

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            __version__="synthetic",
            version=SimpleNamespace(cuda=None),
            cuda=SimpleNamespace(device_count=unavailable),
        ),
    )
    actual = runtime.inventory()
    assert actual["python"] == platform.python_version()
    assert actual["python_build"] == list(platform.python_build())
    assert actual["python_full_version"] == sys.version
    assert actual["torch"] == "synthetic" and actual["torch_cuda_runtime"] is None
    assert actual["inventory_error"] == "RuntimeError"
    with pytest.raises(ValueError):
        runtime.qualify(actual, approved=False)


@pytest.mark.parametrize("python_patch", ["3.13.15", "3.13.16", "3.13.17", "3.13.18"])
def test_approved_patches_still_require_exact_runtime(
    python_patch: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert runtime.PROFILE["candidate_python_patches"] == [
        "3.13.15",
        "3.13.16",
        "3.13.17",
        "3.13.18",
    ]
    assert runtime.PROFILE["approved_python_patches"] == runtime.PROFILE[
        "candidate_python_patches"
    ]
    sample = {**observed(), "python": python_patch}
    runtime.qualify(sample)
    activate(monkeypatch)
    serialized = json.loads(json.dumps(sample))
    runtime.qualify(serialized)
    runtime.agree(serialized, {**serialized, "python_executable": "/synthetic/venv/python"})
    runtime.PROFILE["approved_python_patches"].remove(python_patch)
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        runtime.qualify(serialized)


@pytest.mark.parametrize("python_patch", ["3.13.14", "3.13.19", "3.14.0"])
def test_outside_candidate_set_cannot_be_screened_or_approved(
    python_patch: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        runtime.qualify({**observed(), "python": python_patch}, approved=False)
    activate(monkeypatch)
    runtime.PROFILE["approved_python_patches"].append(python_patch)
    with pytest.raises(ValueError, match="approval"):
        runtime.require_approval()


def test_actual_inventory_is_json_native(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            __version__="2.11.0+cu130",
            version=SimpleNamespace(cuda="13.0"),
            cuda=SimpleNamespace(
                device_count=lambda: 1,
                get_device_properties=lambda _: SimpleNamespace(
                    name="Tesla T4", uuid="synthetic-uuid", total_memory=15 * 1024**3
                ),
                get_device_capability=lambda _: (7, 5),
            ),
        ),
    )
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "synthetic-driver\n")
    actual = runtime.inventory()
    assert "inventory_error" not in actual
    assert json.loads(json.dumps(actual)) == actual
    assert isinstance(actual["python_build"], list)
    assert actual["compute_capability"] == [7, 5]
    assert actual["python_full_version"] == sys.version

from __future__ import annotations

import importlib.metadata
import site
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import a02_dev_runtime


def _inventory() -> dict[str, Any]:
    return {
        "python": {
            "version": "3.13.18",
            "implementation": "CPython",
            "full_version": "CPython 3.13.18",
            "system": "Linux",
            "machine": "x86_64",
            "soabi": "cpython-313-x86_64-linux-gnu",
            "extension_suffix": ".cpython-313-x86_64-linux-gnu.so",
        },
        "torch": {
            "version": "2.11.0+cu130",
            "distribution_version": "2.11.0+cu130",
            "cuda_runtime": "13.0",
            "module_origin": "/system/torch/__init__.py",
            "distribution_origin": "/system",
            "extension_origin": "/system/torch/_C.cpython-313-x86_64-linux-gnu.so",
            "inference_site": "/inference",
            "inherited_system_sites": ["/system"],
            "cxx11_abi": True,
        },
        "cuda": {
            "available": True,
            "device_count": 1,
            "name": "Tesla T4",
            "uuid": "GPU-synthetic",
            "compute_capability": [7, 5],
            "total_vram_bytes": 16 * 1024**3,
            "free_vram_bytes": 10 * 1024**3,
            "allocated_vram_bytes": 0,
            "reserved_vram_bytes": 0,
        },
        "driver_inventory": "GPU-synthetic, driver 999.1, Tesla T4",
        "inventory_errors": {},
    }


def test_runtime_policy_is_versioned_and_bound() -> None:
    binding = a02_dev_runtime.policy_binding()

    assert a02_dev_runtime.POLICY["schema"] == "RES541_A02_RUNTIME_POLICY_V1"
    assert binding["runtime_policy_id"] == a02_dev_runtime.POLICY["id"]
    assert len(binding["runtime_policy_sha256"]) == 64


def test_qualification_accepts_capability_checks_and_records_unchecked_versions() -> None:
    observed = _inventory()
    decision = a02_dev_runtime.qualify(
        observed,
        {"attempted": True, "passed": True, "observed": "all 256 FP16 outputs equal 16"},
    )
    changed_provenance = _inventory()
    changed_provenance["python"].update(
        full_version="a different build string",
        executable="/different/python",
        compiler="a different compiler",
    )
    changed_provenance["torch"].update(
        version="2.12.0+cu131",
        distribution_version="2.12.0+cu131",
        cuda_runtime="13.1",
    )
    changed_provenance["cuda"].update(uuid="GPU-another-T4")
    changed_provenance["driver_inventory"] = "a different driver string"
    changed = a02_dev_runtime.qualify(
        changed_provenance,
        {"attempted": True, "passed": True, "observed": "all 256 FP16 outputs equal 16"},
    )

    assert decision["qualified"] is True
    assert changed["qualified"] is True
    assert decision["failed_requirements"] == []
    assert changed["provenance_only"]["torch_version"] == "2.12.0+cu131"
    assert changed["provenance_only"]["gpu_uuid"] == "GPU-another-T4"


@pytest.mark.parametrize(
    ("name", "change"),
    [
        ("system", lambda row: row["python"].update(system="Darwin")),
        ("machine", lambda row: row["python"].update(machine="aarch64")),
        (
            "python_implementation",
            lambda row: row["python"].update(implementation="PyPy"),
        ),
        ("python_minor", lambda row: row["python"].update(version="3.12.9")),
        (
            "python_final_release",
            lambda row: row["python"].update(version="3.13.18rc1"),
        ),
        ("python_soabi", lambda row: row["python"].update(soabi="cpython-312-x86_64-linux-gnu")),
        (
            "torch_distribution_version",
            lambda row: row["torch"].update(distribution_version="2.10.0+cu130"),
        ),
        (
            "torch_module_origin",
            lambda row: row["torch"].update(module_origin="/other/torch.py"),
        ),
        (
            "torch_inherited_origin",
            lambda row: row["torch"].update(distribution_origin="/inference/torch"),
        ),
        (
            "torch_python_abi",
            lambda row: row["torch"].update(extension_origin="/system/torch/_C.cpython-312.so"),
        ),
        ("torch_cuda_runtime", lambda row: row["torch"].update(cuda_runtime=None)),
        ("cuda_available", lambda row: row["cuda"].update(available=False)),
        ("cuda_device_count", lambda row: row["cuda"].update(device_count=2)),
        ("gpu_name", lambda row: row["cuda"].update(name="Tesla A100")),
        (
            "compute_capability",
            lambda row: row["cuda"].update(compute_capability=[8, 0]),
        ),
        (
            "total_vram_bytes",
            lambda row: row["cuda"].update(total_vram_bytes=11 * 1024**3),
        ),
        (
            "free_vram_bytes",
            lambda row: row["cuda"].update(free_vram_bytes=7 * 1024**3),
        ),
    ],
)
def test_each_runtime_requirement_fails_with_expected_and_observed_values(
    name: str, change: Any
) -> None:
    observed = _inventory()
    change(observed)

    decision = a02_dev_runtime.qualify(
        observed, {"attempted": True, "passed": True, "observed": "ok"}
    )
    failures = {failure["name"]: failure for failure in decision["failed_requirements"]}

    assert decision["qualified"] is False
    assert name in failures
    assert "expected" in failures[name]
    assert "observed" in failures[name]


def test_cuda_smoke_is_an_independent_compatibility_requirement() -> None:
    decision = a02_dev_runtime.qualify(
        _inventory(),
        {"attempted": True, "passed": False, "observed": "CUDA error: illegal instruction"},
    )

    failure = next(item for item in decision["failed_requirements"] if item["name"] == "cuda_smoke")
    assert failure["expected"] == "synchronized_fp16_16x16_matmul"
    assert failure["observed"] == "CUDA error: illegal instruction"


class _Scalar:
    def item(self) -> bool:
        return True


class _Tensor:
    def __matmul__(self, other: _Tensor) -> _Tensor:
        return other

    def __eq__(self, other: object) -> bool:
        assert other == 16
        return True


def test_cuda_smoke_runs_fp16_matmul_and_synchronizes() -> None:
    calls: list[Any] = []

    def ones(shape: tuple[int, int], *, dtype: str, device: str) -> _Tensor:
        calls.append((shape, dtype, device))
        return _Tensor()

    def all_values(result: bool) -> _Scalar:
        calls.append(result)
        return _Scalar()

    torch = SimpleNamespace(
        float16="float16",
        ones=ones,
        all=all_values,
        cuda=SimpleNamespace(synchronize=lambda device: calls.append(("sync", device))),
    )

    result = a02_dev_runtime.cuda_smoke(torch, _inventory())

    assert result == {
        "attempted": True,
        "passed": True,
        "observed": "all 256 FP16 outputs equal 16",
    }
    assert calls == [((16, 16), "float16", "cuda"), ("sync", 0), True]


def test_runtime_qualification_error_preserves_field_level_diagnostics() -> None:
    observed = _inventory()
    observed["cuda"]["free_vram_bytes"] = 0
    decision = a02_dev_runtime.qualify(
        observed, {"attempted": True, "passed": True, "observed": "ok"}
    )

    with pytest.raises(a02_dev_runtime.RuntimeQualificationError) as caught:
        raise a02_dev_runtime.RuntimeQualificationError(decision)

    assert "free_vram_bytes" in str(caught.value)
    assert "expected" in str(caught.value)
    assert "observed" in str(caught.value)


def test_inventory_records_python_torch_cuda_driver_and_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distribution = SimpleNamespace(
        version="2.11.0+cu130", locate_file=lambda _name: Path("/system")
    )
    props = SimpleNamespace(name="Tesla T4", uuid="GPU-synthetic")
    torch = SimpleNamespace(
        __version__="2.11.0+cu130",
        __file__="/system/torch/__init__.py",
        version=SimpleNamespace(cuda="13.0"),
        _C=SimpleNamespace(
            __file__="/system/torch/_C.cpython-313-x86_64-linux-gnu.so",
            _GLIBCXX_USE_CXX11_ABI=True,
        ),
        cuda=SimpleNamespace(
            is_available=lambda: True,
            device_count=lambda: 1,
            get_device_properties=lambda _index: props,
            get_device_capability=lambda _index: (7, 5),
            mem_get_info=lambda _index: (10 * 1024**3, 16 * 1024**3),
            memory_allocated=lambda _index: 64,
            memory_reserved=lambda _index: 128,
        ),
    )
    monkeypatch.setattr(importlib.metadata, "distribution", lambda _name: distribution)
    monkeypatch.setattr(site, "getsitepackages", lambda: ["/system", "/inference"])
    monkeypatch.setattr(
        subprocess,
        "check_output",
        lambda *_args, **_kwargs: "GPU-synthetic, 999.1, Tesla T4, 16384, 10240, 7.5",
    )

    observed = a02_dev_runtime.inventory(torch, Path("/inference"))

    assert observed["torch"]["version"] == "2.11.0+cu130"
    assert observed["torch"]["module_origin"] == "/system/torch/__init__.py"
    assert observed["torch"]["extension_origin"].endswith(".cpython-313-x86_64-linux-gnu.so")
    assert observed["torch"]["cxx11_abi"] is True
    assert observed["cuda"]["free_vram_bytes"] == 10 * 1024**3
    assert observed["cuda"]["allocated_vram_bytes"] == 64
    assert observed["driver_inventory"].startswith("GPU-synthetic")

from __future__ import annotations

import pytest
from scripts.res71_reference_cases import VERIFIER_REFERENCE_INTERFACE, main

from dynamislm.qualification import (
    RES71_SEALED_REFERENCE_DIGEST,
    reference_case_digest,
    reference_case_manifest,
)

SEALED_REFERENCE_DIGEST = "sha256:d29d84699b7cf70c2d409d370c5ffd6c7ad7cd704375b14b541527a95fa385e5"


def test_verifier_reference_adapter_emits_the_registered_digest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert VERIFIER_REFERENCE_INTERFACE == "res71-reference-interface@1.0.0"
    assert main(["--digest"]) == 0
    digest = reference_case_digest()
    assert digest == SEALED_REFERENCE_DIGEST
    assert digest == RES71_SEALED_REFERENCE_DIGEST
    assert capsys.readouterr().out.strip() == SEALED_REFERENCE_DIGEST


def test_verifier_reference_adapter_emits_canonical_manifest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--manifest"]) == 0
    assert capsys.readouterr().out.strip() == reference_case_manifest()

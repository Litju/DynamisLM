from __future__ import annotations

import pytest
from scripts.res71_reference_cases import VERIFIER_REFERENCE_INTERFACE, main

from dynamislm.qualification import reference_case_digest, reference_case_manifest


def test_verifier_reference_adapter_emits_the_registered_digest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert VERIFIER_REFERENCE_INTERFACE == "res71-reference-interface@1.0.0"
    assert main(["--digest"]) == 0
    assert capsys.readouterr().out.strip() == reference_case_digest()


def test_verifier_reference_adapter_emits_canonical_manifest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--manifest"]) == 0
    assert capsys.readouterr().out.strip() == reference_case_manifest()

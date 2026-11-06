from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from scripts import a02_dev_execution, a02_execution


def test_run_refuses_missing_one_time_authorization_before_colab_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a02_dev_execution, "AUTHORIZATION_PATH", tmp_path / "authorization.json")
    monkeypatch.setattr(
        a02_execution,
        "_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Colab must not be called")),
    )

    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="one-time V2 campaign"):
        a02_dev_execution.run_campaign_session()


@pytest.mark.parametrize(
    ("remaining", "rate", "expected"),
    [
        (2.0, 4.0, 720),
        (1.0, 8.0, 337),
        (0.2, 10.0, 0),
    ],
)
def test_exec_bound_respects_remaining_cu_budget(
    remaining: float, rate: float, expected: int
) -> None:
    assert a02_dev_execution._safe_exec_seconds(remaining, rate) == expected


def test_exec_bound_fails_closed_on_unknown_usage_rate() -> None:
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="ambiguous"):
        a02_dev_execution._safe_exec_seconds(1.0, 0.0)


def test_v2_profile_cannot_be_retried_after_a_session_marker() -> None:
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="single-use"):
        a02_dev_execution._next_session_index([{"run_id": "prior-v2-session"}])


def test_campaign_authorization_record_is_hash_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "authorization.json"
    source = {
        "source_revision": "c" * 40,
        "profile_sha256": "a" * 64,
        "preflight_sha256": "b" * 64,
    }
    balance = {"balance": 10.0}
    confirmation = a02_dev_execution._authorization_phrase(source, balance)
    document: dict[str, Any] = {
        "schema": "RES541_A02_DEVELOPMENT_CAMPAIGN_AUTHORIZATION_V1",
        "status": "OWNER_AUTHORIZED",
        "branch": "work/res-541-a02-colab-recovery",
        "source_revision": source["source_revision"],
        "source_tree": "d" * 40,
        "development_profile_sha256": source["profile_sha256"],
        "development_preflight_sha256": source["preflight_sha256"],
        "campaign_cap_cu": 2.0,
        "max_t4_sessions": 2,
        "max_session_seconds": 900,
        "max_exec_seconds": 720,
        "no_upgrade": True,
        "no_training": True,
        "initial_compute_unit_balance": balance["balance"],
        "owner_confirmation": confirmation,
        "owner_confirmation_sha256": hashlib.sha256(confirmation.encode()).hexdigest(),
    }
    document["authorization_sha256"] = hashlib.sha256(
        json.dumps(document, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(json.dumps(document))
    monkeypatch.setattr(a02_dev_execution, "AUTHORIZATION_PATH", path)

    assert a02_dev_execution._load_authorization()["status"] == "OWNER_AUTHORIZED"
    document["campaign_cap_cu"] = 200.0
    path.write_text(json.dumps(document))
    with pytest.raises(a02_dev_execution.DevelopmentRunError, match="integrity"):
        a02_dev_execution._load_authorization()

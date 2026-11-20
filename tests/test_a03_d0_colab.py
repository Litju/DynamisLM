from pathlib import Path

import pytest
from scripts.a03_d0_colab import approved, exact_live, model_cost


def test_launch_refuses_a_different_proposal_digest(tmp_path: Path) -> None:
    (tmp_path / "proposal.json").write_text("{}")
    with pytest.raises(ValueError, match="explicit owner approval"):
        approved(tmp_path, "APPROVE RES-745 D0 " + "0" * 64)


def test_price_gate_binds_the_only_active_t4_and_uses_a_modeled_ceiling() -> None:
    live = {
        "usage_rate_cu_per_hour": 1.15,
        "active_assignment_count": 1,
        "active_sessions": [{"name": "d0", "endpoint": "exact", "hardware": "T4"}],
    }
    assert exact_live(live, "d0", "exact")
    assert not exact_live(live, "d0", "substituted")
    assert not exact_live({**live, "usage_rate_cu_per_hour": 1.16}, "d0", "exact")
    assert not exact_live({**live, "active_assignment_count": 2}, "d0", "exact")
    assert model_cost({"balance": 20}, {"balance": 20}, 3600) == 1.35
    assert model_cost({"balance": 20}, {"balance": 19}, 1000) == 1.21

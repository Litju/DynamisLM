from collections import Counter

import pytest
from scripts import a02_v3_decision as decision
from scripts.a03_d0_sample import rank, seal, select


def test_d0_selects_three_lowest_hashes_from_each_historical_family() -> None:
    examples = decision.heldout_examples(decision.load_protocol())
    selected = select(examples)
    assert len(selected) == 42
    assert set(Counter(row["family"] for row in selected).values()) == {3}
    assert select(list(reversed(examples))) == selected
    selected_ids = {decision.example_id(row) for row in selected}
    for row in examples:
        if decision.example_id(row) not in selected_ids:
            assert all(
                rank(row) > rank(pick) for pick in selected if pick["family"] == row["family"]
            )
    with pytest.raises(ValueError, match="duplicate"):
        select([*examples, examples[0]])


def test_d0_rejects_an_unbound_static_receipt() -> None:
    with pytest.raises(ValueError, match="frozen D0 static receipt"):
        seal(None, b"{}")

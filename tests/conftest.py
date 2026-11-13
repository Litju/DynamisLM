from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _fast_supervision_backoff(monkeypatch: Any) -> None:
    """Escalation rounds stay bounded and counted, but tests need not sleep between them."""
    from scripts import a02_v3_execution as execution

    monkeypatch.setattr(execution, "TERMINATION_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(execution, "RECONCILE_DELAY_SECONDS", 0)


@pytest.fixture(autouse=True)
def _fast_watchdog_retry(monkeypatch: Any) -> None:
    # Subprocess watchdogs read this at import; in-process ones read the module constant.
    monkeypatch.setenv("RES541_WATCHDOG_RETRY_SECONDS", "0")
    from scripts import a02_v3_execution

    monkeypatch.setattr(a02_v3_execution, "WATCHDOG_RETRY_SECONDS", 0.0)

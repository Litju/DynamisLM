from __future__ import annotations

import copy
import hashlib
import sys
from types import ModuleType
from typing import Any

import pytest
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as decision
from scripts import a02_v3_gold as gold

_VERIFY_PROTOCOL = decision.load_protocol
_VERIFIED_PROTOCOLS: dict[tuple[Any, ...], dict[str, Any]] = {}


def protocol_fingerprint() -> tuple[Any, ...]:
    """Everything ``load_protocol`` reads: its three frozen input files and the code it runs.

    The bytes of the protocol, profile and generated-semantics files are hashed on every call,
    and every module-level binding of every ``scripts.*`` module reachable from the decision
    module is identified by object identity. A test that tampers with a file, repoints a path
    or monkeypatches any generator, gold deriver or hash function therefore gets a different
    key, and with it the real verification.
    """
    paths = (decision.PROTOCOL_PATH, v3.PROFILE_PATH, gold.GENERATED_SEMANTICS_PATH)
    files = tuple((str(p), hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths)
    bindings = tuple(
        (module.__name__, tuple((attr, id(value)) for attr, value in vars(module).items()))
        for module in _reachable_modules()
    )
    return files, bindings


def _reachable_modules() -> list[ModuleType]:
    """Every ``scripts.*`` module whose bindings ``load_protocol`` can reach.

    The closure follows imported modules and the defining module of every imported function or
    class, so an unrelated controller constant patched by a test does not defeat reuse while any
    patch inside the protocol, generator, gold, grammar or hashing code still does.
    """
    seen: dict[str, ModuleType] = {}
    pending: list[ModuleType] = [decision]
    while pending:
        module = pending.pop()
        if module.__name__ in seen:
            continue
        seen[module.__name__] = module
        for value in vars(module).values():
            owner = (
                value
                if isinstance(value, ModuleType)
                else sys.modules.get(getattr(value, "__module__", None) or "")
            )
            if owner is not None and owner.__name__.startswith("scripts."):
                pending.append(owner)
    return [seen[name] for name in sorted(seen)]


def _verified_protocol() -> dict[str, Any]:
    """``load_protocol`` with the full verification run once per identical input state.

    The verification is a pure deterministic function of the fingerprinted state, so a repeat
    with an identical fingerprint must return an identical protocol. Failures are never cached,
    and every caller receives its own deep copy.
    """
    key = protocol_fingerprint()
    if key not in _VERIFIED_PROTOCOLS:
        _VERIFIED_PROTOCOLS[key] = _VERIFY_PROTOCOL()
    return copy.deepcopy(_VERIFIED_PROTOCOLS[key])


# Installed before collection so module-level ``PROTOCOL = decision.load_protocol()`` imports
# share the verification too. A test that monkeypatches ``load_protocol`` gets this back on undo.
decision.load_protocol = _verified_protocol


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

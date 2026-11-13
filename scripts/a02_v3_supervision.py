"""RES-541 session supervision: lifecycle, cancellation and bounded verified termination.

The controller thread may be blocked inside one provider command while a monitor thread
decides the paid target must die. This module supplies the pieces that make that safe:

* ``SessionLifecycle`` - a small phase machine plus a shared cancellation state. Its lock guards
  only in-memory state and is never held across a provider call, so a hung provider command can
  never block an emergency stop.
* ``bounded_call`` / ``run_cancellable`` - every provider call is bounded; a blocked command is
  abandoned (its daemon thread dies with the session or the process), never waited on forever.
* ``terminate_until_absent`` - bounded stop-and-verify escalation. Only an affirmative exact
  target absence verification yields ``VERIFIED_STOPPED``; everything else is ``UNCERTAIN``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class SupervisionError(RuntimeError):
    """The session may no longer perform paid work."""


class CallTimeoutError(SupervisionError):
    """A provider call exceeded its bound and was abandoned."""


class CancelledError(SupervisionError):
    """The shared terminal-failure state interrupted a blocked operation."""


class InventoryMismatchError(RuntimeError):
    """Independent provider inventory reads disagree (possibly across a stop transition)."""


class Phase(StrEnum):
    ALLOCATION = "ALLOCATION"
    RUNNING = "RUNNING"
    STOP_REQUESTED = "STOP_REQUESTED"
    TEARDOWN_VERIFICATION = "TEARDOWN_VERIFICATION"
    VERIFIED_STOPPED = "VERIFIED_STOPPED"
    UNCERTAIN = "UNCERTAIN"


TEARDOWN_PHASES = frozenset(
    {Phase.STOP_REQUESTED, Phase.TEARDOWN_VERIFICATION, Phase.VERIFIED_STOPPED, Phase.UNCERTAIN}
)
_ALLOWED: dict[Phase, frozenset[Phase]] = {
    Phase.ALLOCATION: frozenset({Phase.RUNNING, Phase.STOP_REQUESTED, Phase.UNCERTAIN}),
    Phase.RUNNING: frozenset({Phase.STOP_REQUESTED, Phase.UNCERTAIN}),
    Phase.STOP_REQUESTED: frozenset({Phase.TEARDOWN_VERIFICATION, Phase.UNCERTAIN}),
    Phase.TEARDOWN_VERIFICATION: frozenset(
        {Phase.VERIFIED_STOPPED, Phase.UNCERTAIN, Phase.STOP_REQUESTED}
    ),
    Phase.UNCERTAIN: frozenset(
        {Phase.STOP_REQUESTED, Phase.TEARDOWN_VERIFICATION, Phase.VERIFIED_STOPPED}
    ),
    Phase.VERIFIED_STOPPED: frozenset(),
}


class SessionLifecycle:
    """Thread-safe phase machine. ``epoch`` increases on every accepted transition."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._phase = Phase.ALLOCATION
        self._epoch = 0
        self._history: list[dict[str, Any]] = [
            {"phase": Phase.ALLOCATION.value, "epoch": 0, "note": "session lifecycle created"}
        ]
        self._failures: list[str] = []
        self.cancelled = threading.Event()

    def view(self) -> tuple[Phase, int]:
        with self._lock:
            return self._phase, self._epoch

    @property
    def phase(self) -> Phase:
        return self.view()[0]

    def transition(self, target: Phase, note: str = "") -> bool:
        """Apply a legal transition; an illegal one is recorded and ignored (never raises)."""
        with self._lock:
            if target == self._phase:
                return True
            legal = target in _ALLOWED[self._phase]
            entry = {
                "phase": target.value,
                "from": self._phase.value,
                "note": note,
                "accepted": legal,
                "monotonic": time.monotonic(),
            }
            if legal:
                self._phase = target
                self._epoch += 1
            entry["epoch"] = self._epoch
            self._history.append(entry)
            return legal

    def fail(self, reason: str) -> None:
        """Shared terminal-failure state: cancels blocked work and refuses further work."""
        with self._lock:
            self._failures.append(reason)
        self.cancelled.set()

    @property
    def failures(self) -> list[str]:
        with self._lock:
            return list(self._failures)

    @property
    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in self._history]

    def work_permitted(self) -> bool:
        phase = self.phase
        return not self.cancelled.is_set() and phase in {Phase.ALLOCATION, Phase.RUNNING}

    def require_work_permitted(self, what: str) -> None:
        if not self.work_permitted():
            raise SupervisionError(
                f"{what} refused: session is {self.phase.value} or has a terminal failure"
            )


def bounded_call(operation: Callable[[], Any], timeout: float, label: str) -> Any:
    """Run in a daemon thread; raise CallTimeoutError if it outlives ``timeout``."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = operation()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=run, name=f"res541-{label}", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise CallTimeoutError(f"{label} exceeded {timeout}s and was abandoned")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def run_cancellable(
    operation: Callable[[], Any],
    lifecycle: SessionLifecycle,
    label: str,
    *,
    supervisor_ok: Callable[[], bool],
    poll: float = 0.2,
    abandoned: list[str] | None = None,
) -> Any:
    """Run a provider call, but return control the moment supervision fails or is cancelled.

    A blocked command is abandoned rather than awaited: the controller then proceeds to bounded
    teardown. The abandoned command ends when the session is stopped or the process exits.
    """
    lifecycle.require_work_permitted(label)
    if not supervisor_ok():
        lifecycle.fail(f"no live resource supervisor before {label}")
        raise SupervisionError(f"{label} refused: no live resource supervisor")
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = operation()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=run, name=f"res541-{label}", daemon=True)
    thread.start()
    while True:
        thread.join(poll)
        if not thread.is_alive():
            break
        if lifecycle.cancelled.is_set():
            if abandoned is not None:
                abandoned.append(f"{label}: cancelled by terminal failure")
            raise CancelledError(f"{label} interrupted by terminal failure")
        if not supervisor_ok():
            lifecycle.fail(f"resource supervisor lost during {label}")
            if abandoned is not None:
                abandoned.append(f"{label}: supervisor lost")
            raise CancelledError(f"{label} interrupted: resource supervisor lost")
    if "error" in box:
        raise box["error"]
    return box.get("value")


class TeardownClient(Protocol):
    def stop(self, name: str) -> bool: ...
    def verify_absent(self, name: str, *, allocation_attempted: bool = True) -> bool: ...


@dataclass
class Termination:
    absent: bool = False
    stop_succeeded: bool = False
    attempts: list[dict[str, Any]] = field(default_factory=list)


def terminate_until_absent(
    client: TeardownClient,
    name: str,
    lifecycle: SessionLifecycle,
    *,
    allocation_attempted: bool,
    rounds: int,
    call_timeout: float,
    backoff: float,
    keep_going: Callable[[], bool] = lambda: True,
) -> Termination:
    """Bounded escalation: stop, then independently verify exact-target absence, per round.

    A stop result (even ``True``) is never treated as proof. Only ``verify_absent`` returning
    ``True`` ends the escalation as verified; exhausting ``rounds`` leaves the lifecycle
    UNCERTAIN so the caller keeps the independent watchdog armed.
    """
    result = Termination()
    for round_number in range(1, rounds + 1):
        if round_number > 1 and not keep_going():
            break
        attempt: dict[str, Any] = {"round": round_number}
        lifecycle.transition(Phase.STOP_REQUESTED, f"round {round_number}")
        try:
            stopped = bounded_call(lambda: client.stop(name), call_timeout, "stop")
            attempt["stop"] = bool(stopped)
            result.stop_succeeded = result.stop_succeeded or bool(stopped)
        except Exception as exc:
            attempt["stop_error"] = f"{type(exc).__name__}: {exc}"
        lifecycle.transition(Phase.TEARDOWN_VERIFICATION, f"round {round_number}")
        try:
            absent = bounded_call(
                lambda: client.verify_absent(name, allocation_attempted=allocation_attempted),
                call_timeout,
                "verify-absent",
            )
            attempt["verified_absent"] = absent is True
        except Exception as exc:
            absent = False
            attempt["verify_error"] = f"{type(exc).__name__}: {exc}"
        result.attempts.append(attempt)
        if absent is True:
            result.absent = True
            lifecycle.transition(Phase.VERIFIED_STOPPED, f"round {round_number}")
            return result
        lifecycle.transition(Phase.UNCERTAIN, f"absence unverified after round {round_number}")
        if round_number < rounds:
            time.sleep(backoff)
    return result

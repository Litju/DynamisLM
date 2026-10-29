"""RES-414 public synthetic CPU evaluation runner; no frozen PSE scoring authority.

This bounded research adapter accepts only explicitly synthetic public-development
cases. The model/scorer callbacks are trusted in-process code, not a sandbox.
The separate PSE scoring authority is not imported, adapted, or reimplemented.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal, Protocol

VERSION = "RES414_CPU_PUBLIC_ADAPTER_V1"
QUALIFICATION = "DEVELOPMENT_ONLY_NOT_PSE_QUALIFIED"
MAX_CASES = 256
MAX_PROMPT_BYTES = 8192
MAX_REFERENCE_BYTES = 8192
MAX_RESPONSE_BYTES = 16384
_IDENTIFIER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,127}\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_GIT_SHA = re.compile(r"[a-f0-9]{40}\Z")
_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,79}\Z")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    ).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _identifier(value: object, field: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} requires a bounded stable identifier")
    return value


def _hash(value: object, field: str, *, git: bool = False) -> str:
    pattern = _GIT_SHA if git else _SHA256
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(f"{field} requires a pinned hexadecimal digest")
    return value


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _not_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _strict_object(raw: str) -> dict[str, object]:
    value = json.loads(raw, object_pairs_hook=_no_duplicate_keys, parse_constant=_not_constant)
    if type(value) is not dict:
        raise ValueError("response/reference must be a JSON object")
    return value


@dataclass(frozen=True, slots=True)
class PublicSyntheticCase:
    case_id: str
    message: str
    reference_json: str
    split: str = "PUBLIC_DEVELOPMENT"
    origin: str = "DETERMINISTIC_SYNTHETIC"

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case_id")
        for field, value, limit in (
            ("message", self.message, MAX_PROMPT_BYTES),
            ("reference", self.reference_json, MAX_REFERENCE_BYTES),
        ):
            if type(value) is not str or not value.strip() or len(value.encode()) > limit:
                raise ValueError(f"{field} must contain bounded, non-empty text")
        _strict_object(self.reference_json)
        if self.split != "PUBLIC_DEVELOPMENT" or self.origin != "DETERMINISTIC_SYNTHETIC":
            raise ValueError("only synthetic public-development cases are admitted")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    run_id: str
    case_id: str
    message: str


class ModelPort(Protocol):
    def generate(self, request: ModelRequest) -> str: ...


@dataclass(frozen=True, slots=True)
class Score:
    verdict: Literal["PASS", "FAIL"]
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.verdict not in {"PASS", "FAIL"}:
            raise ValueError("scorer must return PASS or FAIL")
        if type(self.reason_codes) is not tuple or any(
            type(code) is not str or _REASON.fullmatch(code) is None
            for code in self.reason_codes
        ):
            raise ValueError("scorer returned invalid reason codes")


class ScorerPort(Protocol):
    """Trusted scorer adapter; NOT a PSE scoring implementation."""

    scorer_id: str
    scorer_sha256: str

    def score(self, reference: Mapping[str, object], response: Mapping[str, object]) -> Score: ...


@dataclass(frozen=True, slots=True)
class RunSpec:
    run_id: str
    suite_id: str
    suite_sha256: str
    model_id: str
    model_revision: str
    tokenizer_revision: str
    scorer_id: str
    scorer_sha256: str
    source_revision: str
    environment_sha256: str
    seed: int

    def __post_init__(self) -> None:
        for name in ("run_id", "suite_id", "model_id", "scorer_id"):
            _identifier(getattr(self, name), name)
        for name in (
            "suite_sha256",
            "model_revision",
            "tokenizer_revision",
            "scorer_sha256",
            "environment_sha256",
        ):
            _hash(getattr(self, name), name)
        _hash(self.source_revision, "source_revision", git=True)
        if type(self.seed) is not int or not 0 <= self.seed <= 2**32 - 1:
            raise ValueError("seed must be an unsigned 32-bit integer")


@dataclass(frozen=True, slots=True)
class RawResponse:
    case_id: str
    raw: str | None
    failure: Literal["MODEL_ERROR", "INVALID_RETURN", "RESPONSE_TOO_LARGE"] | None = None

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case_id")
        if self.failure is not None and (
            self.raw is not None
            or self.failure not in {"MODEL_ERROR", "INVALID_RETURN", "RESPONSE_TOO_LARGE"}
        ):
            raise ValueError("error response cannot carry raw text")
        if self.failure is None and (
            type(self.raw) is not str or len(self.raw.encode()) > MAX_RESPONSE_BYTES
        ):
            raise ValueError("response must be a bounded string")


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    request_sha256: str
    response_sha256: str | None
    state: Literal["SCORED", "INVALID_RESPONSE", "MODEL_ERROR"]
    verdict: Literal["PASS", "FAIL"] | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunReceipt:
    version: str
    qualification: str
    spec: RunSpec
    case_results: tuple[CaseResult, ...]
    receipt_sha256: str

    def payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "qualification": self.qualification,
            "spec": asdict(self.spec),
            "case_results": [asdict(row) for row in self.case_results],
        }

    def json(self) -> str:
        return _json_bytes({**self.payload(), "receipt_sha256": self.receipt_sha256}).decode()


@dataclass(frozen=True, slots=True)
class RunEvidence:
    receipt: RunReceipt
    # Private operator-held transcript, never embedded in the public receipt.
    responses: tuple[RawResponse, ...]


def _check_cases(cases: tuple[PublicSyntheticCase, ...]) -> None:
    if type(cases) is not tuple or not 1 <= len(cases) <= MAX_CASES:
        raise ValueError("suite must contain 1..256 cases")
    if any(type(c) is not PublicSyntheticCase for c in cases):
        raise ValueError("unsupported case type")
    ids = [c.case_id for c in cases]
    if ids != sorted(set(ids)):
        raise ValueError("suite case IDs must be unique and sorted")


def suite_sha256(cases: tuple[PublicSyntheticCase, ...]) -> str:
    _check_cases(cases)
    return _sha(_json_bytes({"version": VERSION, "cases": [asdict(c) for c in cases]}))


def _admit(spec: RunSpec, cases: tuple[PublicSyntheticCase, ...], scorer: ScorerPort) -> None:
    if type(spec) is not RunSpec:
        raise ValueError("a versioned RunSpec is required")
    if spec.suite_sha256 != suite_sha256(cases):
        raise ValueError("suite changed since its digest was recorded")
    if scorer.scorer_id != spec.scorer_id or scorer.scorer_sha256 != spec.scorer_sha256:
        raise ValueError("trusted scorer identity differs from run spec")


def _parse_response(raw: str) -> dict[str, object]:
    parsed = _strict_object(raw)
    if not {"decision", "fields"} <= parsed.keys() or not parsed.keys() <= {
        "decision",
        "fields",
        "refusal",
    }:
        raise ValueError("response must use the bounded output schema")
    if parsed["decision"] not in {"ANSWER", "REFUSE"} or type(parsed["fields"]) is not dict:
        raise ValueError("invalid typed response")
    if "refusal" in parsed and type(parsed["refusal"]) is not dict:
        raise ValueError("invalid refusal")
    if parsed["decision"] == "ANSWER" and parsed.get("refusal") not in (None, {}):
        raise ValueError("answer cannot include refusal data")
    if parsed["decision"] == "REFUSE" and parsed["fields"]:
        raise ValueError("refusal cannot silently provide answer fields")
    return parsed


def _result(case: PublicSyntheticCase, response: RawResponse, scorer: ScorerPort) -> CaseResult:
    request_hash = _sha(case.message.encode())
    if response.failure is not None:
        return CaseResult(case.case_id, request_hash, None, "MODEL_ERROR", None, (response.failure,))
    assert response.raw is not None
    response_hash = _sha(response.raw.encode())
    try:
        parsed = _parse_response(response.raw)
    except (ValueError, TypeError, RecursionError):
        return CaseResult(
            case.case_id, request_hash, response_hash, "INVALID_RESPONSE", None,
            ("INVALID_TYPED_RESPONSE",),
        )
    # Invalid trusted scorer behavior aborts the run rather than inflating results.
    score = scorer.score(_strict_object(case.reference_json), parsed)
    if type(score) is not Score:
        raise ValueError("invalid trusted scorer output type")
    return CaseResult(
        case.case_id, request_hash, response_hash, "SCORED", score.verdict, score.reason_codes
    )


def rescore(
    spec: RunSpec,
    cases: tuple[PublicSyntheticCase, ...],
    responses: tuple[RawResponse, ...],
    scorer: ScorerPort,
) -> RunReceipt:
    """Deterministically score stored outputs without invoking a model."""
    _admit(spec, cases, scorer)
    if type(responses) is not tuple or len(responses) != len(cases) or any(
        type(row) is not RawResponse for row in responses
    ):
        raise ValueError("every case requires one typed response")
    if [r.case_id for r in responses] != [c.case_id for c in cases]:
        raise ValueError("response inventory or ordering differs from suite")
    rows = tuple(_result(case, response, scorer) for case, response in zip(cases, responses))
    payload: dict[str, object] = {
        "version": VERSION,
        "qualification": QUALIFICATION,
        "spec": asdict(spec),
        "case_results": [asdict(row) for row in rows],
    }
    return RunReceipt(VERSION, QUALIFICATION, spec, rows, _sha(_json_bytes(payload)))


def execute(
    spec: RunSpec,
    cases: tuple[PublicSyntheticCase, ...],
    model: ModelPort,
    scorer: ScorerPort,
) -> RunEvidence:
    """Run a trusted in-process model port on synthetic public requests only."""
    _admit(spec, cases, scorer)  # every case is validated before the first model call
    responses: list[RawResponse] = []
    for case in cases:
        try:
            raw = model.generate(ModelRequest(spec.run_id, case.case_id, case.message))
        except Exception:
            # Model exceptions never enter public output, even if they contain source text.
            responses.append(RawResponse(case.case_id, None, "MODEL_ERROR"))
            continue
        if type(raw) is not str:
            responses.append(RawResponse(case.case_id, None, "INVALID_RETURN"))
        elif len(raw.encode()) > MAX_RESPONSE_BYTES:
            responses.append(RawResponse(case.case_id, None, "RESPONSE_TOO_LARGE"))
        else:
            responses.append(RawResponse(case.case_id, raw))
    transcript = tuple(responses)
    return RunEvidence(rescore(spec, cases, transcript, scorer), transcript)


def verify_replay(
    evidence: RunEvidence,
    cases: tuple[PublicSyntheticCase, ...],
    scorer: ScorerPort,
) -> RunReceipt:
    """Refuse scorer, case, or response drift relative to the original receipt."""
    if type(evidence) is not RunEvidence:
        raise ValueError("typed RunEvidence required")
    replay = rescore(evidence.receipt.spec, cases, evidence.responses, scorer)
    if replay != evidence.receipt:
        raise ValueError("RES414_REPLAY_DIVERGENCE")
    return replay

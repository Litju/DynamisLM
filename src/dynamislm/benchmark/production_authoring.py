"""Deterministic 001C authoring from frozen authority and external private inputs."""

from __future__ import annotations

import hashlib
import re
import secrets
from collections import Counter, defaultdict
from dataclasses import dataclass, fields, replace
from pathlib import Path
from xml.etree import ElementTree as ET

from dynamislm.benchmark.authoring import (
    authoring_recipe_registry_digest,
    production_seed_namespace,
    question_classes_for_cell,
)
from dynamislm.benchmark.constants import (
    AuthorityKind,
    CaseOrigin,
    DifficultyLevel,
    ScoringProfile,
    SplitName,
)
from dynamislm.benchmark.contracts import (
    AuthorityBinding,
    DifficultyBinding,
)
from dynamislm.benchmark.coverage import COVERAGE_MATRIX, coverage_manifest_digest
from dynamislm.benchmark.pre_review import (
    CandidateIsolationMetadata,
    CandidateParentBinding,
    CandidateReviewPacket,
    bind_candidate_review_packet,
    candidate_scientific_projection,
)
from dynamislm.benchmark.production import (
    FINAL_TARGET_CASES,
    PRODUCTION_AUTHORING_PLAN_VERSION,
    PRODUCTION_AUTHORING_PROCESS_ID,
    PRODUCTION_BATCH_ID,
    PRODUCTION_SYNTHETIC_QUESTION_SURFACE_VARIANTS,
    ProductionAuthoringPlanV1,
    ProductionCandidateCommitmentV1,
    ProductionDuplicationAuditV1,
    ProductionFeasibilityReceiptV1,
    ProductionReviewQueueV1,
    _validate_production_candidate_set_and_commitments,
    audit_production_duplicates,
    bind_production_authoring_plan,
    build_production_review_queue,
    validate_production_authoring_plan,
    validate_production_hard_feasibility,
    validate_production_isolation,
    validate_production_origin_isolation_metadata,
    validate_production_review_queue,
)
from dynamislm.benchmark.production_exclusions import (
    QUALIFICATION_PRIVATE_EXCLUSION_PATH,
    QualificationExclusionCommitmentV1,
    validate_production_candidate_set_against_qualification_exclusion,
)
from dynamislm.benchmark.production_store import (
    DEFAULT_PRODUCTION_ROOT,
    read_external_production_json,
    write_external_production_json,
)
from dynamislm.benchmark.res115_authoring import build_res115_source_artifact_resolver
from dynamislm.benchmark.source_artifacts import SourceArtifactResolver
from dynamislm.qualification import ReferenceCase
from dynamislm.qualification.res115_authoring import SourceCellSelectionV1
from dynamislm.serialization import canonical_hash, register_serializable_type

SYNTHETIC_GENERATOR_ID = "pse-v1-unregistered-operation-context"
SYNTHETIC_GENERATOR_VERSION = "1.0.0"
MAX_PRODUCTION_SOURCE_CASES = 40
_SYNTHETIC_QUESTION_FOCUS = {
    "F05": "is this unsupported rather than zero?",
    "F06": "which live method is missing?",
    "F13": "why cannot these inputs yield a value?",
    "F14": "what safe partial response remains?",
}
if set(_SYNTHETIC_QUESTION_FOCUS) != {
    family for family, _variant_id in PRODUCTION_SYNTHETIC_QUESTION_SURFACE_VARIANTS
}:
    raise ValueError("synthetic refusal surface variants differ from their authorized families")


def _production_adversarial_tags(
    capability_id: str,
    family: str,
    *,
    slot: int | None = None,
) -> tuple[str, ...]:
    row = next(item for item in COVERAGE_MATRIX if item.capability_id == capability_id)
    if capability_id in {"C01", "C02", "C03"}:
        return tuple(sorted(row.adversarial_tags, key=lambda value: value.encode("utf-8")))
    family_index = row.benchmark_families.index(family)
    tag_index = family_index + (slot or 0)
    return (row.adversarial_tags[tag_index % len(row.adversarial_tags)],)


def _apply_adversarial_tag_focus(
    question: str,
    tags: tuple[str, ...],
    *,
    scenario_id: str,
) -> str:
    focus = (
        "combined protocol field omissions"
        if set(tags)
        == {
            "MISSING_DEVICE",
            "MISSING_THRESHOLD",
            "MISSING_EVENT",
            "MISSING_PHASE",
        }
        else (
            "multiple registered identity risks"
            if len(tags) > 1
            else (
                tags[0].lower().replace("_", " ")
                if len(tags) == 1
                else ", ".join(tag.lower().replace("_", " ") for tag in tags)
            )
        )
    )
    return f"{question} For scenario {scenario_id}, assess {focus}."


def _bind_production_adversarial_tags(
    packet: CandidateReviewPacket,
    tags: tuple[str, ...],
) -> CandidateReviewPacket:
    return bind_candidate_review_packet(
        replace(
            packet,
            adversarial_tags=tags,
            candidate_payload_hash="sha256:" + "0" * 64,
            proposed_approval_digest="sha256:" + "0" * 64,
        )
    )


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionSyntheticGeneratorV1:
    generator_id: str
    version: str
    generator_family: str
    output_contract: str


PRODUCTION_SYNTHETIC_GENERATORS = tuple(
    ProductionSyntheticGeneratorV1(
        generator_id=SYNTHETIC_GENERATOR_ID,
        version=SYNTHETIC_GENERATOR_VERSION,
        generator_family=f"pse-v1-synthetic-refusal-{split.value.lower()}",
        output_contract=(
            "non-numeric C08 context bound to a live RES-71 no-operation refusal reference"
        ),
    )
    for split, _count in (
        (SplitName.PUBLIC_DEVELOPMENT, 260),
        (SplitName.FROZEN_VALIDATION, 87),
        (SplitName.HIDDEN_FINAL, 87),
    )
)
PRODUCTION_SYNTHETIC_GENERATOR_DIGEST = canonical_hash(PRODUCTION_SYNTHETIC_GENERATORS)


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionSourceSelectionV1:
    candidate_id: str
    capability_id: str
    benchmark_family: str
    pmcid: str
    document_id: str
    source_family_id: str
    applicability_scope: str
    span_digests: tuple[str, ...]
    search_strata: tuple[str, ...]
    direct_target_document: bool


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionExpertBatchV1:
    author_batch_id: str
    protocol_template_id: str
    isolation_cluster_id: str
    candidate_ids: tuple[str, ...]
    rationale: str

    def __post_init__(self) -> None:
        if not all((self.author_batch_id, self.protocol_template_id, self.isolation_cluster_id)):
            raise ValueError("expert batch and template identities must be non-empty")
        if not self.candidate_ids or self.candidate_ids != tuple(
            sorted(set(self.candidate_ids), key=lambda value: value.encode("utf-8"))
        ):
            raise ValueError("expert batch candidate membership must be canonical")
        if not self.rationale.strip():
            raise ValueError("expert batch requires private scientific rationale")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionMutationLineageInputV1:
    lineage_id: str
    parent_candidate_id: str
    child_candidate_ids: tuple[str, ...]
    operator_id: str
    rationale: str

    def __post_init__(self) -> None:
        if not self.child_candidate_ids or self.child_candidate_ids != tuple(
            sorted(self.child_candidate_ids, key=lambda value: value.encode("utf-8"))
        ):
            raise ValueError("mutation children must use canonical candidate-ID order")
        if not self.rationale.strip():
            raise ValueError("mutation lineage requires private scientific rationale")


@register_serializable_type
@dataclass(frozen=True, slots=True)
class ProductionAuthoringInputsV1:
    batch_id: str
    synthetic_generator_registry_digest: str
    scenario_seeds: tuple[tuple[str, str], ...]
    synthetic_seed_blocks: tuple[tuple[str, str], ...]
    mutation_seed_blocks: tuple[tuple[str, str], ...]
    source_selections: tuple[ProductionSourceSelectionV1, ...]
    expert_batches: tuple[ProductionExpertBatchV1, ...]
    mutation_lineages: tuple[ProductionMutationLineageInputV1, ...]
    input_digest: str

    def __post_init__(self) -> None:
        if self.batch_id != PRODUCTION_BATCH_ID:
            raise ValueError("private authoring inputs bind a different production batch")
        for name in (
            "synthetic_generator_registry_digest",
            "input_digest",
        ):
            if re.fullmatch(r"sha256:[0-9a-f]{64}", getattr(self, name)) is None:
                raise ValueError(f"private authoring input {name} is malformed")
        for name in (
            "scenario_seeds",
            "synthetic_seed_blocks",
            "mutation_seed_blocks",
        ):
            pairs = getattr(self, name)
            ids = tuple(candidate_id for candidate_id, _value in pairs)
            if ids != tuple(sorted(set(ids), key=lambda value: value.encode("utf-8"))):
                raise ValueError(f"private {name} must use unique canonical candidate order")
            if any(not value for _candidate_id, value in pairs):
                raise ValueError(f"private {name} must contain non-empty seed values")


def production_authoring_input_digest(inputs: ProductionAuthoringInputsV1) -> str:
    return canonical_hash(
        {
            item.name: getattr(inputs, item.name)
            for item in fields(inputs)
            if item.name != "input_digest"
        }
    )


@dataclass(frozen=True, slots=True)
class ProductionAuthoringDraftV1:
    packets: tuple[CandidateReviewPacket, ...]
    plan: ProductionAuthoringPlanV1
    inputs: ProductionAuthoringInputsV1
    commitments: tuple[ProductionCandidateCommitmentV1, ...]
    feasibility_receipt: ProductionFeasibilityReceiptV1
    review_queue: ProductionReviewQueueV1
    duplication_audit: ProductionDuplicationAuditV1


def _semantic_slot_specs() -> tuple[tuple[str, str, str, int], ...]:
    special = {"C08", "C13", "C16"}
    counts: Counter[tuple[str, str]] = Counter(
        {
            (row.capability_id, family): 3
            for row in COVERAGE_MATRIX
            if row.capability_id not in special
            for family in row.benchmark_families
        }
    )
    for cell in (("C03", "F01"), ("C02", "F02"), ("C09", "F07"), ("C14", "F01")):
        counts[cell] += 1
    counts[("C18", "F01")] += 1
    for index in range(7):
        counts[("C18", f"F{index + 2:02d}")] += 1
    if sum(counts.values()) != 240:
        raise ValueError("deterministic semantic authoring slots do not total 240")
    return tuple(
        (
            f"PSE-V1-CANDIDATE:SEM:{capability_id}:{family}:{slot:02d}",
            capability_id,
            family,
            slot,
        )
        for (capability_id, family), count in sorted(counts.items())
        for slot in range(count)
    )


def _engine_slot_specs() -> tuple[tuple[str, str, str, int], ...]:
    slots = [
        (
            f"PSE-V1-CANDIDATE:ENGINE:C16:{family}:{slot:02d}",
            "C16",
            family,
            slot,
        )
        for family in ("F05", "F07", "F10", "F14")
        for slot in range(7)
    ]
    slots.append(("PSE-V1-CANDIDATE:ENGINE:C08:F05:00", "C08", "F05", 0))
    slots.extend(
        (
            f"PSE-V1-CANDIDATE:ENGINE:C18:{family}:{slot:02d}",
            "C18",
            family,
            slot,
        )
        for family in ("F05", "F06")
        for slot in range(1)
    )
    if len(slots) != 31:
        raise ValueError("deterministic engine authoring slots do not total 31")
    return tuple(slots)


def _synthetic_slot_specs() -> tuple[tuple[str, str, SplitName], ...]:
    return tuple(
        (
            f"PSE-V1-CANDIDATE:SYNTH:C08:{family}:{split.value}",
            family,
            split,
        )
        for family in ("F05", "F06", "F13", "F14")
        for split, _count in (
            (SplitName.PUBLIC_DEVELOPMENT, 260),
            (SplitName.FROZEN_VALIDATION, 87),
            (SplitName.HIDDEN_FINAL, 87),
        )
    )


_EXPERTISE_GROUP = {
    "C01": "MEASUREMENT_IDENTITY",
    "C02": "PROTOCOL_EXTRACTION",
    "C03": "MEASUREMENT_IDENTITY",
    "C04": "VALUE_PROVENANCE",
    "C05": "UNITS_AND_NORMALIZATION",
    "C06": "FRAME_AND_EVENT_DEFINITIONS",
    "C07": "COMPARABILITY",
    "C09": "LONGITUDINAL_CLAIMS",
    "C10": "STATISTICAL_DESIGN",
    "C11": "POPULATION_STRUCTURE",
    "C12": "RELIABILITY_AND_UNCERTAINTY",
    "C14": "EVIDENCE_APPLICABILITY",
    "C15": "CAUSAL_INFERENCE",
    "C17": "SCIENTIFIC_ERROR_TAXONOMY",
    "C18": "REFUSAL_AND_SAFE_PARTIAL",
}


def _expert_batch_records(
    slots: tuple[tuple[str, str, str, int], ...],
) -> tuple[ProductionExpertBatchV1, ...]:
    by_expertise: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)
    for slot in slots:
        by_expertise[_EXPERTISE_GROUP[slot[1]]].append(slot)
    batches: list[ProductionExpertBatchV1] = []
    for expertise, members in sorted(by_expertise.items()):
        remaining = list(sorted(members, key=lambda item: item[0].encode("utf-8")))
        while remaining:
            counts = Counter(item[1:3] for item in remaining)
            first_cell = max(counts, key=lambda cell: (counts[cell], cell))
            first_index = next(
                index for index, item in enumerate(remaining) if item[1:3] == first_cell
            )
            first = remaining.pop(first_index)
            first_cell = first[1:3]
            partner_options = [
                (index, item) for index, item in enumerate(remaining) if item[1:3] != first_cell
            ]
            partner_index = None
            if partner_options:
                partner_index = max(
                    partner_options,
                    key=lambda pair: (
                        counts[pair[1][1:3]],
                        pair[1][1].encode("utf-8"),
                        pair[1][2].encode("utf-8"),
                    ),
                )[0]
            group = (first,) if partner_index is None else (first, remaining.pop(partner_index))
            member_ids = tuple(
                sorted((item[0] for item in group), key=lambda value: value.encode("utf-8"))
            )
            digest = canonical_hash((expertise, member_ids)).removeprefix("sha256:")[:20]
            batch_id = f"PSE-V1-EXPERT-BATCH:{digest}"
            batches.append(
                ProductionExpertBatchV1(
                    author_batch_id=batch_id,
                    protocol_template_id=f"PSE-V1-PROTOCOL-TEMPLATE:{digest}",
                    isolation_cluster_id=f"PSE-V1-SEMANTIC-CLUSTER:{digest}",
                    candidate_ids=member_ids,
                    rationale=(
                        "Scientifically unique bounded protocol omission scenario."
                        if len(group) == 1
                        else "Two frozen cells share a bounded synthetic test context."
                    ),
                )
            )
    if {candidate_id for batch in batches for candidate_id in batch.candidate_ids} != {
        item[0] for item in slots
    }:
        raise ValueError("finite expert batch registry lost semantic candidate membership")
    return tuple(sorted(batches, key=lambda item: item.author_batch_id.encode("utf-8")))


def _source_candidate_id(selection: SourceCellSelectionV1) -> str:
    if not isinstance(selection, SourceCellSelectionV1):
        raise TypeError("source selection must be SourceCellSelectionV1")
    return (
        "PSE-V1-CANDIDATE:SOURCE:"
        + canonical_hash(
            (
                selection.pmcid,
                selection.capability_id,
                selection.benchmark_family,
                tuple(item.span_digest for item in selection.spans),
            )
        ).removeprefix("sha256:")[:20]
    )


def _choose_supported_sources(
    exclusion: QualificationExclusionCommitmentV1,
    *,
    external_root: Path,
) -> tuple[SourceCellSelectionV1, ...]:
    from dynamislm.qualification.res115_authoring import (
        PHASE_A_SEARCH_STRATA,
        _mapping,
        _phase_a_source_inputs,
        _source_cell_candidates,
        _string,
    )

    accepted, support, direct_rows, strata_by_pmcid = _phase_a_source_inputs(
        external_root=external_root
    )
    direct_families = {
        _string(
            _mapping(row.get("source_family_identity"), field="source family").get(
                "source_family_id"
            ),
            field="source family ID",
        )
        for row in accepted
        if row.get("applicability_scope") == "DIRECT_TARGET_POPULATION_EVIDENCE"
    }
    excluded_span_ids = {
        span_id
        for entry in exclusion.entries
        for span_id, _digest in entry.evidence_span_identities
    }
    excluded_span_digests = {
        digest for entry in exclusion.entries for _span_id, digest in entry.evidence_span_identities
    }
    raw = _source_cell_candidates(
        accepted,
        support,
        external_root=external_root,
        source_search_strata=PHASE_A_SEARCH_STRATA,
        strata_by_pmcid=strata_by_pmcid,
    )
    eligible = tuple(
        item
        for item in raw
        if item.source_family_id not in direct_families
        and all(
            proposal.span_digest not in excluded_span_digests
            and f"PSE-EVIDENCE:PRODUCTION:{item.pmcid}:{proposal.span_digest[-12:]}"
            not in excluded_span_ids
            for proposal in item.spans
        )
    )
    by_family: dict[str, list[SourceCellSelectionV1]] = defaultdict(list)
    for item in eligible:
        by_family[item.source_family_id].append(item)
    candidates = tuple(
        sorted(
            (item for family_items in by_family.values() for item in family_items),
            key=lambda item: (
                item.source_family_id.encode("utf-8"),
                item.pmcid.encode("utf-8"),
                item.capability_id.encode("utf-8"),
                item.benchmark_family.encode("utf-8"),
            ),
        )
    )
    noncanonical = next(
        (item for item in candidates if item.applicability_scope == "NONCANONICAL_CONTEXT_ONLY"),
        None,
    )
    if noncanonical is None:
        raise ValueError("source-backed production authoring lacks a noncanonical source")

    quotas = {"F01": 6, "F02": 15, "F11": 14}
    counts: Counter[str] = Counter()
    selected: list[SourceCellSelectionV1] = []
    selected_families: set[str] = set()
    selected_documents: set[str] = set()
    represented_strata: set[str] = set()

    def add(item: SourceCellSelectionV1) -> None:
        selected.append(item)
        selected_families.add(item.source_family_id)
        selected_documents.add(item.pmcid)
        counts[item.benchmark_family] += 1
        represented_strata.update(item.search_strata)

    add(noncanonical)
    for family in ("F01", "F02", "F11"):
        while counts[family] < 3:
            options = [
                item
                for item in candidates
                if item.benchmark_family == family
                and item.source_family_id not in selected_families
                and item.pmcid not in selected_documents
            ]
            if not options:
                raise ValueError(f"source lane cannot provide three independent {family} cases")
            chosen = max(
                options,
                key=lambda item: (
                    len(set(item.search_strata) - represented_strata),
                    len(item.spans),
                    item.source_family_id.encode("utf-8"),
                ),
            )
            add(chosen)

    while not set(PHASE_A_SEARCH_STRATA).issubset(represented_strata):
        options = [
            item
            for item in candidates
            if item.source_family_id not in selected_families
            and item.pmcid not in selected_documents
            and counts[item.benchmark_family] < quotas[item.benchmark_family]
            and set(item.search_strata) - represented_strata
        ]
        if not options:
            raise ValueError("35 source cases cannot cover all ten Phase-A search strata")
        chosen = max(
            options,
            key=lambda item: (
                len(set(item.search_strata) - represented_strata),
                -counts[item.benchmark_family],
                item.source_family_id.encode("utf-8"),
            ),
        )
        add(chosen)

    while len(selected) < 35:
        options = [
            item
            for item in candidates
            if item.source_family_id not in selected_families
            and item.pmcid not in selected_documents
            and counts[item.benchmark_family] < quotas[item.benchmark_family]
        ]
        if not options:
            raise ValueError("Phase-A source families cannot supply exactly 35 indirect cases")
        chosen = min(
            options,
            key=lambda item: (
                counts[item.benchmark_family],
                item.source_family_id.encode("utf-8"),
                item.pmcid.encode("utf-8"),
            ),
        )
        add(chosen)
    if len(selected_families) != 35 or set(PHASE_A_SEARCH_STRATA) - represented_strata:
        raise ValueError("source lane misses its distinct-family or Phase-A stratum minimum")
    return tuple(sorted(selected, key=lambda item: _source_candidate_id(item).encode("utf-8")))


def _direct_target_source_selections(
    exclusion: QualificationExclusionCommitmentV1,
    *,
    external_root: Path,
) -> tuple[SourceCellSelectionV1, ...]:
    from dynamislm.benchmark.source_artifacts import (
        derive_unique_jats_paragraph_locator,
        extract_jats_text,
    )
    from dynamislm.qualification.res115_authoring import (
        SourceCellSelectionV1,
        SourceSpanProposalV1,
        _accepted_phase_a_rows,
        _mapping,
        _read_phase_a_jsonl,
        _retained_jats_bytes,
        _source_search_strata_by_pmcid,
        _string,
    )

    accepted = _accepted_phase_a_rows()
    direct_rows = _read_phase_a_jsonl(
        external_root / "manifests" / "direct_target_population_evidence_001.jsonl",
        description="Phase-A direct-target population evidence",
    )
    replay_rows = _read_phase_a_jsonl(
        external_root / "manifests" / "search_replays_001.jsonl",
        description="Phase-A search replay evidence",
    )
    direct = tuple(
        row
        for row in direct_rows
        if row.get("applicability_scope") == "DIRECT_TARGET_POPULATION_EVIDENCE"
    )
    if len(direct) != 5:
        raise ValueError("Phase-A must retain exactly five direct-target documents")
    accepted_by_pmcid = {row["pmcid"]: row for row in accepted}
    strata_by_pmcid = _source_search_strata_by_pmcid(accepted, replay_rows)
    excluded = {
        digest for entry in exclusion.entries for _span_id, digest in entry.evidence_span_identities
    }
    population_terms = re.compile(
        r"\b(male|men|professional|elite|first.team|football|soccer|league|academy|players|athletes|squad|team)\b",
        re.IGNORECASE,
    )
    method_heading = re.compile(
        r"method|participant|subject|sample|population|design|setting", re.I
    )
    selections = []
    for record in sorted(
        direct,
        key=lambda row: _string(row.get("pmcid"), field="direct-target PMCID").encode("utf-8"),
    ):
        pmcid = _string(record.get("pmcid"), field="direct-target PMCID")
        row = accepted_by_pmcid.get(pmcid)
        if row is None or row.get("applicability_scope") != "DIRECT_TARGET_POPULATION_EVIDENCE":
            raise ValueError(
                "direct-target evidence does not resolve to an accepted Phase-A document"
            )
        jats = _retained_jats_bytes(row, external_root=external_root)
        root = ET.fromstring(jats)
        parent_of = {child: parent for parent in root.iter() for child in parent}
        options = []
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "p":
                continue
            text = "".join(element.itertext())
            if not 100 <= len(text) <= 2600 or not population_terms.search(text):
                continue
            digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
            if digest in excluded:
                continue
            ancestor = parent_of.get(element)
            headings: list[str] = []
            while ancestor is not None:
                headings.extend(
                    "".join(child.itertext())
                    for child in ancestor
                    if child.tag.rsplit("}", 1)[-1] == "title"
                )
                ancestor = parent_of.get(ancestor)
            heading_text = " ".join(headings)
            if not method_heading.search(heading_text):
                continue
            options.append(
                (
                    0 if re.search(r"participant|subject|sample", heading_text, re.I) else 1,
                    len(text),
                    digest,
                )
            )
        if not options:
            raise ValueError(f"no distinct exact Methods population span remains for {pmcid}")
        _heading_rank, _text_size, digest = min(options)
        locator = derive_unique_jats_paragraph_locator(jats, digest)
        text = extract_jats_text(jats, locator)
        if "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            raise ValueError("selected direct-target JATS paragraph digest changed")
        family = _mapping(row.get("source_family_identity"), field="source family")
        proposal = SourceSpanProposalV1(
            span_digest=digest,
            locator=locator,
            text=text,
            scope="PHASE_A_DIRECT_TARGET_METHODS_PARAGRAPH",
            support_rules=("accepted direct-target Methods population paragraph",),
            support_tags=("DIRECT_TARGET_POPULATION_EVIDENCE",),
        )
        selections.append(
            SourceCellSelectionV1(
                pmcid=pmcid,
                capability_id="C13",
                benchmark_family="F11",
                applicability_scope="DIRECT_TARGET_POPULATION_EVIDENCE",
                source_family_id=_string(family.get("source_family_id"), field="source family ID"),
                source_family_digest=_string(
                    family.get("family_digest"), field="source family digest"
                ),
                search_strata=strata_by_pmcid.get(pmcid, ()),
                spans=(proposal,),
                population_clause_values=(),
                direct_target=False,
            )
        )
    return tuple(selections)


def _source_authoring_records(
    selections: tuple[SourceCellSelectionV1, ...],
) -> tuple[ProductionSourceSelectionV1, ...]:
    from dynamislm.qualification.res115_authoring import (
        _accepted_phase_a_rows,
        _mapping,
        _string,
    )

    accepted_by_pmcid = {
        _string(row.get("pmcid"), field="accepted PMCID"): row for row in _accepted_phase_a_rows()
    }
    records = []
    for selection in selections:
        if not isinstance(selection, SourceCellSelectionV1):
            raise TypeError("source selection must be SourceCellSelectionV1")
        row = accepted_by_pmcid[selection.pmcid]
        document_id = _string(
            _mapping(row.get("retained_source_artifact"), field="retained source artifact").get(
                "document_identity_id"
            ),
            field="document identity ID",
        )
        records.append(
            ProductionSourceSelectionV1(
                candidate_id=_source_candidate_id(selection),
                capability_id=selection.capability_id,
                benchmark_family=selection.benchmark_family,
                pmcid=selection.pmcid,
                document_id=document_id,
                source_family_id=selection.source_family_id,
                applicability_scope=selection.applicability_scope,
                span_digests=tuple(item.span_digest for item in selection.spans),
                search_strata=selection.search_strata,
                direct_target_document=(
                    selection.applicability_scope == "DIRECT_TARGET_POPULATION_EVIDENCE"
                ),
            )
        )
    return tuple(sorted(records, key=lambda item: item.candidate_id.encode("utf-8")))


def _production_source_question(selection: SourceCellSelectionV1, candidate_id: str) -> str:
    span_id = selection.spans[0].span_digest[:12]
    candidate_key = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:10].upper()
    scope = selection.applicability_scope.lower().replace("_", " ")
    tags = _production_adversarial_tags(selection.capability_id, selection.benchmark_family)
    question = (
        f"Source case {candidate_key} cites {selection.pmcid} span {span_id} for cell "
        f"{selection.capability_id}:{selection.benchmark_family} under span {span_id}. "
        f"Source family "
        f"{selection.source_family_id} carries {scope} applicability for {candidate_key}. "
        f"Extract the retained paragraph for span {span_id} and classify its target scope "
        f"for {candidate_key}."
    )
    return _apply_adversarial_tag_focus(question, tags, scenario_id=candidate_key)


def _author_source_packets(
    selections: tuple[SourceCellSelectionV1, ...],
    *,
    source_resolver: SourceArtifactResolver,
) -> tuple[CandidateReviewPacket, ...]:
    from dynamislm.qualification.res115_authoring import (
        _accepted_phase_a_rows,
        _mapping,
        _source_candidate_packet,
        _string,
    )

    accepted = _accepted_phase_a_rows()
    accepted_by_pmcid = {_string(row.get("pmcid"), field="accepted PMCID"): row for row in accepted}
    scope_by_document_id = {
        _string(
            _mapping(row.get("retained_source_artifact"), field="retained source artifact").get(
                "document_identity_id"
            ),
            field="document identity ID",
        ): _string(row.get("applicability_scope"), field="source applicability scope")
        for row in accepted
    }
    packet_by_id = {}
    for selection in selections:
        if not isinstance(selection, SourceCellSelectionV1):
            raise TypeError("source selection must be SourceCellSelectionV1")
        row = accepted_by_pmcid[selection.pmcid]
        candidate_id = _source_candidate_id(selection)
        question = _production_source_question(selection, candidate_id)
        packet = _source_candidate_packet(
            selection,
            accepted_row=row,
            resolver=source_resolver,
            source_scope_by_document_id=scope_by_document_id,
            enforce_production_validator=True,
            candidate_id=candidate_id,
            evidence_span_id_namespace="PRODUCTION",
            question_text=question,
            authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
        )
        packet = _bind_production_adversarial_tags(
            packet,
            _production_adversarial_tags(selection.capability_id, selection.benchmark_family),
        )
        packet_by_id[packet.candidate_id] = packet
    return tuple(
        packet_by_id[candidate_id]
        for candidate_id in sorted(packet_by_id, key=lambda value: value.encode("utf-8"))
    )


def _mutation_lineage_specs(
    semantic_slots: tuple[tuple[str, str, str, int], ...],
) -> tuple[ProductionMutationLineageInputV1, ...]:
    category_specs = (
        (
            "measurement-identity-trap",
            "C01/C03/C04",
            "The child adds an identity/value-origin trap while preserving parent authority.",
            tuple(item[0] for item in semantic_slots if item[1] in {"C01", "C03", "C04"}),
            7,
        ),
        (
            "comparability-overreach",
            "C07",
            "The child tests whether matching labels override the parent's comparability boundary.",
            tuple(item[0] for item in semantic_slots if item[1] == "C07"),
            7,
        ),
        (
            "claim-boundary-overreach",
            "C09/C15",
            "The child injects a longitudinal or causal overclaim against parent authority.",
            tuple(item[0] for item in semantic_slots if item[1] in {"C09", "C15"}),
            7,
        ),
        (
            "safe-partial-refusal-trap",
            "C18",
            "The child requires refusal while preserving a justified lower-level description.",
            tuple(item[0] for item in semantic_slots if item[1] == "C18" and item[2] != "F01"),
            8,
        ),
        (
            "error-correction-trap",
            "C17",
            "The child adds an adversarial error and must retain the registered correction.",
            tuple(item[0] for item in semantic_slots if item[1] == "C17"),
            8,
        ),
    )
    selected: list[tuple[str, str, str, str]] = []
    for operator_id, capability_group, rationale, candidate_ids, count in category_specs:
        if len(candidate_ids) < count:
            raise ValueError(f"mutation lane lacks distinct {capability_group} parent candidates")
        selected.extend(
            (operator_id, capability_group, rationale, candidate_id)
            for candidate_id in candidate_ids[:count]
        )
    if len(selected) != 37:
        raise ValueError("mutation authoring requires exactly 37 independent parent lineages")
    lineages = []
    for index, (operator_id, capability_group, rationale, parent_id) in enumerate(selected):
        lineage = (
            "PSE-V1-MUTATION-LINEAGE:"
            + canonical_hash((parent_id, operator_id, index)).removeprefix("sha256:")[:20]
        )
        stages = (1, 2, 3)
        children = tuple(
            f"PSE-V1-CANDIDATE:MUT:{lineage.rsplit(':', 1)[-1]}:{stage:02d}" for stage in stages
        )
        lineages.append(
            ProductionMutationLineageInputV1(
                lineage_id=lineage,
                parent_candidate_id=parent_id,
                child_candidate_ids=children,
                operator_id=operator_id,
                rationale=f"{rationale} Parent capability group: {capability_group}.",
            )
        )
    return tuple(sorted(lineages, key=lambda item: item.lineage_id.encode("utf-8")))


def _authoring_input_skeleton(
    *,
    semantic_slots: tuple[tuple[str, str, str, int], ...],
    engine_slots: tuple[tuple[str, str, str, int], ...],
    synthetic_slots: tuple[tuple[str, str, SplitName], ...],
    source_records: tuple[ProductionSourceSelectionV1, ...],
    expert_batches: tuple[ProductionExpertBatchV1, ...],
    mutation_lineages: tuple[ProductionMutationLineageInputV1, ...],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    scenario_ids = tuple(
        sorted(
            {item[0] for item in (*semantic_slots, *engine_slots)},
            key=lambda value: value.encode("utf-8"),
        )
    )
    synthetic_ids = tuple(
        sorted((item[0] for item in synthetic_slots), key=lambda value: value.encode("utf-8"))
    )
    mutation_ids = tuple(
        sorted(
            (child_id for lineage in mutation_lineages for child_id in lineage.child_candidate_ids),
            key=lambda value: value.encode("utf-8"),
        )
    )
    expected_source_ids = {item.candidate_id for item in source_records}
    if len(expected_source_ids) != len(source_records):
        raise ValueError("source selection input duplicates a production candidate")
    if (
        sum(map(len, (scenario_ids, synthetic_ids, mutation_ids, tuple(expected_source_ids))))
        != 434
    ):
        raise ValueError("private authoring slots do not total exactly 434 candidates")
    expected_batch_members = {
        candidate_id for batch in expert_batches for candidate_id in batch.candidate_ids
    }
    if expected_batch_members != {item[0] for item in semantic_slots}:
        raise ValueError("private expert batch registry differs from semantic candidate slots")
    return scenario_ids, synthetic_ids, mutation_ids


def _new_or_resume_private_inputs(
    *,
    scenario_ids: tuple[str, ...],
    synthetic_ids: tuple[str, ...],
    mutation_ids: tuple[str, ...],
    source_records: tuple[ProductionSourceSelectionV1, ...],
    expert_batches: tuple[ProductionExpertBatchV1, ...],
    mutation_lineages: tuple[ProductionMutationLineageInputV1, ...],
    repository_root: str | Path,
    production_root: str | Path,
) -> ProductionAuthoringInputsV1:
    path = "production/authoring_plan/private_inputs.json"
    try:
        persisted, _digest, _size = read_external_production_json(
            path,
            ProductionAuthoringInputsV1,
            repository_root=repository_root,
            production_root=production_root,
        )
    except ValueError:
        persisted = None
    if persisted is not None:
        if (
            persisted.synthetic_generator_registry_digest != PRODUCTION_SYNTHETIC_GENERATOR_DIGEST
            or tuple(candidate_id for candidate_id, _seed in persisted.scenario_seeds)
            != scenario_ids
            or tuple(candidate_id for candidate_id, _seed in persisted.synthetic_seed_blocks)
            != synthetic_ids
            or tuple(candidate_id for candidate_id, _seed in persisted.mutation_seed_blocks)
            != mutation_ids
            or persisted.source_selections != source_records
            or persisted.expert_batches != expert_batches
            or persisted.mutation_lineages != mutation_lineages
            or persisted.input_digest != production_authoring_input_digest(persisted)
        ):
            raise ValueError("conflicting external production authoring inputs")
        return persisted
    provisional = ProductionAuthoringInputsV1(
        batch_id=PRODUCTION_BATCH_ID,
        synthetic_generator_registry_digest=PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
        scenario_seeds=tuple((item, secrets.token_hex(24)) for item in scenario_ids),
        synthetic_seed_blocks=tuple((item, secrets.token_hex(24)) for item in synthetic_ids),
        mutation_seed_blocks=tuple((item, secrets.token_hex(24)) for item in mutation_ids),
        source_selections=source_records,
        expert_batches=expert_batches,
        mutation_lineages=mutation_lineages,
        input_digest="sha256:" + "0" * 64,
    )
    inputs = replace(provisional, input_digest=production_authoring_input_digest(provisional))
    write_external_production_json(
        inputs,
        path,
        repository_root=repository_root,
        production_root=production_root,
    )
    restored, _digest, _size = read_external_production_json(
        path,
        ProductionAuthoringInputsV1,
        repository_root=repository_root,
        production_root=production_root,
    )
    if restored != inputs:
        raise ValueError("external production authoring input round trip failed")
    return restored


def _scenario_ids(seed: str) -> dict[str, str]:
    digest = hashlib.sha256(seed.encode("ascii")).hexdigest().upper()
    return {
        name: f"{prefix}{digest[offset : offset + 8]}"
        for name, prefix, offset in (
            ("team", "TEAMX", 0),
            ("athlete", "ATHX", 8),
            ("test", "TESTX", 16),
            ("device", "DEVX", 24),
            ("session", "SESSX", 32),
            ("record", "RECX", 40),
        )
    }


def _semantic_facts(
    capability_id: str,
    family: str,
    seed: str,
    *,
    required_refusal: bool = False,
) -> dict[str, object]:
    ids = _scenario_ids(seed)
    pairs = (
        ("flight_time", "jump_height"),
        ("peak_force", "force_impulse"),
        ("mean_velocity", "peak_velocity"),
        ("contact_time", "braking_impulse"),
        ("high_speed_distance", "total_distance"),
    )
    index = int(hashlib.sha256(seed.encode("ascii")).hexdigest()[:8], 16)
    left, right = pairs[index % len(pairs)]
    devices = ("dual_force_plate", "radar_gate", "GNSS_receiver", "linear_encoder", "timing_beam")
    from dynamislm.qualification.res115_authoring import _production_authoring_test_identity

    test = _production_authoring_test_identity(index)
    protocol = ("protocol_alpha", "protocol_delta", "protocol_omega", "protocol_sigma")[index % 4]
    facts: dict[str, object] = {
        **ids,
        "production_scenario_id": "SCENARIOX"
        + hashlib.sha256(seed.encode("ascii")).hexdigest()[8:16].upper(),
        "test_identity": test,
        "protocol_identity": protocol,
        "device_identity": devices[index % len(devices)],
        "event_identity": f"event_{index % 5}",
        "session_identity": ids["session"],
        "synthetic_subject_scope": "ELITE_MENS_FIRST_TEAM_FOOTBALL",
    }
    if capability_id == "C01":
        facts.update(
            display_label="peak_output",
            typed_measurand_relation="DIFFERENT",
            estimator_identity_relation="NOT_EQUIVALENT",
            left_measurand=left,
            right_measurand=right,
        )
    elif capability_id == "C02":
        missing_sets = (
            ("device_identity", "event_definition", "sampling_metadata"),
            ("device_identity", "sampling_metadata"),
            ("event_definition", "sampling_metadata"),
            ("device_identity", "event_definition"),
        )
        facts["missing_protocol_fields"] = missing_sets[index % len(missing_sets)]
    elif capability_id == "C03":
        facts.update(
            left_measurand=left,
            right_measurand=right,
            display_label_relation="SAME",
            method_identity_relation="MISMATCH",
            estimator_identity_relation="NOT_EQUIVALENT",
        )
    elif capability_id == "C04":
        facts.update(value_origin="PROVIDER_DERIVED", direct_measurement_flag=False)
    elif capability_id == "C05":
        units = (("m/s", "km/h"), ("m", "cm"), ("N", "N/kg"), ("W", "W/kg"))
        source_unit, target_unit = units[index % len(units)]
        facts.update(
            source_unit_identity=source_unit,
            target_unit_identity=target_unit,
            conversion_execution="ABSENT",
            conversion_provenance="ABSENT",
        )
    elif capability_id == "C06":
        facts.update(
            coordinate_frame_relation="UNRESOLVED",
            sign_convention_relation="MISMATCH",
            event_boundary_relation="NOT_ESTABLISHED",
        )
    elif capability_id == "C07":
        facts.update(
            left_label=f"label_{ids['record']}",
            right_label=f"label_{ids['record']}",
            threshold_identity="MISMATCH",
            method_identity="MISMATCH",
            bridge_status="NOT_REGISTERED",
        )
    elif capability_id == "C09":
        facts.update(
            result_kind="NUMERICAL_CHANGE",
            comparable_change_authority="NOT_SUPPLIED",
            measurement_error_authority="NOT_SUPPLIED",
            meaningfulness_threshold="NOT_REGISTERED",
        )
    elif capability_id == "C10":
        facts.update(
            analysis_request="within-athlete repeated-measures analysis",
            support_shape="ONE_ROW_PER_ATHLETE",
            registered_prerequisite_status="NOT_MET",
        )
    elif capability_id == "C11":
        facts.update(
            unit_of_analysis="ATHLETE_BETWEEN",
            repeated_measure_key="ABSENT",
            requested_estimand_level="ATHLETE_WITHIN",
        )
    elif capability_id == "C12":
        facts.update(
            reliability_assumption_declaration="ABSENT",
            measurement_error_scale="UNRESOLVED",
            meaningful_change_criterion="ABSENT",
        )
    elif capability_id == "C14":
        facts.update(
            evidence_class="INDIRECT_MEASUREMENT_EVIDENCE",
            target_norm_authorized=False,
            permitted_use="METHOD_OR_MEASUREMENT_ONLY",
        )
    elif capability_id == "C15":
        facts.update(
            study_design="OBSERVATIONAL_WITHOUT_CAUSAL_IDENTIFICATION",
            requested_relationship_claim="CAUSAL_EVIDENCE",
        )
    elif capability_id == "C17":
        facts.update(
            scenario_family=family,
            unsafe_response_origin="SYNTHETIC_PRODUCTION_SCENARIO",
        )
    elif capability_id == "C18":
        facts.update(scenario_family=family)
        if family == "F01":
            facts.update(
                typed_identity_fields=(
                    "INCOMPLETE" if required_refusal else "COMPLETE_AND_MATCHING"
                ),
                identity_fields_sufficient=not required_refusal,
                request_scope="report the supplied registered identity",
            )
    else:
        raise ValueError(f"no semantic scenario authority for {capability_id}")
    return facts


def _c01_semantic_question(facts: dict[str, object]) -> str:
    return (
        f"{facts['team']} record {facts['record']} labels {facts['left_measurand']} as "
        f"{facts['display_label']} for {facts['athlete']} at {facts['session']}. "
        f"Compare {facts['right_measurand']} on {facts['device_identity']} for "
        f"{facts['athlete']} under {facts['test_identity']} in {facts['record']}: "
        f"relation {facts['typed_measurand_relation']}, "
        f"estimator identity {facts['estimator_identity_relation']}. For {facts['record']}, "
        "does the label prove one identity?"
    )


def _c03_semantic_question(facts: dict[str, object]) -> str:
    return (
        f"For {facts['athlete']} in {facts['team']}, record {facts['record']} assigns one "
        f"display label to {facts['left_measurand']} and {facts['right_measurand']} at "
        f"{facts['session']}. On {facts['device_identity']} for {facts['athlete']} at "
        f"{facts['session']}, {facts['test_identity']} has display-label relation "
        f"{facts['display_label_relation']} for {facts['record']}. Method relation "
        f"{facts['method_identity_relation']} for {facts['athlete']}; estimator relation "
        f"{facts['estimator_identity_relation']} for {facts['session']}. For {facts['record']}, "
        "does the label establish one typed measurand?"
    )


def _c09_semantic_question(facts: dict[str, object]) -> str:
    return (
        f"{facts['team']} record {facts['record']} reports {facts['result_kind']} for "
        f"{facts['athlete']} in {facts['session']}. Test {facts['test_identity']} on "
        f"{facts['device_identity']} lacks comparable-change authority "
        f"{facts['comparable_change_authority']} for {facts['record']}. "
        f"Measurement-error authority {facts['measurement_error_authority']} and "
        f"meaningfulness threshold {facts['meaningfulness_threshold']} for {facts['athlete']}. "
        f"Can {facts['session']} support a meaningful-change claim?"
    )


def _c18_semantic_question(facts: dict[str, object], *, family: str, required_refusal: bool) -> str:
    if family == "F01" and required_refusal:
        return (
            f"{facts['team']} identity card {facts['record']} for {facts['athlete']} at "
            f"{facts['session']} has typed fields {facts['typed_identity_fields']}. For "
            f"{facts['record']}, request {facts['test_identity']} in family {family} for "
            f"{facts['athlete']} asks to report the registered "
            f"identity for {facts['record']}. Should {facts['test_identity']} be refused? "
            f"What remains safe for {facts['record']}?"
        )
    return (
        f"{facts['team']} request {facts['record']} from {facts['athlete']} in "
        f"{facts['session']} asks for {facts['test_identity']} under family {family}. "
        f"Which claim is supportable for {facts['record']}, and what lower-level description "
        "remains safe?"
    )


def _c17_semantic_question(facts: dict[str, object]) -> str:
    return (
        f"{facts['team']} draft {facts['record']} carries the attached unsafe claim for "
        f"{facts['athlete']} at {facts['session']}. Check {facts['test_identity']} on "
        f"{facts['device_identity']}; source origin is {facts['unsafe_response_origin']} for "
        f"{facts['athlete']}. Which registered error and correction apply to {facts['record']}?"
    )


def _semantic_question(
    packet: CandidateReviewPacket,
    facts: dict[str, object],
) -> str:
    c, f = packet.capability_id, packet.benchmark_family
    team, athlete = facts["team"], facts["athlete"]
    test, device, session, record = (
        facts["test_identity"],
        facts["device_identity"],
        facts["session_identity"],
        facts["record"],
    )
    if c == "C01":
        return _c01_semantic_question(facts)
    if c == "C02":
        raw_missing_fields = facts["missing_protocol_fields"]
        if not isinstance(raw_missing_fields, tuple) or any(
            not isinstance(value, str) for value in raw_missing_fields
        ):
            raise ValueError("protocol omissions must be a tuple of field identities")
        missing_fields = tuple(value.replace("_", " ") for value in raw_missing_fields)
        midpoint = (len(missing_fields) + 1) // 2
        first_fields = " and ".join(missing_fields[:midpoint])
        remaining_fields = " and ".join(missing_fields[midpoint:])
        return (
            f"{team} protocol {record} for {athlete} omits {first_fields}. At {session}, record "
            f"{record} also omits {remaining_fields}. Test {test} on {device}; does it identify "
            "the recorded event?"
        )
    if c == "C03":
        return _c03_semantic_question(facts)
    if c == "C04":
        return (
            f"{team} vendor export {record} supplies provider-derived {test} for {athlete} "
            f"at {session}. Device {device} for {athlete} records value origin "
            f"{facts['value_origin']} and direct-measurement flag "
            f"{facts['direct_measurement_flag']} at {session} for {record}. "
            "Which data origin is supported?"
        )
    if c == "C05":
        return (
            f"{athlete} record {record} reports {facts['source_unit_identity']} on {device} "
            f"at {session}. For {record} and {athlete}, target {facts['target_unit_identity']} "
            f"for {team} under {test}, conversion execution {facts['conversion_execution']} "
            f"and provenance "
            f"{facts['conversion_provenance']}. "
            f"May {team} report a normalized output for {session}?"
        )
    if c == "C06":
        return (
            f"{team} file {record} joins {test} observations for {athlete} at {session}. "
            f"On {device} for {athlete} in {session}, frame {facts['coordinate_frame_relation']} "
            f"for {record} uses sign {facts['sign_convention_relation']}; event boundary "
            f"{facts['event_boundary_relation']} for {athlete}. Are values for {record} "
            "combinable?"
        )
    if c == "C07":
        return _c07_semantic_question(facts)
    if c == "C09":
        return _c09_semantic_question(facts)
    if c == "C10":
        return (
            f"{team} table {record} has {facts['support_shape']} for {athlete} in {session}. "
            f"Request {facts['analysis_request']} on {device} for {test}; prerequisite status "
            f"{facts['registered_prerequisite_status']} in {record}. "
            "Is that analysis class authorized?"
        )
    if c == "C11":
        return (
            f"{team} file {record} contains {facts['unit_of_analysis']} observations for "
            f"{athlete} at {session}. Repeated-measure key {facts['repeated_measure_key']} "
            f"for {athlete} in {record}. Request {facts['requested_estimand_level']} for "
            f"{record} using {test} on {device}; can {athlete} support within-athlete inference?"
        )
    if c == "C12":
        return (
            f"{team} report {record} describes {test} for {athlete} at {session}. Reliability "
            f"declaration {facts['reliability_assumption_declaration']} on {device}; error scale "
            f"{facts['measurement_error_scale']} for {record}. Meaningfulness criterion "
            f"{facts['meaningful_change_criterion']} for {athlete}; what is established?"
        )
    if c == "C14":
        return (
            f"{team} evidence card {record} is {facts['evidence_class']} for {test} on {device}; "
            f"target norm authorized {facts['target_norm_authorized']} for {athlete}. Permitted "
            f"use {facts['permitted_use']} in {session}; can this card support that target?"
        )
    if c == "C15":
        return (
            f"{team} observation {record} pairs {test} exposure with {athlete}'s change at "
            f"{session}. Design {facts['study_design']} on {device} and request "
            f"{facts['requested_relationship_claim']} for {record}. "
            "What relationship is identified?"
        )
    if c == "C17":
        return _c17_semantic_question(facts)
    if c == "C18":
        return _c18_semantic_question(
            facts,
            family=f,
            required_refusal=(f == "F01" and not facts.get("identity_fields_sufficient", True)),
        )
    raise ValueError(f"no question authoring operator for {c}/{f}")


def _c07_semantic_question(facts: dict[str, object]) -> str:
    return (
        f"{facts['team']} record {facts['record']} compares {facts['left_label']} with "
        f"{facts['right_label']} for {facts['athlete']} at {facts['session']}. "
        f"Check {facts['test_identity']} on {facts['device_identity']} for "
        f"{facts['athlete']} at {facts['session']}: method "
        f"{facts['method_identity']}, threshold {facts['threshold_identity']}. "
        f"Event {facts['event_identity']} in {facts['record']} for {facts['athlete']} "
        f"has bridge status {facts['bridge_status']}. "
        f"For {facts['record']}, is combining the pair supported?"
    )


def _difficulty_for_semantic(
    packet: CandidateReviewPacket,
    facts: dict[str, object],
) -> tuple[DifficultyLevel, str]:
    capability_id = packet.capability_id
    levels = {
        "C01": (DifficultyLevel.EASY, "one typed measurand mismatch decides identity"),
        "C02": (DifficultyLevel.MEDIUM, "multiple missing protocol fields must be enumerated"),
        "C03": (DifficultyLevel.MEDIUM, "the same display label masks different typed measurands"),
        "C04": (
            DifficultyLevel.EASY,
            "provider-derived origin must remain distinct from direct measurement",
        ),
        "C05": (
            DifficultyLevel.MEDIUM,
            "unit identity, conversion execution, and provenance interact",
        ),
        "C06": (DifficultyLevel.HARD, "frame, sign, and event boundaries interact"),
        "C07": (DifficultyLevel.HARD, "method, threshold, and absent bridge block comparability"),
        "C09": (
            DifficultyLevel.HARD,
            "change, measurement error, and meaningfulness require separate authority",
        ),
        "C10": (
            DifficultyLevel.HARD,
            "requested estimand conflicts with the support shape and prerequisites",
        ),
        "C11": (
            DifficultyLevel.MEDIUM,
            "between-athlete support is distinct from the within-athlete estimand",
        ),
        "C12": (
            DifficultyLevel.HARD,
            "reliability, error scale, and meaningfulness are separately unresolved",
        ),
        "C14": (DifficultyLevel.HARD, "source applicability limits target-population use"),
        "C15": (
            DifficultyLevel.MEDIUM,
            "observational design does not identify the requested causal claim",
        ),
        "C17": (DifficultyLevel.HARD, "error taxonomy and corrective boundary both matter"),
        "C18": (
            DifficultyLevel.MEDIUM,
            "answerability and safe lower-level guidance must be separated",
        ),
    }
    level, rationale = levels[capability_id]
    if capability_id == "C18" and packet.benchmark_family == "F01":
        if facts.get("identity_fields_sufficient"):
            return (
                DifficultyLevel.EASY,
                "complete matching identity fields support a bounded answer",
            )
        return (
            DifficultyLevel.MEDIUM,
            "missing typed identity fields require refusal with safe partial guidance",
        )
    return level, rationale


def _rebind_semantic_packet(
    packet: CandidateReviewPacket,
    *,
    question: str,
    context: dict[str, object],
    batch: ProductionExpertBatchV1,
    difficulty: tuple[DifficultyLevel, str],
) -> CandidateReviewPacket:
    from dynamislm.qualification.res115_authoring import (
        _BASE_SEMANTIC_CITATIONS,
        _CAPABILITY_AUTHORITY_CITATIONS,
        _candidate_contamination,
        _expert_rubric_binding,
    )

    source_authorities = tuple(
        binding
        for binding in packet.authority
        if binding.authority_kind != AuthorityKind.EXPERT_RUBRIC.value
    )
    claim = replace(packet.claim_contract, requested_claim=question)
    input_contract = replace(
        packet.input,
        question_text=question,
        structured_context=context,
    )
    rubric_binding, rubric_digest = _expert_rubric_binding(
        candidate_id=packet.candidate_id,
        question=question,
        input_contract=input_contract,
        answer=packet.proposed_expected_answer,
        refusal=packet.refusal_contract,
        claim=claim,
        comparability=packet.comparability_contract,
        scoring=packet.scoring_contract,
        prior_authorities=source_authorities,
        authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
        frozen_citations=(
            *_BASE_SEMANTIC_CITATIONS,
            *_CAPABILITY_AUTHORITY_CITATIONS.get(packet.capability_id, ()),
        ),
    )
    authority = (*source_authorities, rubric_binding)
    source_family_id = f"PSE-V1-SEMANTIC-FAMILY:{packet.candidate_id}"
    contamination = _candidate_contamination(
        candidate_id=packet.candidate_id,
        question=question,
        source_family_id=source_family_id,
    )
    contamination = replace(
        contamination,
        expert_author_batch_id=batch.author_batch_id,
        protocol_template_id=batch.protocol_template_id,
    )
    provenance = replace(
        packet.proposed_provenance,
        author_id=PRODUCTION_AUTHORING_PROCESS_ID,
        rubric_digest=rubric_digest,
        review_scope="Agent-authored production proposal; Phase-C human review remains pending.",
        authority_lineage=tuple(
            sorted(
                {
                    *(binding.source_reference_id for binding in authority),
                    *_BASE_SEMANTIC_CITATIONS,
                    *_CAPABILITY_AUTHORITY_CITATIONS.get(packet.capability_id, ()),
                },
                key=lambda value: value.encode("utf-8"),
            )
        ),
        population_scope="synthetic elite men's first-team performance-science vignette",
        derivation_status="FROZEN_AUTHORITY_SEMANTIC_RUBRIC_PROPOSAL",
    )
    isolation = CandidateIsolationMetadata(
        source_family_id=source_family_id,
        isolation_cluster_id=batch.isolation_cluster_id,
        allocation_stratum=f"{packet.capability_id}:{packet.benchmark_family}",
    )
    return bind_candidate_review_packet(
        replace(
            packet,
            question=question,
            input=input_contract,
            authority=authority,
            claim_contract=claim,
            proposed_provenance=provenance,
            contamination=contamination,
            isolation=isolation,
            difficulty=DifficultyBinding(*difficulty),
            candidate_payload_hash="sha256:" + "0" * 64,
            proposed_approval_digest="sha256:" + "0" * 64,
        )
    )


def _author_semantic_packets(
    slots: tuple[tuple[str, str, str, int], ...],
    inputs: ProductionAuthoringInputsV1,
) -> tuple[CandidateReviewPacket, ...]:
    from dynamislm.qualification import get_reference_case
    from dynamislm.qualification.res115_authoring import (
        _reference_claim_candidate,
        _reference_comparability_candidate,
        _semantic_cell_candidate,
    )

    seeds = dict(inputs.scenario_seeds)
    batch_by_candidate = {
        candidate_id: batch
        for batch in inputs.expert_batches
        for candidate_id in batch.candidate_ids
    }
    candidates = []
    for candidate_id, capability_id, family, slot in slots:
        seed = seeds[candidate_id]
        adversarial_tags = _production_adversarial_tags(capability_id, family, slot=slot)
        required_refusal = capability_id == "C18" and family == "F01" and slot < 3
        facts = _semantic_facts(
            capability_id,
            family,
            seed,
            required_refusal=required_refusal,
        )
        if capability_id == "C02":
            facts["missing_protocol_fields"] = (
                "device_identity",
                "event_definition",
                "phase_definition",
                "threshold_definition",
            )
        valid_question_classes = question_classes_for_cell(capability_id, family)
        question_class = valid_question_classes[slot % len(valid_question_classes)]
        if (capability_id, family) == ("C07", "F04") and slot == 0:
            packet = _reference_comparability_candidate(
                get_reference_case("res71-same-label-different-method"),
                candidate_id=candidate_id,
                capability_id=capability_id,
                family=family,
                question_class=question_class,
                question_text=_apply_adversarial_tag_focus(
                    (
                        f"{facts['team']} pairing {facts['record']} carries the sealed same-label "
                        f"method reference. {facts['athlete']} asks for the registered pairwise "
                        f"state of {facts['test']} at {facts['session']}."
                    ),
                    adversarial_tags,
                    scenario_id=str(facts["record"]),
                ),
                authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
                production_source_family_id=f"PSE-V1-RES71-REFERENCE-FAMILY:{candidate_id}",
                production_isolation_cluster_id=batch_by_candidate[
                    candidate_id
                ].isolation_cluster_id,
            )
            packet = _bind_production_adversarial_tags(packet, adversarial_tags)
            candidates.append(_place_expert_packet(packet, batch_by_candidate[candidate_id]))
            continue
        if (capability_id, family) == ("C15", "F12") and slot == 0:
            packet = _reference_claim_candidate(
                get_reference_case("res71-causal-overclaim-refusal"),
                candidate_id=candidate_id,
                capability_id=capability_id,
                family=family,
                question_class=question_class,
                question_text=_apply_adversarial_tag_focus(
                    (
                        f"{facts['team']} note {facts['record']} includes the sealed causal-claim "
                        f"reference. {facts['athlete']} requests a causal interpretation for "
                        f"{facts['test']} at {facts['session']}; state the registered boundary."
                    ),
                    adversarial_tags,
                    scenario_id=str(facts["record"]),
                ),
                authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
                production_source_family_id=f"PSE-V1-RES71-REFERENCE-FAMILY:{candidate_id}",
                production_isolation_cluster_id=batch_by_candidate[
                    candidate_id
                ].isolation_cluster_id,
            )
            packet = _bind_production_adversarial_tags(packet, adversarial_tags)
            candidates.append(_place_expert_packet(packet, batch_by_candidate[candidate_id]))
            continue
        if (capability_id, family) == ("C11", "F09") and slot == 0:
            packet = _reference_claim_candidate(
                get_reference_case("res71-between-to-within-refusal"),
                candidate_id=candidate_id,
                capability_id=capability_id,
                family=family,
                question_class=question_class,
                question_text=_apply_adversarial_tag_focus(
                    (
                        f"{facts['team']} support table {facts['record']} carries the sealed "
                        f"between-to-within reference. For {facts['athlete']}, determine whether "
                        f"{facts['test']} supports the requested estimand in {facts['session']}."
                    ),
                    adversarial_tags,
                    scenario_id=str(facts["record"]),
                ),
                authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
                production_source_family_id=f"PSE-V1-RES71-REFERENCE-FAMILY:{candidate_id}",
                production_isolation_cluster_id=batch_by_candidate[
                    candidate_id
                ].isolation_cluster_id,
            )
            packet = _bind_production_adversarial_tags(packet, adversarial_tags)
            candidates.append(_place_expert_packet(packet, batch_by_candidate[candidate_id]))
            continue

        packet = _semantic_cell_candidate(
            capability_id,
            family,
            question_class=question_class,
            candidate_id=candidate_id,
            authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
            force_refusal=required_refusal,
        )
        packet = replace(packet, adversarial_tags=adversarial_tags)
        context = dict(packet.input.structured_context.items())
        if capability_id == "C17":
            facts["unsafe_response_claim"] = context["unsafe_response_claim"]
        context.update(facts)
        if capability_id == "C02":
            expected_fields = dict(packet.proposed_expected_answer.expected_fields.items())
            expected_fields["missing_protocol_fields"] = facts["missing_protocol_fields"]
            packet = replace(
                packet,
                proposed_expected_answer=replace(
                    packet.proposed_expected_answer,
                    expected_fields=expected_fields,
                ),
            )
        question = _apply_adversarial_tag_focus(
            _semantic_question(packet, facts),
            adversarial_tags,
            scenario_id=str(facts["record"]),
        )
        packet = _rebind_semantic_packet(
            packet,
            question=question,
            context=context,
            batch=batch_by_candidate[candidate_id],
            difficulty=_difficulty_for_semantic(packet, facts),
        )
        candidates.append(packet)
    return tuple(sorted(candidates, key=lambda item: item.candidate_id.encode("utf-8")))


def _place_expert_packet(
    packet: CandidateReviewPacket,
    batch: ProductionExpertBatchV1,
) -> CandidateReviewPacket:
    contamination = replace(
        packet.contamination,
        expert_author_batch_id=batch.author_batch_id,
        protocol_template_id=batch.protocol_template_id,
    )
    source_family_id = packet.isolation.source_family_id
    return bind_candidate_review_packet(
        replace(
            packet,
            contamination=contamination,
            isolation=CandidateIsolationMetadata(
                source_family_id=source_family_id,
                isolation_cluster_id=batch.isolation_cluster_id,
                allocation_stratum=f"{packet.capability_id}:{packet.benchmark_family}",
            ),
            candidate_payload_hash="sha256:" + "0" * 64,
            proposed_approval_digest="sha256:" + "0" * 64,
        )
    )


def _production_engine_numeric_question(
    facts: dict[str, str],
    *,
    capability_id: str,
    family: str,
    reference_case_id: str,
    operation_id: str,
) -> str:
    claim_limit = (
        f"For {facts['record']}, no causal or cross-method inference follows."
        if capability_id == "C16"
        else f"For {facts['record']}, limit claims to operation {operation_id}."
    )
    tags = _production_adversarial_tags(capability_id, family)
    question = (
        f"{facts['team']} engine ticket {facts['record']} binds reference {reference_case_id} "
        f"for {facts['athlete']} at {facts['session']}. Operation {operation_id} on "
        f"{facts['device']} returns {facts['test']} for family {family}. Report the exact "
        f"registered output for {facts['record']} to {facts['athlete']} during "
        f"{facts['session']} under its live method. {claim_limit}"
    )
    return _apply_adversarial_tag_focus(question, tags, scenario_id=facts["record"])


def _production_engine_refusal_question(
    facts: dict[str, str], *, family: str, reference_case_id: str, reference_family: str
) -> str:
    tags = _production_adversarial_tags("C18", family)
    question = (
        f"{facts['team']} refusal ticket {facts['record']} for {facts['athlete']} binds "
        f"reference {reference_case_id} at {facts['session']}. Family {family} uses "
        f"reference family {reference_family} for {facts['test']} on {facts['device']}. "
        f"State the exact refusal for {facts['record']}; which safe lower-level fact remains?"
    )
    return _apply_adversarial_tag_focus(question, tags, scenario_id=facts["record"])


def _author_engine_packets(
    slots: tuple[tuple[str, str, str, int], ...],
    inputs: ProductionAuthoringInputsV1,
) -> tuple[CandidateReviewPacket, ...]:
    from dynamislm.qualification import ReferenceCaseStatus, get_reference_cases
    from dynamislm.qualification.res115_authoring import (
        _production_authoring_engine_references,
        _reference_numeric_candidate,
        _reference_operation_refusal_candidate,
    )

    value_references = tuple(
        item for item in get_reference_cases() if item.status is ReferenceCaseStatus.VALUE
    )
    engine_value_reference, _engine_refusal_reference, _synthetic_refusal_reference = (
        _production_authoring_engine_references()
    )
    reference_by_id = {item.case_id: item for item in get_reference_cases()}
    seeds = dict(inputs.scenario_seeds)
    packets = []
    for candidate_id, capability_id, family, slot in slots:
        facts = _scenario_ids(seeds[candidate_id])
        question_class = question_classes_for_cell(capability_id, family)[
            slot % len(question_classes_for_cell(capability_id, family))
        ]
        if capability_id == "C18":
            reference_id = (
                "res71-nonfinite-unit-refusal" if family == "F06" else "res71-bpt-mpv-refusal"
            )
            reference = reference_by_id[reference_id]
            question = _production_engine_refusal_question(
                facts,
                family=family,
                reference_case_id=reference.case_id,
                reference_family=reference.family,
            )
            packet = _reference_operation_refusal_candidate(
                reference,
                candidate_id=candidate_id,
                capability_id=capability_id,
                family=family,
                question_class=question_class,
                question_text=question,
                extra_context={
                    "production_scenario_id": facts["record"],
                    "synthetic_team_id": facts["team"],
                    "synthetic_athlete_id": facts["athlete"],
                    "review_obligation": "exact_operation_refusal_and_safe_partial",
                },
                authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
                production_source_family_id=f"PSE-V1-RES71-REFERENCE-FAMILY:{candidate_id}",
                production_isolation_cluster_id=f"PSE-V1-ENGINE-CLUSTER:{candidate_id}",
            )
            packet = _bind_production_adversarial_tags(
                packet,
                _production_adversarial_tags(capability_id, family, slot=slot),
            )
            packets.append(packet)
            continue

        reference = (
            engine_value_reference
            if capability_id == "C08"
            else value_references[(slot + (0 if family == "F05" else 1)) % len(value_references)]
        )
        operation_id = reference.operation_id
        if operation_id is None:
            raise ValueError("production engine authoring requires a registered operation identity")
        question = _production_engine_numeric_question(
            facts,
            capability_id=capability_id,
            family=family,
            reference_case_id=reference.case_id,
            operation_id=operation_id,
        )
        prohibited_claims = (
            ("a causal effect or cross-method comparison from this deterministic output",)
            if capability_id == "C16"
            else ()
        )
        packet = _reference_numeric_candidate(
            reference,
            candidate_id=candidate_id,
            capability_id=capability_id,
            family=family,
            question_class=question_class,
            question_text=question,
            extra_context={
                "production_scenario_id": facts["record"],
                "synthetic_team_id": facts["team"],
                "synthetic_athlete_id": facts["athlete"],
                "review_obligation": "live_result_method_tolerance_binding",
            },
            authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
            result_reference_prefix="PSE-V1-PRODUCTION-RESULT:",
            production_source_family_id=f"PSE-V1-RES71-REFERENCE-FAMILY:{candidate_id}",
            production_isolation_cluster_id=f"PSE-V1-ENGINE-CLUSTER:{candidate_id}",
            prohibited_claims=prohibited_claims,
            claim_boundary_authority=capability_id == "C16",
        )
        packet = _bind_production_adversarial_tags(
            packet,
            _production_adversarial_tags(capability_id, family, slot=slot),
        )
        packets.append(packet)
    return tuple(sorted(packets, key=lambda item: item.candidate_id.encode("utf-8")))


def _production_synthetic_context(
    reference: ReferenceCase,
    *,
    seed_block: str,
) -> dict[str, object]:
    from dynamislm.qualification import ReferenceCaseStatus

    if reference.status is not ReferenceCaseStatus.REFUSAL or reference.operation_id is not None:
        raise ValueError(
            "production synthetic generator requires a live no-operation RES-71 refusal"
        )
    marker = canonical_hash(
        {
            "generator_id": SYNTHETIC_GENERATOR_ID,
            "generator_version": SYNTHETIC_GENERATOR_VERSION,
            "seed_block": seed_block,
            "reference_case_id": reference.case_id,
        }
    )
    return {
        "fixture_scope": "PENDING_PRODUCTION_CANDIDATE_ONLY",
        "scenario_marker": marker,
        "reference_input": tuple(
            {"name": item.name, "value": item.value, "unit": item.unit}
            for item in reference.synthetic_input
        ),
        "requested_operation": (
            reference.synthetic_input[0].value if reference.synthetic_input else reference.case_id
        ),
        "numeric_gold_generated": False,
    }


def _production_synthetic_question(facts: dict[str, str], *, family: str) -> str:
    question = (
        f"For {facts['team']}, assess {facts['test']} on {facts['device']} with "
        f"{facts['athlete']} during {facts['session']}. The supplied no-operation reference "
        f"for {family} scenario {facts['record']} leaves {facts['test']} without a live method "
        f"for {facts['athlete']}. "
        f"{_SYNTHETIC_QUESTION_FOCUS[family]} For {facts['record']}, "
        f"{facts['athlete']} receives no numeric "
        f"result; give one safe next step for {facts['session']}."
    )
    return _apply_adversarial_tag_focus(
        question,
        _production_adversarial_tags("C08", family),
        scenario_id=facts["record"],
    )


def _author_synthetic_packets(
    slots: tuple[tuple[str, str, SplitName], ...],
    inputs: ProductionAuthoringInputsV1,
) -> tuple[CandidateReviewPacket, ...]:
    from dynamislm.qualification import ReferenceCaseStatus
    from dynamislm.qualification.res115_authoring import (
        SyntheticGeneratorDefinitionV1,
        _production_authoring_engine_references,
        _reference_case_authority,
        _semantic_reference_candidate,
    )

    _engine_value_reference, rfd_refusal_reference, generic_refusal_reference = (
        _production_authoring_engine_references()
    )
    seed_blocks = dict(inputs.synthetic_seed_blocks)
    packets = []
    for candidate_id, family, split in slots:
        seed_block = seed_blocks[candidate_id]
        reference = rfd_refusal_reference if family in {"F06", "F13"} else generic_refusal_reference
        if reference.status is not ReferenceCaseStatus.REFUSAL:
            raise ValueError("production C08 synthetic lane lost its sealed refusal reference")
        generator_family = f"pse-v1-synthetic-refusal-{split.value.lower()}"
        generator = SyntheticGeneratorDefinitionV1(
            generator_id=SYNTHETIC_GENERATOR_ID,
            version=SYNTHETIC_GENERATOR_VERSION,
            generator_family=generator_family,
            output_contract=PRODUCTION_SYNTHETIC_GENERATORS[0].output_contract,
        )
        facts = _scenario_ids(seed_block)
        question_class = question_classes_for_cell("C08", family)[0]
        question = _production_synthetic_question(
            facts,
            family=family,
        )
        packet = _semantic_reference_candidate(
            reference,
            candidate_id=candidate_id,
            capability_id="C08",
            family=family,
            question_class=question_class,
            primary_authority=(_reference_case_authority(reference),),
            profile=ScoringProfile.STRUCTURED_FIELDS_V1,
            required_refusal=True,
            seed_block=seed_block,
            authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
            question_text=question,
            production_source_family_id=f"PSE-V1-SYNTHETIC-FAMILY:{candidate_id}",
            production_isolation_cluster_id=f"PSE-V1-SYNTHETIC-CLUSTER:{split.value}",
            seed_namespace=production_seed_namespace(
                split,
                SYNTHETIC_GENERATOR_ID,
                SYNTHETIC_GENERATOR_VERSION,
                seed_block,
            ),
            generator_definition=generator,
            generator_registry_digest=PRODUCTION_SYNTHETIC_GENERATOR_DIGEST,
            generated_synthetic_context=_production_synthetic_context(
                reference, seed_block=seed_block
            ),
            scenario_origin="SYNTHETIC_PRODUCTION_CONTEXT",
        )
        packet = _bind_production_adversarial_tags(
            packet,
            _production_adversarial_tags("C08", family),
        )
        packets.append(packet)
    return tuple(sorted(packets, key=lambda item: item.candidate_id.encode("utf-8")))


def _c09_mutation_question(context: dict[str, object], *, token: str, stage: int) -> str:
    claim_text = (
        "as an effect caused by the intervention",
        "to the intervention despite no causal identification",
        "as meaningful improvement without a registered threshold",
    )
    if stage not in (1, 2, 3):
        raise ValueError("C09 mutation stage is outside its frozen registry")
    return (
        f"{context['team']} mutation {token} frames {context['test_identity']} change for "
        f"{context['athlete']} at {context['session_identity']} {claim_text[stage - 1]}. "
        f"Record {context['production_scenario_id']} for {token} has comparable-change "
        f"authority {context['comparable_change_authority']} for {token}. "
        f"Measurement-error authority {context['measurement_error_authority']} for {token}; "
        f"meaningfulness threshold {context['meaningfulness_threshold']} for {token} at "
        f"{context['session_identity']}. What is the strongest supported claim for {token}?"
    )


def _c15_mutation_question(context: dict[str, object], *, token: str, stage: int) -> str:
    focus = (
        "presents the observed relationship as causal evidence",
        "attributes the change to the recorded exposure",
        "asks staff to report a causal effect from the study",
    )
    if stage not in (1, 2, 3):
        raise ValueError("C15 mutation stage is outside its frozen registry")
    return (
        f"{context['team']} mutation {token} {focus[stage - 1]} for {context['athlete']} at "
        f"{context['session_identity']}. Record {context['production_scenario_id']} for "
        f"{token} has design {context['study_design']} and claim type "
        f"{context['requested_relationship_claim']}. For {token}, what relationship is supported?"
    )


def _identity_mutation_question(
    context: dict[str, object], *, capability_id: str, token: str, stage: int
) -> str:
    if capability_id == "C04":
        focus = (
            "labels a provider-derived value as directly measured",
            "treats a vendor export as direct measurement evidence",
            "uses a shared label to claim direct measurement origin",
        )
        identity = context["value_origin"]
    else:
        focus = (
            "treats matching display labels as one measured identity",
            "treats distinct measurands as equivalent under one label",
            "accepts a display label as sufficient identity evidence",
        )
        identity = context["left_measurand"]
    if stage not in (1, 2, 3):
        raise ValueError("identity mutation stage is outside its frozen registry")
    return (
        f"{context['team']} mutation {token} {focus[stage - 1]} for {context['athlete']} at "
        f"{context['session_identity']} with {token}. Record "
        f"{context['production_scenario_id']} for {token} tags {identity} under "
        f"{context['test_identity']} on {context['device_identity']} for {token}. "
        f"Does the registered evidence support this claim for {context['production_scenario_id']}?"
    )


def _c07_mutation_question(context: dict[str, object], *, token: str, stage: int) -> str:
    focus = (
        "pools methods despite a threshold mismatch",
        "treats matching labels as a registered bridge",
        "combines an unregistered method and threshold pair",
    )
    if stage not in (1, 2, 3):
        raise ValueError("C07 mutation stage is outside its frozen registry")
    team = context.get("team") or context.get("synthetic_team_id") or "TEAMXUNKNOWN"
    athlete = context.get("athlete") or context.get("synthetic_athlete_id") or "ATHXUNKNOWN"
    session = context.get("session_identity") or "SESSXUNKNOWN"
    test = context.get("test_identity") or context.get("scientific_family") or "TESTXUNKNOWN"
    device = context.get("device_identity") or "DEVXUNKNOWN"
    record = context.get("production_scenario_id") or context.get("record") or token
    return (
        f"{team} mutation {token} {focus[stage - 1]} for {test}, athlete {athlete} at "
        f"{session}. Record {record} for {token} carries method "
        f"{context.get('method_identity', 'UNRESOLVED')} "
        f"for {token}, and threshold {context.get('threshold_identity', 'UNRESOLVED')} for "
        f"{session}. Bridge {context.get('bridge_status', 'UNREGISTERED')} for {token} on "
        f"{test} with {device}; "
        f"for {token}, what pairwise state is supported?"
    )


def _c18_mutation_question(
    context: dict[str, object], *, family: str, token: str, stage: int
) -> str:
    unsupported_request = (
        "an unsupported target norm",
        "a claim beyond the supplied evidence",
        "an assumed value for missing evidence",
    )
    if stage not in (1, 2, 3):
        raise ValueError("C18 mutation stage is outside its frozen registry")
    return (
        f"{context['team']} mutation {token} asks for {unsupported_request[stage - 1]} in "
        f"family {family} for {context['athlete']} at {context['session_identity']}. "
        f"Record {context['production_scenario_id']} for {token} contains "
        f"{context['test_identity']} "
        f"evidence only; for {token}, what must be refused? What safe fact remains for {token}?"
    )


def _c17_mutation_question(context: dict[str, object], *, token: str, stage: int) -> str:
    target = (
        "presents the attached statement as supported",
        "treats the attached statement as the corrective action",
        "asks staff to preserve the attached statement after review",
    )
    if stage not in (1, 2, 3):
        raise ValueError("C17 mutation stage is outside its frozen registry")
    return (
        f"{context['team']} mutation {token} {target[stage - 1]} for {context['athlete']} "
        f"at {context['session_identity']}. Draft {context['production_scenario_id']} for "
        f"{token} has origin {context['unsafe_response_origin']}; {token} cites "
        f"{context['test_identity']} on {context['device_identity']}. For {token}, identify "
        "the registered error and corrective boundary."
    )


def _mutation_question(
    parent: CandidateReviewPacket,
    operator_id: str,
    stage: int,
    token: str,
) -> tuple[str, dict[str, object]]:
    context = dict(parent.input.structured_context.items())
    team = context.get("team") or context.get("synthetic_team_id") or "TEAMXUNKNOWN"
    athlete = context.get("athlete") or context.get("synthetic_athlete_id") or "ATHXUNKNOWN"
    session = context.get("session_identity") or "SESSXUNKNOWN"
    test = (
        context.get("test_identity") or context.get("scientific_family") or parent.benchmark_family
    )
    record = context.get("production_scenario_id") or context.get("record") or token
    questions = {
        "measurement-identity-trap": (
            f"{team} overlay {token} treats two {test} outputs as one "
            "because their labels match. "
            f"{athlete} asks which typed identity is registered for {session}.",
            f"{athlete} receives {team} sheet {record}: one field is direct "
            "and one provider-derived. "
            f"Decide whether the common label proves identity in {token}.",
            f"Audit {token} for {team}; the {test} export collapses distinct "
            f"measurands for {athlete}. "
            f"State the identity boundary at {session}.",
        ),
        "comparability-overreach": (
            f"{team} memo {token} pools {test} methods despite a threshold mismatch "
            "and no registered bridge. "
            f"State comparability for {athlete} in {session}.",
            f"For {athlete}, {record} calls two {test} protocols interchangeable "
            "because labels match. "
            f"{team} has no bridge; give the registered state in {token}.",
            f"{token} asks {team} to combine unmatched {test} thresholds "
            f"and methods for {athlete}. "
            f"Identify the comparison boundary at {session}.",
        ),
        "claim-boundary-overreach": (
            f"{team} interpretation {token} turns the reported {test} change "
            f"for {athlete} into a causal effect. "
            f"State the supported claim at {session}.",
            f"{record} attributes {athlete}'s {test} change to an intervention "
            "without causal identification. "
            f"Give the maximum supported statement for {team} in {token}.",
            f"At {session}, {team} calls {test} improvement meaningful "
            "despite missing error authority. "
            f"State what the evidence supports for {athlete} in {token}.",
        ),
        "safe-partial-refusal-trap": (
            f"{team} request {token} asks for an unsupported "
            f"{parent.benchmark_family} norm from {record}. "
            f"Refuse escalation and preserve safe facts about {athlete} at {session}.",
            f"For {athlete}, {record} lacks authority for the requested {test} claim. "
            f"{team} still has lower-level observations; state the refusal boundary in {token}.",
            f"{token} asks {team} to fill missing {test} evidence "
            f"with an assumed answer for {athlete}. "
            f"State what must be refused and what remains safe at {session}.",
        ),
        "error-correction-trap": (
            f"{team} draft {token} asserts "
            f"{context.get('unsafe_response_claim', 'an unsupported scientific interpretation')}. "
            f"Classify the registered error and correct the boundary for "
            f"{athlete}'s {test} record {record}.",
            f"Review {record} from {team}: the proposed {test} statement is unsupported. "
            f"Name the error class and safe correction for {athlete} at {token}.",
            f"{token} presents an unsupported conclusion for {athlete}. "
            "Identify the principal registered "
            f"error in {team}'s {test} note and its corrective limit.",
        ),
    }
    if operator_id not in questions or stage not in (1, 2, 3):
        raise ValueError("production mutation operator/stage is outside its frozen registry")
    question = (
        _identity_mutation_question(
            context,
            capability_id=parent.capability_id,
            token=token,
            stage=stage,
        )
        if parent.capability_id in {"C01", "C03", "C04"}
        and operator_id == "measurement-identity-trap"
        else (
            _c07_mutation_question(context, token=token, stage=stage)
            if parent.capability_id == "C07" and operator_id == "comparability-overreach"
            else (
                (
                    _c09_mutation_question(context, token=token, stage=stage)
                    if parent.capability_id == "C09"
                    else _c15_mutation_question(context, token=token, stage=stage)
                )
                if parent.capability_id in {"C09", "C15"}
                and operator_id == "claim-boundary-overreach"
                else (
                    _c18_mutation_question(
                        context,
                        family=parent.benchmark_family,
                        token=token,
                        stage=stage,
                    )
                    if parent.capability_id == "C18" and operator_id == "safe-partial-refusal-trap"
                    else (
                        _c17_mutation_question(context, token=token, stage=stage)
                        if parent.capability_id == "C17" and operator_id == "error-correction-trap"
                        else questions[operator_id][stage - 1]
                    )
                )
            )
        )
    )
    question = _apply_adversarial_tag_focus(
        question,
        parent.adversarial_tags,
        scenario_id=str(record),
    )
    context.update(
        {
            "production_mutation_token": token,
            "production_mutation_operator": operator_id,
            "production_mutation_stage": stage,
            "adversarial_claim_injected": True,
        }
    )
    return question, context


def _mutation_child(
    parent: CandidateReviewPacket,
    *,
    candidate_id: str,
    lineage_id: str,
    operator_id: str,
    stage: int,
    mutation_seed: int,
) -> CandidateReviewPacket:
    from dynamislm.qualification.res115_authoring import _mutation_contamination

    token = f"MUTX{hashlib.sha256(str(mutation_seed).encode()).hexdigest()[:10].upper()}"
    question, context = _mutation_question(parent, operator_id, stage, token)
    binding = CandidateParentBinding(
        parent_candidate_id=parent.candidate_id,
        parent_candidate_version=parent.candidate_version,
        parent_candidate_payload_hash=parent.candidate_payload_hash,
        parent_origin_class=parent.proposed_provenance.origin_class,
        mutation_lineage_id=lineage_id,
    )
    parent_authority = AuthorityBinding(
        authority_kind=AuthorityKind.MUTATION_PARENT.value,
        source_reference_id=parent.candidate_id,
        version=parent.candidate_version,
        digest=parent.candidate_payload_hash,
        governed_field_ids=("provenance.parent_case_hash",),
    )
    authority = (
        *(
            item
            for item in parent.authority
            if item.authority_kind != AuthorityKind.MUTATION_PARENT.value
        ),
        parent_authority,
    )
    provenance = replace(
        parent.proposed_provenance,
        author_id=PRODUCTION_AUTHORING_PROCESS_ID,
        review_scope="Agent-authored adversarial mutation; Phase-C human review remains pending.",
        origin_class=CaseOrigin.ADVERSARIAL_MUTATION,
        derivation_status="ADVERSARIAL_MUTATION_REVALIDATED",
        mutation_lineage_id=lineage_id,
        parent_case_hash=None,
        mutation_operator=operator_id,
        mutation_version="1.0.0",
        mutation_seed=mutation_seed,
        changed_fields=(),
        parent_origin_class=parent.proposed_provenance.origin_class,
        authority_lineage=tuple(
            sorted(
                (item.source_reference_id for item in authority),
                key=lambda value: value.encode("utf-8"),
            )
        ),
        generator_id=None,
        generator_version=None,
        generator_family=None,
        seed_namespace=None,
        seed_block=None,
        generator_registry_digest=None,
    )
    input_contract = replace(
        parent.input,
        question_text=question,
        structured_context=context,
    )
    contamination = _mutation_contamination(parent, candidate_id=candidate_id, question=question)
    contamination = replace(
        contamination,
        generator_namespace=None,
        generator_seed_block=None,
    )
    child = CandidateReviewPacket(
        benchmark_version=parent.benchmark_version,
        schema_version=parent.schema_version,
        candidate_id=candidate_id,
        candidate_version=parent.candidate_version,
        capability_id=parent.capability_id,
        benchmark_family=parent.benchmark_family,
        practitioner_question_class=parent.practitioner_question_class,
        question=question,
        input=input_contract,
        source_evidence_refs=parent.source_evidence_refs,
        proposed_expected_answer=parent.proposed_expected_answer,
        authority=authority,
        refusal_contract=parent.refusal_contract,
        claim_contract=parent.claim_contract,
        comparability_contract=parent.comparability_contract,
        scoring_contract=parent.scoring_contract,
        tolerance_contract=parent.tolerance_contract,
        proposed_provenance=provenance,
        contamination=contamination,
        isolation=replace(
            parent.isolation,
            allocation_stratum=(
                f"{parent.capability_id}:{parent.benchmark_family}:MUTATION-{stage}"
            ),
        ),
        difficulty=DifficultyBinding(
            DifficultyLevel.HARD,
            "adversarial claim conflicts with the preserved primary scientific authority",
        ),
        adversarial_tags=parent.adversarial_tags,
        parent_candidate_binding=binding,
        candidate_payload_hash="sha256:" + "0" * 64,
        proposed_approval_digest="sha256:" + "0" * 64,
    )
    parent_projection = candidate_scientific_projection(parent)
    child_projection = candidate_scientific_projection(child)
    changed_fields = tuple(
        sorted(
            (
                field
                for field in parent_projection
                if parent_projection[field] != child_projection[field]
            ),
            key=lambda value: value.encode("utf-8"),
        )
    )
    if not changed_fields:
        raise ValueError("production mutation operator changed no scientific projection fields")
    child = replace(
        child,
        proposed_provenance=replace(
            child.proposed_provenance,
            changed_fields=changed_fields,
        ),
    )
    return bind_candidate_review_packet(child)


def _scope_production_author_batch(packet: CandidateReviewPacket) -> CandidateReviewPacket:
    if (
        packet.proposed_provenance.origin_class
        not in {
            CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION,
            CaseOrigin.DETERMINISTIC_ENGINE_DERIVED,
            CaseOrigin.DETERMINISTIC_SYNTHETIC,
        }
        or packet.contamination.expert_author_batch_id is None
    ):
        validate_production_origin_isolation_metadata(packet)
        return packet
    return bind_candidate_review_packet(
        replace(
            packet,
            contamination=replace(packet.contamination, expert_author_batch_id=None),
            candidate_payload_hash="sha256:" + "0" * 64,
            proposed_approval_digest="sha256:" + "0" * 64,
        )
    )


def _author_mutation_packets(
    lineages: tuple[ProductionMutationLineageInputV1, ...],
    seed_blocks: tuple[tuple[str, str], ...],
    parents: dict[str, CandidateReviewPacket],
) -> tuple[CandidateReviewPacket, ...]:
    seed_by_id = dict(seed_blocks)
    packets: dict[str, CandidateReviewPacket] = {}
    for lineage in lineages:
        parent = parents[lineage.parent_candidate_id]
        for stage, child_id in enumerate(lineage.child_candidate_ids, start=1):
            seed = seed_by_id[child_id]
            mutation_seed = int(hashlib.sha256(seed.encode("ascii")).hexdigest()[:15], 16)
            child = _mutation_child(
                parent,
                candidate_id=child_id,
                lineage_id=lineage.lineage_id,
                operator_id=lineage.operator_id,
                stage=stage,
                mutation_seed=mutation_seed,
            )
            packets[child_id] = child
            parent = child
    if len(packets) != 111:
        raise ValueError("production mutation lane must contain exactly 111 candidates")
    return tuple(packets[candidate_id] for candidate_id in sorted(packets))


def build_production_authoring_draft(
    *,
    repository_root: str | Path,
    production_root: str | Path = DEFAULT_PRODUCTION_ROOT,
) -> tuple[ProductionAuthoringDraftV1, QualificationExclusionCommitmentV1]:
    """Author, validate, and plan the full external-only 434-packet production batch."""

    repository_root = Path(repository_root).resolve()
    production_root = Path(production_root).resolve()
    if production_root.is_relative_to(repository_root):
        raise ValueError("production authoring inputs and packets must remain outside Git")
    source_resolver = build_res115_source_artifact_resolver()
    exclusion, _exclusion_file_digest, _exclusion_size = read_external_production_json(
        QUALIFICATION_PRIVATE_EXCLUSION_PATH,
        QualificationExclusionCommitmentV1,
        repository_root=repository_root,
        production_root=production_root,
    )
    from dynamislm.benchmark.production_exclusions import (
        validate_qualification_exclusion_commitment,
    )

    validate_qualification_exclusion_commitment(exclusion)
    external_root = source_resolver.retained_source_root.parents[1]
    supported_sources = _choose_supported_sources(exclusion, external_root=external_root)
    direct_sources = _direct_target_source_selections(exclusion, external_root=external_root)
    source_selections = tuple(
        sorted(
            (*supported_sources, *direct_sources),
            key=lambda item: _source_candidate_id(item).encode("utf-8"),
        )
    )
    if len(source_selections) != 40:
        raise ValueError("production source lane must contain exactly 40 selections")

    semantic_slots = _semantic_slot_specs()
    engine_slots = _engine_slot_specs()
    synthetic_slots = _synthetic_slot_specs()
    expert_batches = _expert_batch_records(semantic_slots)
    mutation_lineages = _mutation_lineage_specs(semantic_slots)
    source_records = _source_authoring_records(source_selections)
    scenario_ids, synthetic_ids, mutation_ids = _authoring_input_skeleton(
        semantic_slots=semantic_slots,
        engine_slots=engine_slots,
        synthetic_slots=synthetic_slots,
        source_records=source_records,
        expert_batches=expert_batches,
        mutation_lineages=mutation_lineages,
    )
    inputs = _new_or_resume_private_inputs(
        scenario_ids=scenario_ids,
        synthetic_ids=synthetic_ids,
        mutation_ids=mutation_ids,
        source_records=source_records,
        expert_batches=expert_batches,
        mutation_lineages=mutation_lineages,
        repository_root=repository_root,
        production_root=production_root,
    )
    semantic = _author_semantic_packets(semantic_slots, inputs)
    engine = _author_engine_packets(engine_slots, inputs)
    synthetic = _author_synthetic_packets(synthetic_slots, inputs)
    source = _author_source_packets(source_selections, source_resolver=source_resolver)
    ordinary = tuple(
        sorted(
            (
                _scope_production_author_batch(packet)
                for packet in (*semantic, *engine, *synthetic, *source)
            ),
            key=lambda p: p.candidate_id.encode("utf-8"),
        )
    )
    if len(ordinary) != 323 or len({packet.candidate_id for packet in ordinary}) != 323:
        raise ValueError("production origin lanes do not contain 323 unique parent packets")
    ordinary_by_id = {packet.candidate_id: packet for packet in ordinary}
    mutation_parents = {
        lineage.parent_candidate_id: ordinary_by_id[lineage.parent_candidate_id]
        for lineage in mutation_lineages
    }
    mutations = _author_mutation_packets(
        mutation_lineages,
        inputs.mutation_seed_blocks,
        mutation_parents,
    )
    packets = tuple(
        sorted((*ordinary, *mutations), key=lambda packet: packet.candidate_id.encode("utf-8"))
    )
    if (
        len(packets) != FINAL_TARGET_CASES
        or len({packet.candidate_id for packet in packets}) != FINAL_TARGET_CASES
    ):
        raise ValueError("production authoring did not produce exactly 434 unique packets")
    for packet in packets:
        validate_production_origin_isolation_metadata(packet)
    commitments = _validate_production_candidate_set_and_commitments(
        packets,
        source_resolver=source_resolver,
    )
    counts = Counter(packet.proposed_provenance.origin_class for packet in packets)
    expected_counts = {
        CaseOrigin.EXPERT_AUTHORED_SEMANTIC: 240,
        CaseOrigin.SOURCE_BACKED_EVIDENCE_EXTRACTION: 40,
        CaseOrigin.DETERMINISTIC_ENGINE_DERIVED: 31,
        CaseOrigin.DETERMINISTIC_SYNTHETIC: 12,
        CaseOrigin.ADVERSARIAL_MUTATION: 111,
    }
    if counts != expected_counts:
        raise ValueError(f"production origin counts differ from the authored target: {counts}")
    validate_production_isolation(commitments)
    validate_production_candidate_set_against_qualification_exclusion(
        packets,
        exclusion,
        source_resolver=source_resolver,
    )
    duplication = audit_production_duplicates(packets)
    feasibility = validate_production_hard_feasibility(
        commitments,
        exact_shingle_colocation_pairs=duplication.exact_shingle_colocation_pairs,
    )
    queue = build_production_review_queue(packets)
    validate_production_review_queue(queue, packets)

    items = tuple(item.item for item in commitments)
    provisional_plan = ProductionAuthoringPlanV1(
        batch_id=PRODUCTION_BATCH_ID,
        plan_version=PRODUCTION_AUTHORING_PLAN_VERSION,
        authoring_process_id=PRODUCTION_AUTHORING_PROCESS_ID,
        target_case_count=FINAL_TARGET_CASES,
        coverage_matrix_digest=coverage_manifest_digest(),
        recipe_registry_digest=authoring_recipe_registry_digest(),
        qualification_exclusion_digest=exclusion.commitment_digest,
        items=items,
        plan_digest="sha256:" + "0" * 64,
    )
    plan = bind_production_authoring_plan(provisional_plan)
    validate_production_authoring_plan(plan)
    return (
        ProductionAuthoringDraftV1(
            packets=packets,
            plan=plan,
            inputs=inputs,
            commitments=commitments,
            feasibility_receipt=feasibility,
            review_queue=queue,
            duplication_audit=duplication,
        ),
        exclusion,
    )

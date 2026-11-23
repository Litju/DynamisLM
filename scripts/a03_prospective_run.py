"""Generate and commit blinded A0.3 N/C0/C1 outputs. Scientific dispatch occurs at scoring."""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import random
import resource
import site
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, Protocol

from dynamislm.serialization import canonical_hash, canonical_json, from_canonical_json
from scripts import a02_dev_runtime
from scripts import a02_v3_constrained as c0
from scripts import a02_v3_contract as v3
from scripts import a02_v3_decision as historical
from scripts import a02_v3_worker as checkpoint
from scripts import a03_benchmark_seal as sealer
from scripts import a03_d0_runtime as d0
from scripts import a03_scientific_admission as admission
from scripts.a02_v3_precision import PrecisionAudit, load_model
from scripts.a02_v3_preflight import load_pinned_tokenizer
from scripts.a03_d0_sample import tokens_sha256
from scripts.a03_d0_static import token_replay
from scripts.a03_hf_token_mask import hf_prefix_mask
from scripts.a03_token_decoder import Grammar, TokenMask, Vocabulary

ARMS = ("N", "C0", "C1")
ARM_SEED = 741132
SCHEMA = "DYNAMISLM_A03_PROSPECTIVE_RUN_V1"
C0_BLOB = "f92bbb42035ab6702ced71b95f9561c27c57d2ce"
ROOT = Path(__file__).resolve().parents[1]
BLIND_FIELDS = "item_id question observations requested_claims"
DEV = "DEVELOPMENT_ONLY"
QUALIFICATION = "REAL_MODEL_DEVELOPMENT_ONLY"
PROSPECTIVE = "PROSPECTIVE"
MAX_PROMPT = 1536


def object_hash(value: object) -> str:
    return v3.sha256(v3.canonical(value).encode())


def verified_bytes(path: Path, expected: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"bound input must be a regular file: {path.name}")
    data = path.read_bytes()
    if v3.sha256(data) != expected:
        raise ValueError(f"bound bytes differ: {path.name}")
    return data


def jsonl(data: bytes) -> list[dict[str, Any]]:
    if not data.endswith(b"\n"):
        raise ValueError("JSONL is empty or has an unfinished line")
    return [v3.json_object(line) for line in data.decode("utf-8").splitlines()]


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def source_identity(mode: str) -> dict[str, str]:
    if mode not in (DEV, QUALIFICATION, PROSPECTIVE):
        raise ValueError("unknown evaluation mode")
    if mode != DEV and _git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("real-model execution requires an exact clean source checkout")
    if _git("hash-object", "scripts/a02_v3_constrained.py") != C0_BLOB:
        raise ValueError("frozen C0 source differs")
    tracked = _git(
        "ls-files", "src", "scripts", "experiments", "registries", "uv.lock", "pyproject.toml"
    )
    # Include the prospective modules while developing the CPU fixture before its commit.
    files = set(tracked.splitlines()) | {
        path.relative_to(ROOT).as_posix() for path in (ROOT / "scripts").glob("a03_prospective*.py")
    }
    return {
        "commit": _git("rev-parse", "HEAD"),
        "tree": _git("rev-parse", "HEAD^{tree}"),
        "checkout_sha256": object_hash({name: d0.digest(ROOT / name) for name in sorted(files)}),
        "c0_git_blob": C0_BLOB,
    }


def model_identity(mode: str, device: str = "cpu") -> dict[str, Any]:
    if device not in ("cpu", "cuda"):
        raise ValueError("inference device must be cpu or cuda")
    packages = dict(d0.RUNTIME)
    if mode == QUALIFICATION and device == "cpu":
        packages["torch"] = "2.14.1+cpu"
    return {
        "device": device,
        "model": historical.load_protocol()["candidate_model"],
        "model_files": d0.MODEL_FILES,
        "adapter_step": 510,
        "adapter_files": d0.ADAPTER_FILES,
        "tokenizer": v3.load_profile()["tokenizer"],
        "greedy": True,
        "precision": "float32",
        "attention": "sdpa:MATH",
        "runtime_packages": packages,
        "autocast": False,
        "tf32": False,
        "max_new_tokens": d0.MAX_NEW,
        "max_prompt_tokens": MAX_PROMPT,
        "eos_token_id": d0.EOS,
    }


def blind_request(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row[field] for field in BLIND_FIELDS.split()}


def observation_binding(
    bound: admission.BoundRequest, index: int, source_sha256: str
) -> dict[str, Any]:
    entry = bound.entries[index]
    observation = entry.observation
    artifacts = {
        artifact.content_digest.removeprefix("sha256:")
        for artifact in observation.provenance.source_artifacts
        if artifact.immutable
    }
    records = {
        record.canonical_record_hash.removeprefix("sha256:")
        for record in bound.records
        if entry in record.entries
    }
    visible = bound.model_request()["observations"][index]
    if source_sha256 not in artifacts or len(records) != 1:
        raise ValueError("qualified observation lacks unique trusted source and record binding")
    return {
        "alias": f"observation-{index + 1}",
        "binding": "QUALIFIED",
        "source_sha256": source_sha256,
        "record_sha256": next(iter(records)),
        "observation_sha256": canonical_hash(observation).removeprefix("sha256:"),
        "device": visible["device"],
        "protocol": visible["protocol"],
        "unit": visible["unit"],
    }


@dataclass(frozen=True)
class Item:
    item_id: str
    request: dict[str, Any]
    bound: admission.BoundRequest
    ids: list[str]


def load_items(requests: bytes, sources: bytes, *, mode: str = PROSPECTIVE) -> list[Item]:
    source_rows = jsonl(sources)
    by_id = {row["item_id"]: sealer._fields(row, "item_id bound")["bound"] for row in source_rows}
    if len(by_id) != len(source_rows):
        raise ValueError("duplicate source item")
    items = []
    seen = set()
    exposed = sealer._exposed_questions() if mode != QUALIFICATION else set()
    for row in jsonl(requests):
        sealer._fields(row, BLIND_FIELDS)
        item_id = sealer._key(row["item_id"])
        if item_id in seen or item_id not in by_id:
            raise ValueError("duplicate item or missing trusted snapshot")
        seen.add(item_id)
        ids = sealer._request(
            {
                **row,
                "cluster_id": item_id,
                "scenario_id": item_id,
                "author_id": "blinded",
                "stratum": sealer.STRATA[0],
                "critical_families": [],
            },
            exposed,
        )
        bound = from_canonical_json(by_id[item_id], admission.BoundRequest)
        if by_id[item_id] != canonical_json(bound):
            raise ValueError("trusted source snapshot is noncanonical")
        request = bound.model_request()
        if (request["question"], request["requested_claims"]) != (
            row["question"],
            row["requested_claims"],
        ):
            raise ValueError("blinded request differs from trusted binding")
        # Unresolved slots can follow the qualified prefix and never enter the model snapshot.
        qualified = row["observations"][: len(bound.entries)]
        unresolved = row["observations"][len(bound.entries) :]
        if (
            len(qualified) != len(bound.entries)
            or any(
                obs != observation_binding(bound, i, obs["source_sha256"])
                for i, obs in enumerate(qualified)
            )
            or any(obs["binding"] != "UNRESOLVED" for obs in unresolved)
        ):
            raise ValueError("sealed observation differs from trusted snapshot")
        v3.visible_request(request)
        items.append(Item(item_id, row, bound, ids))
    if not items or seen != by_id.keys():
        raise ValueError("trusted snapshot inventory differs")
    return items


def work_items(items: list[Item]) -> list[checkpoint.WorkItem]:
    rng = random.Random(ARM_SEED)
    return [
        checkpoint.WorkItem(item.item_id, arm)
        for item in items
        for arm in rng.sample(ARMS, len(ARMS))
    ]


def run_manifest(
    mode: str, requests: bytes, sources: bytes, *, device: str = "cpu"
) -> dict[str, Any]:
    items = load_items(requests, sources, mode=mode)
    return {
        "schema": SCHEMA,
        "mode": mode,
        "source": source_identity(mode),
        "model_identity": model_identity(mode, device) if mode != DEV else None,
        "protocol_sha256": d0.digest(ROOT / "experiments/a03/prospective-protocol.md"),
        "blind_requests_sha256": v3.sha256(requests),
        "sources_sha256": v3.sha256(sources),
        "arms": list(ARMS),
        "arm_seed": ARM_SEED,
        "work_sha256": checkpoint.work_list_sha256(work_items(items)),
    }


@dataclass(frozen=True)
class Generation:
    ids: list[int]
    raw: str
    termination: str


class Backend(Protocol):
    tokenizer: Any
    mask: TokenMask

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Generation: ...


class PinnedBackend:
    """Local frozen D0 loader with explicit FP32 CPU or T4 placement."""

    def __init__(self, snapshot: Path, adapter: Path, *, mode: str, device: str):
        import torch  # type: ignore[import-not-found]
        from peft import PeftModel  # type: ignore[import-not-found]

        started = time.monotonic()
        self.identity = model_identity(mode, device)
        packages = self.identity["runtime_packages"]
        if {name: version(name) for name in packages} != packages:
            raise ValueError("pinned runtime packages differ")
        self.runtime: dict[str, Any] = {
            "python": sys.version,
            "device": device,
            "torch_threads": torch.get_num_threads(),
            "torch_interop_threads": torch.get_num_interop_threads(),
        }
        if device == "cuda":
            inventory = a02_dev_runtime.inventory(torch, Path(site.getsitepackages()[0]))
            qualified = a02_dev_runtime.qualify(
                inventory, a02_dev_runtime.cuda_smoke(torch, inventory)
            )
            if (
                not qualified["qualified"]
                or torch.version.cuda != "13.0"
                or torch.cuda.mem_get_info(0)[0] < d0.MIN_FREE_VRAM
            ):
                raise ValueError(f"D0 T4 qualification failed: {qualified}")
            self.runtime["cuda"] = {
                "provenance": qualified["provenance_only"],
                "requirements": {row["name"]: row["passed"] for row in qualified["requirements"]},
                "name": inventory["cuda"]["name"],
                "compute_capability": inventory["cuda"]["compute_capability"],
                "total_vram_bytes": inventory["cuda"]["total_vram_bytes"],
            }
        d0.verify_files(snapshot, d0.MODEL_FILES)
        d0.verify_files(adapter, d0.ADAPTER_FILES)
        self.tokenizer = load_pinned_tokenizer(snapshot)
        self.mask = TokenMask(Vocabulary.from_pinned(snapshot))
        self.model = PeftModel.from_pretrained(
            load_model(snapshot, "float32", device=device), adapter, is_trainable=False
        ).eval()
        self.model.generation_config = type(self.model.generation_config).from_model_config(
            self.model.config
        )
        self.audit = PrecisionAudit(self.model, "float32")
        if (
            self.mask.eos != d0.EOS
            or self.model.generation_config.eos_token_id != d0.EOS
            or self.model.config._attn_implementation != "sdpa"
            or any(p.requires_grad or p.device.type != device for p in self.model.parameters())
        ):
            raise ValueError("pinned inference conditions differ")
        self.runtime["parameters"] = self.audit.identity
        self.setup_seconds = time.monotonic() - started

    def measurements(self) -> dict[str, Any]:
        import torch

        return {
            "setup_seconds": self.setup_seconds,
            "peak_host_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "peak_cuda_reserved_bytes": (
                torch.cuda.max_memory_reserved() if self.identity["device"] == "cuda" else None
            ),
            "precision": self.audit.report() if self.audit.logit_dtypes else self.audit.identity,
        }

    def generate(
        self, arm: str, request: dict[str, Any], prompt: list[int], deadline: float
    ) -> Generation:
        from functools import partial

        if arm == "C0":
            score = c0.CachedSequenceLogprob(c0.HFIncrementalBackend(self.model))

            def bounded_score(ids: Sequence[int], start: int) -> float:
                if time.monotonic() >= deadline or len(ids) > len(prompt) + d0.MAX_NEW:
                    raise TimeoutError("C0 scoring limit reached")
                return score(ids, start)

            import torch

            def audit(_module: Any, _inputs: Any, logits: Any) -> None:
                if not torch.isfinite(logits).all().item():
                    raise ValueError("C0 model logits must be finite")

            hook = self.model.lm_head.register_forward_hook(audit)
            try:
                result = c0.decode(
                    request=request,
                    prompt_ids=prompt,
                    encode=lambda text: self.tokenizer.encode(text, add_special_tokens=False),
                    chooser=c0.model_chooser(bounded_score),
                )
            finally:
                hook.remove()
            return Generation(result["token_ids"], result["text"], "C0_GRAMMAR_COMPLETE")
        callback = (
            partial(hf_prefix_mask, self.mask, Grammar(request), prompt) if arm == "C1" else None
        )
        result, _ = d0.generate(self.model, self.tokenizer, prompt, callback, deadline)
        ids = result["token_ids"]
        termination = (
            "MODEL_EOS"
            if result["eos"]
            else ("TOKEN_LIMIT" if len(ids) == d0.MAX_NEW else "EARLY_STOP")
        )
        return Generation(ids, result["raw_output"], termination)


def diagnostics(
    arm: str, generation: Generation, tokenizer: Any, mask: TokenMask, item: Item
) -> dict[str, Any]:
    ids, raw, stop = generation.ids, generation.raw, generation.termination
    if not isinstance(ids, list) or any(type(i) is not int or i < 0 for i in ids):
        raise ValueError("invalid generated token IDs")
    if not isinstance(raw, str) or len(ids) > d0.MAX_NEW:
        raise ValueError("invalid generated bytes or token bound")
    if stop == "MODEL_ERROR":
        if raw or ids:
            raise ValueError("model error record contains generated output")
        return {
            "parse_only": False,
            "strict_syntax": False,
            "action": None,
            "parser_code": "MODEL_ERROR",
            "first_masked_token": None,
            "mask_accepted": False,
            "truncated": False,
        }
    eos_well_formed = bool(ids and ids[-1] == mask.eos and mask.eos not in ids[:-1])
    expected = (
        "C0_GRAMMAR_COMPLETE"
        if arm == "C0"
        else "MODEL_EOS"
        if eos_well_formed
        else "TOKEN_LIMIT"
        if len(ids) == d0.MAX_NEW
        else "EARLY_STOP"
    )
    if stop != expected or (arm == "C0" and mask.eos in ids):
        raise ValueError("termination is inconsistent with the selected arm and tokens")
    if arm == "C0":
        reproduced = tokenizer.encode(raw, add_special_tokens=False) == ids
    else:
        reproduced = tokenizer.decode(ids, skip_special_tokens=True) == raw
    if not reproduced:
        raise ValueError("recorded raw output does not reproduce from token evidence")
    try:
        action = v3.parse_action(
            raw, [f"observation-{i}" for i in range(1, v3.MAX_OBSERVATIONS + 1)]
        )
    except (ValueError, TypeError):
        action = None
    scoped = action is not None and set(action["observation_ids"]) <= set(
        v3.observation_ids(item.bound.model_request())
    )
    accepted, first = (
        token_replay(mask, Grammar(item.bound.model_request()), ids, raw)
        if arm != "C0"
        else (False, None)
    )
    return {
        "parse_only": action is not None,
        "action": action,
        "parser_code": (
            "V3_INVALID_PROPOSAL"
            if action is None
            else "OK"
            if scoped
            else "V3_OBSERVATION_REFERENCE_UNRESOLVED"
        ),
        "strict_syntax": bool(action is not None and (arm == "C0" or eos_well_formed)),
        "mask_accepted": accepted,
        "first_masked_token": first,
        "truncated": stop == "TOKEN_LIMIT",
    }


def restricted(path: Path) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to(ROOT) or resolved != path.absolute():
        raise ValueError("evaluation paths must be outside Git and must not use symlinks")
    if not resolved.is_dir() or resolved.stat().st_mode & 0o077:
        raise ValueError("evaluation directories must be private (0700)")
    return resolved


def verify_run(
    manifest: dict[str, Any], requests: bytes, sources: bytes
) -> tuple[list[Item], list[checkpoint.WorkItem]]:
    if manifest.get("blind_requests_sha256") != v3.sha256(requests) or manifest.get(
        "sources_sha256"
    ) != v3.sha256(sources):
        raise ValueError("bound request or source bytes differ")
    mode = manifest["mode"]
    device = manifest["model_identity"]["device"] if mode != DEV else "cpu"
    expected = run_manifest(mode, requests, sources, device=device)
    if manifest != expected:
        raise ValueError("source, inputs or execution manifest differ")
    items = load_items(requests, sources, mode=mode)
    return items, work_items(items)


def verify_output_records(
    path: Path,
    manifest: dict[str, Any],
    items: list[Item],
    work: list[checkpoint.WorkItem],
    tokenizer: Any,
    mask: TokenMask,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    digests = {
        item.item_id: v3.build_action_prompt(tokenizer, item.bound.model_request())
        for item in items
    }
    state = checkpoint.read_checkpoint(path, work)
    if state["torn_tail_discarded"]:
        raise ValueError("torn checkpoint requires external custody disposition")
    by_id = {item.item_id: item for item in items}
    for entry, scheduled in zip(state["entries"], work, strict=False):
        row = entry["record"]
        prompt = digests[scheduled.key]
        if (
            row["run_sha256"] != object_hash(manifest)
            or row["rendered_prompt_sha256"] != prompt["rendered_prompt_sha256"]
            or row["prompt_tokens_sha256"] != tokens_sha256(prompt["prompt_token_ids"])
            or row["raw_sha256"] != v3.sha256(row["raw"].encode())
            or row["tokens_sha256"] != tokens_sha256(row["ids"])
            or type(row["seconds"]) not in (int, float)
            or not math.isfinite(row["seconds"])
            or row["seconds"] < 0
            or row["diagnostics"]
            != diagnostics(
                scheduled.arm,
                Generation(row["ids"], row["raw"], row["termination"]),
                tokenizer,
                mask,
                by_id[scheduled.key],
            )
            or (row["termination"] == "MODEL_ERROR") != (row["model_error"] is not None)
        ):
            raise ValueError("checkpoint record binding differs")
    return state, digests


def run(
    manifest: dict[str, Any],
    requests: bytes,
    sources: bytes,
    output: Path,
    backend: Backend,
    *,
    seconds: float,
    resume_sha256: str | None = None,
    stop_after: int | None = None,
) -> dict[str, Any]:
    """Only blinded request/source bytes can enter this interface."""
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("a finite positive time bound is required")
    mode = manifest["mode"]
    pinned = backend if isinstance(backend, PinnedBackend) else None
    if mode != DEV and (
        pinned is None
        or type(pinned) is not PinnedBackend
        or pinned.identity != manifest["model_identity"]
    ):
        raise ValueError("real-model work requires the exact manifest backend")
    if stop_after is not None and (mode != QUALIFICATION or not 0 < stop_after):
        raise ValueError("only real-model development can request a checkpoint stop")
    directory = restricted(output)
    items, work = verify_run(manifest, requests, sources)
    by_id = {item.item_id: item for item in items}
    path = directory / "outputs.jsonl"
    commit = directory / "output-commit.json"
    runtime = directory / "runtime.json"
    if any(p.is_symlink() for p in (path, commit, runtime, directory / ".writer.lock")):
        raise ValueError("output state must not use symlinks")
    with (directory / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if commit.exists():
            raise ValueError("committed outputs are immutable")
        if path.exists() != (resume_sha256 is not None) or (
            resume_sha256 is not None and d0.digest(path) != resume_sha256
        ):
            raise ValueError("incomplete run requires the exact externally retained prefix digest")
        if pinned is not None:
            receipt = {"run_sha256": object_hash(manifest), **pinned.runtime}
            if path.exists() or runtime.exists():
                if runtime.read_bytes() != (v3.canonical(receipt) + "\n").encode():
                    raise ValueError("resumed inference runtime differs")
            else:
                d0.write(runtime, receipt)
        if not path.exists():
            path.touch(mode=0o600, exist_ok=False)
        if path.stat().st_mode & 0o077:
            raise ValueError("checkpoint must be private")
        state, prompts = verify_output_records(
            path, manifest, items, work, backend.tokenizer, backend.mask
        )
        deadline = time.monotonic() + seconds
        head = state["head"]
        first = len(state["entries"])
        for seq in range(first, len(work)):
            if time.monotonic() >= deadline or (
                stop_after is not None and seq - first >= stop_after
            ):
                return {"status": "INCOMPLETE", "entries": seq, "prefix_sha256": d0.digest(path)}
            scheduled = work[seq]
            item = by_id[scheduled.key]
            prompt = prompts[scheduled.key]
            ids = prompt["prompt_token_ids"]
            if not 0 < len(ids) <= MAX_PROMPT:
                raise ValueError("blinded request exceeds the registered prompt bound")
            start = time.monotonic()
            failure = None
            try:
                generation = backend.generate(
                    scheduled.arm, item.bound.model_request(), ids, deadline
                )
                if time.monotonic() >= deadline:
                    raise TimeoutError("generation finished after its deadline")
            except (RuntimeError, TimeoutError, ValueError) as exc:
                if isinstance(exc, TimeoutError) and mode == QUALIFICATION:
                    return {
                        "status": "INCOMPLETE",
                        "entries": seq,
                        "prefix_sha256": d0.digest(path),
                        "reason": "GENERATION_DEADLINE",
                    }
                failure = type(exc).__name__
                generation = Generation([], "", "MODEL_ERROR")
            record = {
                "run_sha256": object_hash(manifest),
                "raw": generation.raw,
                "ids": generation.ids,
                "raw_sha256": v3.sha256(generation.raw.encode()),
                "tokens_sha256": tokens_sha256(generation.ids),
                "termination": generation.termination,
                "model_error": failure,
                "seconds": time.monotonic() - start,
                "rendered_prompt_sha256": prompt["rendered_prompt_sha256"],
                "prompt_tokens_sha256": tokens_sha256(ids),
                "diagnostics": diagnostics(
                    scheduled.arm, generation, backend.tokenizer, backend.mask, item
                ),
            }
            head = checkpoint._append(
                path,
                {
                    "schema": checkpoint.CHECKPOINT_SCHEMA,
                    "seq": seq,
                    "item": scheduled.id,
                    "prev_sha256": head,
                    "record": record,
                },
            )
        result = {
            "status": "COMMITTED",
            "entries": len(work),
            "run_sha256": object_hash(manifest),
            "head": head,
            "outputs_sha256": d0.digest(path),
        }
        if pinned is not None:
            result["runtime_sha256"] = d0.digest(runtime)
        with commit.open("x", encoding="utf-8") as stream:
            stream.write(v3.canonical(result) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("blind_directory", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--resume-sha256")
    args = parser.parse_args()
    blind = restricted(args.blind_directory)
    manifest = v3.json_object(verified_bytes(blind / "run.json", args.manifest_sha256).decode())
    requests = verified_bytes(blind / "requests.jsonl", manifest["blind_requests_sha256"])
    sources = verified_bytes(blind / "sources.jsonl", manifest["sources_sha256"])
    if manifest["mode"] not in (QUALIFICATION, PROSPECTIVE):
        raise ValueError("the CLI requires a real-model manifest")
    verify_run(manifest, requests, sources)
    if manifest["model_identity"]["device"] != args.device:
        raise ValueError("requested device differs from run manifest")
    backend = PinnedBackend(args.snapshot, args.adapter, mode=manifest["mode"], device=args.device)
    print(
        v3.canonical(
            {
                **run(
                    manifest,
                    requests,
                    sources,
                    args.output_directory,
                    backend,
                    seconds=args.seconds,
                    resume_sha256=args.resume_sha256,
                    stop_after=args.stop_after,
                ),
                "measurements": backend.measurements(),
            }
        )
    )


if __name__ == "__main__":
    main()

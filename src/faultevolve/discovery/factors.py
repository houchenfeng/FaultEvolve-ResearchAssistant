"""Atomic factor discovery (KD1-F/G), decoupled from evolution.

The discovery package stays task-agnostic: whatever is specific to one device
family -- the columns a factor may read, and the stand-in feature used when no
LLM is available -- is passed in by the caller (see ``faultevolve.cli``).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Collection

from faultevolve.discovery.funnel import FunnelRecord, funnel_summary_dict, json_native
from faultevolve.discovery.pipeline import Candidate, DiscoveryRound
from faultevolve.discovery.schemas import DiscoveryStats

BASELINE_VERSION = "K0_v1"
COVERAGE_MIN_EXPLORE = 0.30
VALID_LANES = frozenset({"confirm", "diagnostic", "control"})
VALID_DIRECTIONS = frozenset({"+", "-", "auto"})


@dataclass
class FactorEntry:
    factor_id: str
    family: str
    code: str
    inputs: list[str]
    window_days: int
    direction: str
    source: str
    title: str
    condition: str
    outcome: str
    scope: str
    falsifier: str
    lane: str = "confirm"
    confirm_eligible: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FactorEntry:
        lane = str(data.get("lane", "confirm"))
        confirm_eligible = data.get("confirm_eligible")
        if confirm_eligible is None:
            confirm_eligible = lane == "confirm"
        return cls(
            factor_id=str(data["factor_id"]),
            family=str(data.get("family", "")),
            code=str(data["code"]),
            inputs=[str(x) for x in (data.get("inputs") or [])],
            window_days=int(data.get("window_days", 14)),
            direction=str(data["direction"]),
            source=str(data.get("source", "seed_library")),
            title=str(data["title"]),
            condition=str(data.get("condition", "always")),
            outcome=str(data.get("outcome", "failure")),
            scope=str(data.get("scope", "all")),
            falsifier=str(data.get("falsifier", "none")),
            lane=lane,
            confirm_eligible=bool(confirm_eligible),
        )

    def to_raw_claim(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "condition": self.condition,
            "feature_code": self.code,
            "outcome": self.outcome,
            "direction": self.direction,
            "scope": self.scope,
            "falsifier": self.falsifier,
            "category": "feature_engineering",
            "tags": [self.family, self.factor_id],
            "lane": self.lane,
            "confirm_eligible": self.confirm_eligible,
        }


def code_sha256(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def load_factor_library(
    path: Path,
    max_candidates: int = 30,
    allowed_columns: Collection[str] | None = None,
) -> list[FactorEntry]:
    """Load a factor library, optionally validating the columns factors declare.

    ``allowed_columns`` is the caller's contract.  When it is given, every entry
    of a factor's ``inputs`` must name a column that exists for that task, so a
    library that references a misspelled or unavailable column fails here rather
    than inside the sandbox.  When it is ``None`` (toy fixtures, task-agnostic
    callers) the column check is skipped.
    """
    allowed = set(allowed_columns) if allowed_columns is not None else None
    entries: list[FactorEntry] = []
    seen_hashes: set[str] = set()
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            fid = data.get("factor_id", f"line_{line_no}")
            if "def feature(" not in str(data.get("code", "")):
                raise ValueError(f"factor {fid} missing def feature(")
            ent = FactorEntry.from_dict(data)
            if ent.direction not in VALID_DIRECTIONS:
                raise ValueError(f"factor {ent.factor_id} invalid direction {ent.direction}")
            if ent.lane not in VALID_LANES:
                raise ValueError(f"factor {ent.factor_id} invalid lane {ent.lane}")
            if allowed is not None:
                for col in ent.inputs:
                    if col not in allowed:
                        raise ValueError(
                            f"factor {ent.factor_id} input {col} not in the task's discovery columns"
                        )
            ch = code_sha256(ent.code)
            if ch in seen_hashes:
                raise ValueError(f"factor {ent.factor_id} duplicate code hash")
            seen_hashes.add(ch)
            entries.append(ent)
            if len(entries) > max_candidates:
                raise ValueError(
                    f"factor library has more than max_candidates={max_candidates} entries"
                )
    if not entries:
        raise ValueError("factor library is empty")
    return entries


def write_candidate_registry(
    entries: list[FactorEntry],
    out_path: Path,
    baseline_version: str = BASELINE_VERSION,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for i, ent in enumerate(entries, start=1):
            row = {
                "factor_id": ent.factor_id,
                "comparison_index": i,
                "code_sha256": code_sha256(ent.code),
                "inputs": ent.inputs,
                "window_days": ent.window_days,
                "direction": ent.direction,
                "baseline_version": baseline_version,
                "source": ent.source,
                "family": ent.family,
                "lane": ent.lane,
                "confirm_eligible": ent.confirm_eligible,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def factors_to_candidates(entries: list[FactorEntry]) -> list[Candidate]:
    out: list[Candidate] = []
    for ent in entries:
        out.append(
            (
                f"factor:{ent.factor_id}",
                "",
                "",
                None,
                "discover_op",
                ent.to_raw_claim(),
            )
        )
    return out


def git_sha_short() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=Path(__file__).resolve().parents[3],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def _write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False, default=json_native)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _persist_funnel_artifacts(
    disc: Path,
    funnel: list[FunnelRecord],
    track_meta: dict[str, Any] | None = None,
) -> None:
    disc.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(disc / "funnel.json", [r.to_dict() for r in funnel])
    _write_json_atomic(disc / "funnel_summary.json", funnel_summary_dict(funnel, track_meta))


@dataclass
class FactorDiscoveryResult:
    round_result: Any
    funnel: list[FunnelRecord]
    registry_path: Path
    stats: DiscoveryStats
    discovery_llm_errors: int
    discovery_llm_error_first: str | None
    explore_only: bool = False


def run_factor_discovery(
    kd: DiscoveryRound,
    library_entries: list[FactorEntry],
    art_dir: Path,
    max_confirm: int,
    round_idx: int = 1,
    min_explore_effect: float = 0.05,
    explore_only: bool = False,
    audit_extra: dict[str, Any] | None = None,
    track_label: str = "",
    explore_incr_rule: str = "ci_low",
    min_incr_ci_low: float = 0.0,
    fdr_mode: str = "bh_ebh",
) -> FactorDiscoveryResult:
    registry_path = art_dir / "discovery" / "candidate_registry.jsonl"
    write_candidate_registry(library_entries, registry_path)
    candidates = factors_to_candidates(library_entries)
    funnel: list[FunnelRecord] = []
    disc = art_dir / "discovery"
    run_exc: BaseException | None = None
    result = None
    try:
        result = kd.run(
            round_idx,
            final=True,
            candidates=candidates,
            explore_gate_max_confirm=max_confirm,
            funnel_records=funnel,
            coverage_min_explore=COVERAGE_MIN_EXPLORE,
            min_explore_effect=min_explore_effect,
            explore_only=explore_only,
            track_label=track_label,
            explore_incr_rule=explore_incr_rule,
            min_incr_ci_low=min_incr_ci_low,
            fdr_mode=fdr_mode,
        )
    except BaseException as exc:
        run_exc = exc
    finally:
        track_meta = {
            "track_label": track_label,
            "explore_incr_rule": explore_incr_rule,
            "min_incr_ci_low": min_incr_ci_low,
            "fdr_mode": fdr_mode,
        }
        _persist_funnel_artifacts(disc, funnel, track_meta)
    if run_exc is not None:
        raise run_exc
    assert result is not None
    audit = {
        "n_library_factors": len(library_entries),
        "baseline_version": BASELINE_VERSION,
        "git_sha": git_sha_short(),
        "registry": str(registry_path),
        "min_explore_effect": min_explore_effect,
        "explore_only": explore_only,
        "confirmation_fraction": kd.cfg.confirmation_fraction,
        "track_label": track_label,
        "explore_incr_rule": explore_incr_rule,
        "min_incr_ci_low": min_incr_ci_low,
        "fdr_mode": fdr_mode,
    }
    if audit_extra:
        audit.update(audit_extra)
    with (disc / "data_audit.json").open("w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, ensure_ascii=False)
    first_err = kd.stats.discovery_llm_error_first
    return FactorDiscoveryResult(
        round_result=result,
        funnel=funnel,
        registry_path=registry_path,
        stats=kd.stats,
        discovery_llm_errors=kd.stats.discovery_llm_errors,
        discovery_llm_error_first=first_err,
        explore_only=explore_only,
    )


PROPOSE_MARKER = "KD_FACTOR_PROPOSE"


def build_propose_prompt(
    schema_note: str,
    column_list: list[str],
    baseline_desc: str,
    card_titles: list[str],
    control_hints: str,
    max_candidates: int,
) -> str:
    cols = ", ".join(column_list[:80])
    titles = "\n".join(f"- {t}" for t in card_titles[:40]) or "(none)"
    return f"""{PROPOSE_MARKER}
Propose up to {max_candidates} atomic failure factors as separate <claim></claim> JSON blocks.
Each claim must include: title, condition, feature_code (def feature(history): returning a Series aligned with history),
outcome, direction (+ or -), scope, falsifier, category, tags.
Use only columns present in history. No scoring or statistics in your reply.

Baseline K0: {baseline_desc}

Known literature card titles:
{titles}

Control hints: {control_hints}

Schema:
{schema_note}

Available columns: {cols}
"""


def propose_factors_llm(
    llm_call: Callable[[list[dict[str, str]]], str],
    prompt: str,
    max_candidates: int,
    mock: bool = False,
    mock_feature: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    from faultevolve.discovery.claims import extract_claims_from_response

    if mock:
        if mock_feature is None:
            raise ValueError(
                "mock=True needs a (feature_code, title) pair from the caller: the "
                "discovery package carries no task-specific column names"
            )
        mock_code, mock_title = mock_feature
        return [
            {
                "title": mock_title,
                "condition": "mock",
                "feature_code": mock_code,
                "outcome": "failure",
                "direction": "+",
                "scope": "all",
                "falsifier": "none",
                "category": "feature_engineering",
                "tags": ["mock"],
            }
        ]
    text = llm_call([{"role": "user", "content": prompt}])
    claims = extract_claims_from_response(text)
    return claims[:max_candidates]


def write_proposals(art_dir: Path, proposals: list[dict[str, Any]]) -> Path:
    disc = art_dir / "discovery"
    disc.mkdir(parents=True, exist_ok=True)
    path = disc / "factor_proposals.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for i, p in enumerate(proposals, start=1):
            row = {"proposal_index": i, **p}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def proposals_to_factor_entries(proposals: list[dict[str, Any]]) -> list[FactorEntry]:
    entries: list[FactorEntry] = []
    for i, p in enumerate(proposals, start=1):
        fid = f"LLM_P{i:03d}"
        entries.append(
            FactorEntry(
                factor_id=fid,
                family="llm_proposal",
                code=str(p["feature_code"]),
                inputs=[],
                window_days=14,
                direction=str(p["direction"]),
                source="llm_propose",
                title=str(p["title"]),
                condition=str(p.get("condition", "")),
                outcome=str(p.get("outcome", "failure")),
                scope=str(p.get("scope", "all")),
                falsifier=str(p.get("falsifier", "none")),
            )
        )
    return entries

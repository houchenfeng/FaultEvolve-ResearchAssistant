"""Frozen-claim replay: interrogation, KD2 tournament, and transfer validation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Collection

import numpy as np
import pandas as pd

from faultevolve.config import DiscoveryConfig
from faultevolve.discovery.baseline_features import build_baseline_features
from faultevolve.discovery.certificates import write_json as write_tournament_json
from faultevolve.discovery.claims import preregister
from faultevolve.discovery.controls import run_negative_controls
from faultevolve.discovery.factors import FactorEntry, load_factor_library
from faultevolve.discovery.mechanisms import (
    FIXED_RIVALS,
    _PREDICTION_TEMPLATES,
    _normalize_predictions,
)
from faultevolve.discovery.sandbox import STDERR_TAIL_CHARS, run_feature
from faultevolve.discovery.schemas import Claim, KD2Handoff, TournamentStats
from faultevolve.discovery.seed_util import seed_from
from faultevolve.discovery.splits import label_times, split_masks, temporal_halves
from faultevolve.discovery.stats import incremental_auroc, test_feature
from faultevolve.discovery.tournament import Tournament
from faultevolve.tasks.protocol import DiscoveryDataProvider, DiscoveryFrames

INTERROGATE_MARKERS = {
    "proponent": "KD_INTERROGATE_PROPONENT",
    "confounder": "KD_INTERROGATE_CONFOUNDER",
    "critic": "KD_INTERROGATE_CRITIC",
}

VALID_TRANSFER_FRAMES = frozenset({"train_late", "backblaze_public_train", "val"})
FORBIDDEN_TRANSFER_TOKENS = frozenset({"holdout", "test", "public_train"})


class ReplayError(Exception):
    def __init__(self, error_type: str, message: str = "", detail: dict[str, Any] | None = None) -> None:
        super().__init__(message or error_type)
        self.error_type = error_type
        self.detail = detail or {}


@dataclass
class ReplayResult:
    ok: bool
    claim_id: str
    factor_id: str
    frozen_direction: str
    split_salt: str
    confirmation_fraction: float
    interrogation_lines: int = 0
    tournament: dict[str, Any] = field(default_factory=dict)
    transfer: dict[str, Any] = field(default_factory=dict)
    cards_sha256_before: str = ""
    cards_sha256_after: str = ""
    error_type: str = ""
    error: str = ""


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_source_audit(source_discovery_dir: Path) -> dict[str, Any]:
    audit_path = source_discovery_dir / "data_audit.json"
    if not audit_path.is_file():
        raise ReplayError("missing_source_audit")
    return json.loads(audit_path.read_text(encoding="utf-8"))


def audit_split_params(audit: dict[str, Any]) -> tuple[str, float]:
    salt = audit.get("split_salt")
    frac = audit.get("confirmation_fraction")
    if salt is None or frac is None:
        raise ReplayError(
            "missing_audit_split_params",
            detail={"has_split_salt": salt is not None, "has_confirmation_fraction": frac is not None},
        )
    return str(salt), float(frac)


def load_frozen_direction(source_discovery_dir: Path, claim_id: str) -> str | None:
    phen_path = source_discovery_dir / "phenomena.json"
    if phen_path.is_file():
        try:
            items = json.loads(phen_path.read_text(encoding="utf-8"))
            if isinstance(items, list):
                for item in items:
                    if item.get("claim_id") != claim_id:
                        continue
                    payload = item.get("payload") or {}
                    for key in ("direction", "frozen_direction"):
                        val = payload.get(key)
                        if val in {"+", "-"}:
                            return val
        except json.JSONDecodeError:
            pass
    funnel_path = source_discovery_dir / "funnel.json"
    if funnel_path.is_file():
        try:
            records = json.loads(funnel_path.read_text(encoding="utf-8"))
            if isinstance(records, list):
                for rec in records:
                    if rec.get("claim_id") != claim_id:
                        continue
                    detail = rec.get("detail") or {}
                    for key in ("frozen_direction", "direction"):
                        val = detail.get(key)
                        if val in {"+", "-"}:
                            return val
        except json.JSONDecodeError:
            pass
    return None


def _missing_input_columns(history: pd.DataFrame, inputs: list[str]) -> list[str]:
    cols = set(history.columns)
    return [c for c in inputs if c not in cols]


def _build_claim(
    entry: FactorEntry,
    claim_id: str,
    experiment_id: str,
    frozen_direction: str,
    cfg: DiscoveryConfig,
) -> Claim:
    raw = entry.to_raw_claim()
    claim = Claim(
        id=claim_id,
        experiment_id=experiment_id,
        origin_node_id=entry.factor_id,
        source="discover_op",
        title=str(raw["title"]),
        condition=str(raw["condition"]),
        feature_code=str(raw["feature_code"]),
        outcome=str(raw["outcome"]),
        direction=frozen_direction,  # type: ignore[arg-type]
        scope=str(raw["scope"]),
        falsifier=str(raw["falsifier"]),
        category=str(raw.get("category", "feature_engineering")),
        tags=list(raw.get("tags") or []),
    )
    claim.prereg_hash = preregister(claim, cfg)
    claim.status = "graded"
    claim.grade = None
    return claim


def _extract_json_predictions(text: str) -> dict[str, Any] | None:
    for pattern in (
        r"<predictions>\s*(.*?)\s*</predictions>",
        r"<json>\s*(.*?)\s*</json>",
        r"\{[^{}]*env_invariance[^{}]*\}",
    ):
        m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if not m:
            continue
        blob = m.group(1) if m.lastindex else m.group(0)
        try:
            data = json.loads(blob)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return None


def _interrogation_prompt(
    role: str,
    claim: Claim,
    schema_note: str,
    feature_code_tail: str,
) -> str:
    marker = INTERROGATE_MARKERS[role]
    base = (
        f"{marker}\n"
        f"title={claim.title}\n"
        f"condition={claim.condition}\n"
        f"outcome={claim.outcome}\n"
        f"scope={claim.scope}\n"
        f"schema_note={schema_note[:500]}\n"
        f"feature_code={feature_code_tail}\n"
    )
    if role == "proponent":
        base += (
            "Write a mechanistic story and respond with "
            "<predictions>{...}</predictions> JSON for env_invariance, temporal, "
            "dose_response, mediation, heterogeneity (+1 or -1 each). "
            "Claim predictions must match the frozen claim template.\n"
        )
    elif role == "confounder":
        base += (
            "Attack confounding, measurement artifact, or censoring. "
            "Return one llm_rival as <predictions>{title, predictions}.</predictions>\n"
        )
    else:
        base += (
            "List causal sentences this claim cannot support. "
            "Optional llm_rival JSON in <predictions>...</predictions> or empty.\n"
        )
    return base


def run_interrogation(
    claim: Claim,
    schema_note: str,
    llm_call: Callable[[list[dict[str, str]]], str],
    out_path: Path,
) -> int:
    code_tail = claim.feature_code[:600]
    lines: list[dict[str, Any]] = []
    claim_template = _normalize_predictions(_PREDICTION_TEMPLATES["claim"])
    for role in ("proponent", "confounder", "critic"):
        prompt = _interrogation_prompt(role, claim, schema_note, code_tail)
        phash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        reply = ""
        parse_ok = False
        predictions: dict[str, int] | None = None
        try:
            reply = llm_call([{"role": "user", "content": prompt}])
            raw = _extract_json_predictions(reply)
            if raw is not None:
                preds = _normalize_predictions(raw.get("predictions") if "predictions" in raw else raw)
                if role == "proponent":
                    if preds == claim_template:
                        predictions = dict(preds)
                        parse_ok = True
                    else:
                        predictions = dict(claim_template)
                        parse_ok = False
                else:
                    predictions = dict(preds)
                    parse_ok = True
        except Exception:
            parse_ok = False
        lines.append(
            {
                "role": role,
                "prompt_hash": phash,
                "reply_tail": (reply or "")[-800:],
                "parse_ok": parse_ok,
                "predictions": predictions,
            }
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in lines:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(lines)


def _late_unit_mask(frames: DiscoveryFrames) -> np.ndarray:
    labels = frames.labels
    if not isinstance(labels, pd.DataFrame):
        labels = pd.DataFrame(labels)
    times = label_times(
        labels,
        frames.unit_col,
        frames.time_col,
        getattr(frames, "env_frame", None),
        frames.history if isinstance(frames.history, pd.DataFrame) else None,
    )
    if times is None or times.dropna().empty:
        n = len(labels)
        mid = n // 2
        mask = np.zeros(n, dtype=bool)
        mask[mid:] = True
        return mask
    unique_times = sorted(times.dropna().unique())
    if not unique_times:
        return np.ones(len(labels), dtype=bool)
    mid = unique_times[len(unique_times) // 2]
    return (times >= mid).fillna(False).to_numpy(dtype=bool)


def _run_transfer_stats(
    claim: Claim,
    frames: DiscoveryFrames,
    eval_mask: np.ndarray,
    cfg: DiscoveryConfig,
    frame_name: str,
) -> dict[str, Any]:
    labels = frames.labels
    if not isinstance(labels, pd.DataFrame):
        labels = pd.DataFrame(labels)
    unit_col = frames.unit_col
    label_col = frames.label_col
    y_all = labels[label_col].to_numpy(dtype=int)
    groups_all = labels[unit_col].astype(str).to_numpy()
    if not eval_mask.any():
        return {"frame": frame_name, "error_type": "empty_eval_mask", "ok": False}
    hist = frames.history if isinstance(frames.history, pd.DataFrame) else pd.DataFrame(frames.history)
    missing = [c for c in frames.baseline_cols if c not in hist.columns]
    sb = run_feature(
        claim.feature_code,
        frames.history,
        unit_col,
        groups_all,
        cfg.sandbox_timeout_s,
    )
    if not sb.ok or sb.series is None:
        return {
            "frame": frame_name,
            "ok": False,
            "error_type": sb.error_type or "SandboxFailure",
            "error_tail": (sb.error or "")[-STDERR_TAIL_CHARS:],
        }
    feat = sb.series.reindex(labels[unit_col].astype(str)).to_numpy(dtype=float)
    idx = eval_mask
    x_e = feat[idx]
    y_e = y_all[idx]
    g_e = groups_all[idx]
    rng = np.random.default_rng(seed_from("transfer", claim.id, frame_name))
    res = test_feature(x_e, y_e, g_e, claim.direction, cfg, rng)
    baseline_df = build_baseline_features(
        frames.history,
        unit_col,
        frames.time_col,
        frames.baseline_cols,
        frames.baseline_lag_rows,
    )
    base_e = baseline_df.reindex(labels.loc[idx, unit_col].astype(str)).fillna(0)
    gain, ilo, ihi = incremental_auroc(
        x_e, base_e, y_e, g_e, cfg.bootstrap_b, cfg.alpha, rng,
    )
    all_times = label_times(
        labels,
        unit_col,
        frames.time_col,
        getattr(frames, "env_frame", None),
        frames.history if isinstance(frames.history, pd.DataFrame) else None,
    )
    temporal_ok: bool | None = None
    if all_times is not None and all_times.loc[idx].dropna().any():
        times = all_times.loc[idx].reset_index(drop=True)
        first, second = temporal_halves(times)
        if first.any() and second.any():
            from faultevolve.discovery.stats import signed_effect

            e1 = signed_effect(x_e[first], y_e[first])
            e2 = signed_effect(x_e[second], y_e[second])
            sign_ok = claim.direction == "+"
            temporal_ok = bool((e1 > 0 and e2 > 0) if sign_ok else (e1 < 0 and e2 < 0))
    neg_fp, neg_trials = run_negative_controls(
        {claim.id: feat},
        y_all,
        groups_all,
        np.zeros(len(y_all), dtype=int),
        {claim.id: claim.direction},
        cfg,
        seed_from("transfer_neg", claim.id, frame_name),
    )
    direction_ok = res.direction_ok
    sign_match = direction_ok
    ci_excludes_zero = res.ci_low > 0 or res.ci_high < 0
    transfer_increment_failed = ilo <= 0
    out: dict[str, Any] = {
        "frame": frame_name,
        "ok": True,
        "n": int(idx.sum()),
        "effect": res.effect,
        "ci_low": res.ci_low,
        "ci_high": res.ci_high,
        "direction_ok": direction_ok,
        "temporal_ok": temporal_ok,
        "incr_gain": gain,
        "incr_ci_low": ilo,
        "incr_ci_high": ihi,
        "transfer_increment_failed": transfer_increment_failed,
        "sign_match": sign_match,
        "ci_excludes_zero": ci_excludes_zero,
        "neg_control_fp": neg_fp,
        "neg_control_trials": neg_trials,
        "missing_baseline_cols": missing,
    }
    return out


def run_replay_claim(
    *,
    adapter: DiscoveryDataProvider,
    task_spec: Any,
    experiment_id: str,
    claim_id: str,
    factor_id: str,
    library_path: Path,
    source_discovery_dir: Path,
    art_dir: Path,
    cfg: DiscoveryConfig,
    store: Any,
    mechanism_llm_call: Callable[[list[dict[str, str]]], str],
    log_event: Callable[[str, dict], None],
    enable_tournament: bool = False,
    interrogate: bool = False,
    n_slices: int | None = None,
    transfer_frame: str | None = None,
    allow_val_transfer: bool = False,
    transfer_adapter: DiscoveryDataProvider | None = None,
    transfer_task_spec: Any | None = None,
    allowed_columns: Collection[str] | None = None,
) -> ReplayResult:
    if transfer_frame is not None:
        tf = transfer_frame.strip().lower()
        if tf in FORBIDDEN_TRANSFER_TOKENS:
            raise ReplayError("forbidden_transfer_frame", detail={"frame": tf})
        if tf not in VALID_TRANSFER_FRAMES:
            raise ReplayError("invalid_transfer_frame", detail={"frame": tf})
        if tf == "val" and not allow_val_transfer:
            raise ReplayError("val_transfer_requires_flag")
    else:
        tf = None

    audit = load_source_audit(source_discovery_dir)
    split_salt, confirmation_fraction = audit_split_params(audit)
    cfg.split_salt = split_salt
    cfg.confirmation_fraction = confirmation_fraction
    if n_slices is not None:
        cfg.tournament.n_slices = n_slices

    entries = load_factor_library(library_path, max_candidates=500, allowed_columns=allowed_columns)
    entry = next((e for e in entries if e.factor_id == factor_id), None)
    if entry is None:
        raise ReplayError("factor_not_found", detail={"factor_id": factor_id})

    frozen = load_frozen_direction(source_discovery_dir, claim_id)
    if frozen is None:
        frozen = entry.direction if entry.direction in {"+", "-"} else "+"

    claim = _build_claim(entry, claim_id, experiment_id, frozen, cfg)
    frames = adapter.discovery_frames(task_spec)
    labels = frames.labels
    if not isinstance(labels, pd.DataFrame):
        labels = pd.DataFrame(labels)
    history = frames.history if isinstance(frames.history, pd.DataFrame) else pd.DataFrame(frames.history)
    missing_cols = _missing_input_columns(history, entry.inputs)
    if missing_cols:
        raise ReplayError(
            "missing_column",
            detail={"columns": missing_cols, "factor_id": factor_id},
        )

    unit_col = frames.unit_col
    label_col = frames.label_col
    y_all = labels[label_col].to_numpy(dtype=int)
    groups_all = labels[unit_col].astype(str).to_numpy()
    sb = run_feature(
        claim.feature_code,
        history,
        unit_col,
        groups_all,
        cfg.sandbox_timeout_s,
    )
    if not sb.ok or sb.series is None:
        raise ReplayError(
            "sandbox_failed",
            detail={"error_type": sb.error_type, "error": (sb.error or "")[-STDERR_TAIL_CHARS:]},
        )
    feat = sb.series.reindex(labels[unit_col].astype(str)).to_numpy(dtype=float)
    _, confirm_mask = split_masks(labels, unit_col, split_salt, confirmation_fraction)

    disc = art_dir / "discovery"
    disc.mkdir(parents=True, exist_ok=True)
    cards_path = store.db_path.parent.parent / "knowledge" / "discovered_cards.jsonl"
    cards_before = _sha256_file(cards_path)

    interrogation_lines = 0
    if interrogate:
        interrogation_lines = run_interrogation(
            claim,
            frames.schema_note,
            mechanism_llm_call,
            disc / "interrogation.jsonl",
        )

    tournament_summary: dict[str, Any] = {}
    if enable_tournament:
        cfg.tournament.enabled = True
        handoff = KD2Handoff(
            claims=[claim],
            payloads={claim.id: {"direction": frozen}},
            feature_map={claim.id: feat},
            y=y_all,
            groups=groups_all,
            unit_ids=groups_all,
            confirm_mask=confirm_mask,
            env_frame=getattr(frames, "env_frame", None),
            schema_note=frames.schema_note,
            round_idx=0,
        )
        tstats = TournamentStats()
        tournament = Tournament(cfg, store, experiment_id, mechanism_llm_call, log_event, tstats)
        fr = tournament.run_family(handoff, 0)
        mech_rows = [m.model_dump() for m in fr.mechanisms]
        certs = fr.certificates
        min_det = min(tstats.min_detectable_effects) if tstats.min_detectable_effects else None
        tournament_summary = {
            "mechanisms_proposed": tstats.mechanisms_proposed,
            "matches_played": tstats.matches_played,
            "decisive_matches": tstats.decisive_matches,
            "underpowered_draws": tstats.underpowered_draws,
            "mechanisms_established": tstats.mechanisms_established,
            "mechanisms_refuted": tstats.mechanisms_refuted,
            "certificates_issued": tstats.certificates_issued,
            "min_detectable_effect": min_det,
            "family_id": fr.family_id,
            "fixed_rivals": len(FIXED_RIVALS),
        }
        if tstats.matches_played == 0 and tstats.rounds_skipped:
            tournament_summary["tournament_skipped"] = True
        write_tournament_json(
            art_dir,
            certs,
            mech_rows,
            tournament_summary,
        )

    transfer_out: dict[str, Any] = {}
    if tf is not None:
        t_adapter = transfer_adapter or adapter
        t_spec = transfer_task_spec or task_spec
        try:
            if tf == "val":
                val_fn = getattr(t_adapter, "discovery_frames_val", None)
                if not callable(val_fn):
                    raise ReplayError("val_frames_unavailable")
                t_frames = val_fn(t_spec)
            else:
                t_frames = t_adapter.discovery_frames(t_spec)
        except FileNotFoundError:
            if tf == "backblaze_public_train":
                transfer_out = {"transfer_skipped": "backblaze_data_missing", "ok": True}
            else:
                raise ReplayError("transfer_data_missing", detail={"frame": tf}) from None
        else:
            if tf == "train_late":
                eval_mask = _late_unit_mask(t_frames)
            else:
                eval_mask = np.ones(len(t_frames.labels), dtype=bool)
            transfer_out = _run_transfer_stats(claim, t_frames, eval_mask, cfg, tf)

    cards_after = _sha256_file(cards_path)
    replay_audit = {
        "mode": "replay_claim",
        "claim_id": claim_id,
        "factor_id": factor_id,
        "split_salt": split_salt,
        "confirmation_fraction": confirmation_fraction,
        "frozen_direction": frozen,
        "source_audit_path": str(source_discovery_dir / "data_audit.json"),
    }
    with (disc / "data_audit.json").open("w", encoding="utf-8") as f:
        json.dump(replay_audit, f, indent=2, ensure_ascii=False)
    if transfer_out:
        with (disc / "transfer_summary.json").open("w", encoding="utf-8") as f:
            json.dump(transfer_out, f, indent=2, ensure_ascii=False)

    return ReplayResult(
        ok=True,
        claim_id=claim_id,
        factor_id=factor_id,
        frozen_direction=frozen,
        split_salt=split_salt,
        confirmation_fraction=confirmation_fraction,
        interrogation_lines=interrogation_lines,
        tournament=tournament_summary,
        transfer=transfer_out,
        cards_sha256_before=cards_before,
        cards_sha256_after=cards_after,
    )

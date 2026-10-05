"""Manifest-based discovery / tournament reporting."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class ReportError(Exception):
    pass


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def compute_tokens_per_score_gain_value(
    run_summary: dict[str, Any],
) -> str | float:
    best = run_summary.get("best_score")
    initial = run_summary.get("initial_score")
    total = run_summary.get("total_tokens", 0)
    if best is None or initial is None:
        return "n/a"
    try:
        gain = float(best) - float(initial)
    except (TypeError, ValueError):
        return "n/a"
    if abs(gain) < 1e-9:
        return "n/a"
    return round(float(total) / gain, 4)


def build_token_tier_table(run_summary: dict[str, Any]) -> dict[str, Any]:
    stages = (
        "generate",
        "repair",
        "reflect",
        "knowledge",
        "self_fix",
        "discovery",
        "crossover",
        "tournament",
        "mechanism",
    )
    total = int(run_summary.get("total_tokens") or 0)
    rows: list[dict[str, Any]] = []
    for stage in stages:
        key = f"{stage}_tokens"
        val = int(run_summary.get(key) or 0)
        rows.append(
            {
                "stage": stage,
                "tokens": val,
                "share_pct": round(100.0 * val / total, 2) if total else 0.0,
            }
        )
    discovery_only = {
        "propose_tokens": int(run_summary.get("propose_tokens") or 0),
        "translate_tokens": int(run_summary.get("translate_tokens") or 0),
        "entailment_tokens": int(run_summary.get("entailment_tokens") or 0),
    }
    tested = int(run_summary.get("claims_tested") or 0)
    confirmed = int(run_summary.get("claims_confirmed") or 0) + int(
        run_summary.get("claims_discovered") or 0
    )
    disc_tok = int(run_summary.get("discovery_tokens") or 0)
    return {
        "by_stage": rows,
        "discovery_run": discovery_only,
        "tokens_per_score_gain": compute_tokens_per_score_gain_value(run_summary),
        "tokens_per_candidate_tested": (
            round(disc_tok / tested, 2) if tested else "n/a"
        ),
        "tokens_per_confirmed_claim": (
            round(disc_tok / confirmed, 2) if confirmed else "n/a"
        ),
        "discovery_token_share": run_summary.get("discovery_token_share"),
    }


def build_manifest(art_dir: Path, run_id: str) -> dict[str, Any]:
    run_summary = _load_json(art_dir / "run_summary.json") or {}
    disc = art_dir / "discovery"
    phenomena = _load_json(disc / "phenomena.json") or []
    controls = _load_json(disc / "controls.json") or {}
    mechanisms = _load_json(disc / "mechanisms.json") or []
    certificates = _load_json(disc / "certificates.json") or []
    tournament_results = _load_json(disc / "tournament_results.json") or {}
    theories = _load_json(disc / "theories.json") or []

    numbers: dict[str, Any] = {
        "claims_confirmed": run_summary.get("claims_confirmed", 0),
        "claims_revised": run_summary.get("claims_revised", 0),
        "claims_discovered": run_summary.get("claims_discovered", 0),
        "claims_refuted": run_summary.get("claims_refuted", 0),
        "claims_undetermined": run_summary.get("claims_undetermined", 0),
        "neg_control_false_positives": run_summary.get("neg_control_false_positives", 0),
        "neg_control_fpr": run_summary.get("neg_control_fpr"),
        "mechanisms_proposed": run_summary.get("mechanisms_proposed", 0),
        "mechanisms_established": run_summary.get("mechanisms_established", 0),
        "mechanisms_refuted": run_summary.get("mechanisms_refuted", 0),
        "matches_played": run_summary.get("matches_played", 0),
        "decisive_matches": run_summary.get("decisive_matches", 0),
        "underpowered_draws": run_summary.get("underpowered_draws", 0),
        "certificates_issued": run_summary.get("certificates_issued", 0),
        "mechanism_patches": run_summary.get("mechanism_patches", 0),
        "tournament_tokens": run_summary.get("tournament_tokens", 0),
        "best_score": run_summary.get("best_score", 0),
        "initial_score": run_summary.get("initial_score", 0),
        "total_tokens": run_summary.get("total_tokens", 0),
    }
    planted = run_summary.get("planted_recovery_rate") or {}
    for k, v in planted.items():
        numbers[f"planted_recovery_rate.{k}"] = v

    sources: dict[str, str] = {}
    for name in (
        "run_summary.json",
        "discovery/phenomena.json",
        "discovery/controls.json",
        "discovery/mechanisms.json",
        "discovery/certificates.json",
        "discovery/tournament_results.json",
        "discovery/theories.json",
    ):
        p = art_dir / name
        if p.exists():
            sources[name] = _sha256_file(p)

    funnel_summary = _load_json(disc / "funnel_summary.json") or {}
    token_tiers = build_token_tier_table(run_summary)

    return {
        "run_id": run_id,
        "numbers": numbers,
        "phenomena": phenomena,
        "mechanisms": mechanisms,
        "certificates": certificates,
        "sources": sources,
        "tournament_results": tournament_results,
        "theories": theories,
        "funnel": funnel_summary,
        "token_tiers": token_tiers,
    }


def _n(manifest: dict[str, Any], key: str) -> str:
    v = manifest.get("numbers", {}).get(key)
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def render_json(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False)


def render_md(manifest: dict[str, Any]) -> str:
    nums = manifest.get("numbers", {})
    lines = [
        "# 运行报告",
        "",
        "## 现象与声明",
        f"- 确认: {_n(manifest, 'claims_confirmed')}",
        f"- 修订: {_n(manifest, 'claims_revised')}",
        f"- 发现: {_n(manifest, 'claims_discovered')}",
        f"- 否证: {_n(manifest, 'claims_refuted')}",
        f"- 未决: {_n(manifest, 'claims_undetermined')}",
        "",
        "## 机理锦标赛",
        f"- 提出机理: {_n(manifest, 'mechanisms_proposed')}",
        f"- 成立: {_n(manifest, 'mechanisms_established')}",
        f"- 否证: {_n(manifest, 'mechanisms_refuted')}",
        f"- 对局: {_n(manifest, 'matches_played')}",
        f"- 决定性对局: {_n(manifest, 'decisive_matches')}",
        f"- 平局/功效不足: {_n(manifest, 'underpowered_draws')}",
        f"- 证书: {_n(manifest, 'certificates_issued')}",
        f"- 锦标赛 token: {_n(manifest, 'tournament_tokens')}",
        "",
        "## 进化指标",
        f"- 最优分: {_n(manifest, 'best_score')}",
        f"- 初始分: {_n(manifest, 'initial_score')}",
        f"- 总 token: {_n(manifest, 'total_tokens')}",
        "",
        "## Token 分层",
    ]
    tiers = manifest.get("token_tiers") or {}
    tpsg = tiers.get("tokens_per_score_gain", "n/a")
    lines.append(f"- tokens_per_score_gain: {tpsg}")
    lines.append(
        f"- tokens_per_candidate_tested: {tiers.get('tokens_per_candidate_tested', 'n/a')}"
    )
    lines.append(
        f"- tokens_per_confirmed_claim: {tiers.get('tokens_per_confirmed_claim', 'n/a')}"
    )
    dshare = tiers.get("discovery_token_share")
    if dshare is not None:
        lines.append(f"- discovery_token_share: {dshare}")
    for row in tiers.get("by_stage") or []:
        lines.append(
            f"- {row.get('stage')}: {row.get('tokens')} ({row.get('share_pct')}%)"
        )
    funnel = manifest.get("funnel") or {}
    if funnel:
        lines.extend(["", "## 发现漏斗"])
        for key in (
            "proposed",
            "executable",
            "coverage_ok",
            "deduped",
            "explore_incr",
            "power_gate",
            "frozen",
            "confirmed_stats",
            "discovered_or_confirmed",
            "power_gate_pass",
        ):
            if key in funnel:
                lines.append(f"- {key}: {funnel[key]}")
        if funnel.get("literature_dedup"):
            lines.append(f"- literature_dedup: {funnel['literature_dedup']}")
        if funnel.get("mde_explore_effect_floor") is not None:
            lines.append(f"- mde_explore_effect_floor: {funnel['mde_explore_effect_floor']}")
    disc_run = (manifest.get("token_tiers") or {}).get("discovery_run") or {}
    if disc_run:
        lines.extend(["", "## 发现 run token 子表"])
        for k in ("propose_tokens", "translate_tokens", "entailment_tokens"):
            if k in disc_run:
                lines.append(f"- {k}: {disc_run[k]}")
    return "\n".join(lines) + "\n"


def verify_md(md: str, manifest: dict[str, Any]) -> list[str]:
    allowed: set[str] = set()
    for key in manifest.get("numbers", {}):
        formatted = _n(manifest, key)
        if formatted:
            allowed.add(formatted)
    tiers = manifest.get("token_tiers") or {}
    for key in ("tokens_per_score_gain", "tokens_per_candidate_tested", "tokens_per_confirmed_claim"):
        val = tiers.get(key)
        if val is not None and val != "n/a":
            allowed.add(str(val))
    for row in tiers.get("by_stage") or []:
        tok = row.get("tokens")
        if tok is not None:
            allowed.add(str(int(tok)))
        share = row.get("share_pct")
        if share is not None:
            allowed.add(f"{float(share):.4g}")
    funnel = manifest.get("funnel") or {}
    for key, val in funnel.items():
        if isinstance(val, int):
            allowed.add(str(val))
    mismatches: list[str] = []
    for match in re.finditer(r"-?\d+(?:\.\d+)?", md):
        token = match.group(0)
        if token in {"1", "2", "3"}:
            continue
        if token not in allowed:
            mismatches.append(token)
    return mismatches

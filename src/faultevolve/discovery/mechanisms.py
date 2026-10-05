"""Mechanism rivals and revision for KD2 tournament."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable, Literal

from faultevolve.discovery.schemas import Claim, MatchResult, Mechanism, MechanismRole

FIXED_RIVALS: tuple[MechanismRole, ...] = ("confound", "artifact", "censor", "other")

_ROLE_ABBR: dict[MechanismRole, str] = {
    "claim": "cl",
    "confound": "cf",
    "artifact": "af",
    "censor": "ce",
    "other": "ot",
    "llm_rival": "lr",
}

_PREDICTION_TEMPLATES: dict[MechanismRole, dict[str, Literal[1, -1]]] = {
    "claim": {
        "env_invariance": 1,
        "temporal": 1,
        "dose_response": 1,
        "mediation": 1,
        "heterogeneity": -1,
    },
    "confound": {
        "env_invariance": -1,
        "heterogeneity": 1,
        "temporal": 1,
        "dose_response": 1,
        "mediation": -1,
    },
    "artifact": {
        "env_invariance": -1,
        "heterogeneity": 1,
        "dose_response": -1,
        "temporal": 1,
        "mediation": -1,
    },
    "censor": {
        "temporal": -1,
        "mediation": -1,
        "env_invariance": 1,
        "dose_response": 1,
        "heterogeneity": -1,
    },
    "other": {
        "env_invariance": -1,
        "temporal": -1,
        "dose_response": -1,
        "mediation": -1,
        "heterogeneity": -1,
    },
}

_ALL_TEST_KEYS = ("env_invariance", "temporal", "dose_response", "mediation", "heterogeneity")


def _normalize_predictions(raw: dict[str, Any] | None) -> dict[str, Literal[1, -1]]:
    out: dict[str, Literal[1, -1]] = {k: -1 for k in _ALL_TEST_KEYS}
    if not raw:
        return out
    for k in _ALL_TEST_KEYS:
        v = raw.get(k, -1)
        try:
            iv = int(v)
        except (TypeError, ValueError):
            iv = -1
        out[k] = 1 if iv > 0 else -1
    return out


def _mech_id(experiment_id: str, claim_seq: str, role: MechanismRole, suffix: str = "") -> str:
    return f"M-{experiment_id}-{claim_seq}-{_ROLE_ABBR[role]}{suffix}"


def _claim_seq_from_id(claim_id: str) -> str:
    parts = claim_id.split("-")
    return parts[-1] if parts else "0000"


def _build_mechanism(
    claim: Claim,
    experiment_id: str,
    role: MechanismRole,
    title: str,
    predictions: dict[str, Literal[1, -1]] | None = None,
    suffix: str = "",
) -> Mechanism:
    seq = _claim_seq_from_id(claim.id)
    preds = _normalize_predictions(predictions or _PREDICTION_TEMPLATES[role])
    return Mechanism(
        id=_mech_id(experiment_id, seq, role, suffix),
        claim_id=claim.id,
        role=role,
        title=title or claim.title,
        nodes=["X", "Y"],
        edges=[("X", "Y", "+")],
        predictions=preds,
    )


def propose_rivals(
    claim: Claim,
    schema_note: str,
    llm_call: Callable[[list[dict[str, str]]], str],
    max_rivals: int,
    experiment_id: str,
) -> list[Mechanism]:
    mechs: list[Mechanism] = [
        _build_mechanism(claim, experiment_id, "claim", claim.title),
    ]
    for role in FIXED_RIVALS:
        mechs.append(_build_mechanism(claim, experiment_id, role, f"{role} rival"))

    llm_rivals: list[Mechanism] = []
    prompt = (
        "KD_MECH_RIVALS\n"
        f"title={claim.title}\ncondition={claim.condition}\n"
        f"outcome={claim.outcome}\nscope={claim.scope}\n"
        f"schema_note={schema_note[:500]}\n"
        "Respond with <rivals>[{...}]</rivals> JSON list with title, edges, predictions."
    )
    try:
        text = llm_call([{"role": "user", "content": prompt}])
        m = re.search(r"<rivals>(.*?)</rivals>", text, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            if isinstance(data, list):
                for item in data[:max_rivals]:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title", "llm rival"))
                    preds = _normalize_predictions(item.get("predictions"))
                    seq = _claim_seq_from_id(claim.id)
                    llm_rivals.append(
                        Mechanism(
                            id=_mech_id(experiment_id, seq, "llm_rival", f"{len(llm_rivals)}"),
                            claim_id=claim.id,
                            role="llm_rival",
                            title=title,
                            predictions=preds,
                        )
                    )
    except Exception:
        llm_rivals = []

    mechs.extend(llm_rivals[:max_rivals])
    return mechs


def revise_mechanism(
    m: Mechanism,
    evidence: list[MatchResult],
    llm_call: Callable[[list[dict[str, str]]], str],
    max_patches: int,
) -> Mechanism | None:
    if m.patch_count >= max_patches:
        return None
    prompt = (
        "KD_MECH_REVISE\n"
        f"mechanism={m.title}\n"
        f"evidence={json.dumps([e.model_dump() for e in evidence[:5]], default=str)}\n"
        "Return JSON predictions only."
    )
    try:
        text = llm_call([{"role": "user", "content": prompt}])
        m_json = re.search(r"\{.*\}", text, re.DOTALL)
        preds = _normalize_predictions(json.loads(m_json.group(0)) if m_json else {})
    except Exception:
        preds = dict(m.predictions)
    return m.model_copy(
        update={
            "id": m.id + "r",
            "patch_count": m.patch_count + 1,
            "parent_id": m.id,
            "status": "proposed",
            "predictions": preds,
        }
    )


def prediction_hash(mechs: list[Mechanism]) -> str:
    payload = sorted((m.id, sorted(m.predictions.items())) for m in mechs)
    blob = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def unify(established: list[Mechanism]) -> list[dict]:
    return []

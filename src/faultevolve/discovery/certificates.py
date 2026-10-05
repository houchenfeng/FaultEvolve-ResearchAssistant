"""Refutation certificates for mechanism tournament."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from faultevolve.discovery.schemas import Certificate, MatchResult, Mechanism


def issue(
    mech: Mechanism,
    rival: Mechanism,
    match: MatchResult,
    env: str,
    prereg_hash: str,
    claim_prereg: str,
) -> Certificate:
    return Certificate(
        mechanism_id=mech.id,
        rival_id=rival.id,
        test_id=match.test_id,
        test_type=match.test_type,
        env=env,
        stat=match.stat,
        ci=(match.ci_low, match.ci_high),
        e_value=match.e_raw,
        prereg_hash=prereg_hash or claim_prereg,
        date=datetime.now(timezone.utc).isoformat(),
    )


def write_json(
    art_dir: Path,
    certificates: list[Certificate],
    mechanisms: list[dict[str, Any]],
    tournament_results: dict[str, Any],
) -> None:
    disc = art_dir / "discovery"
    disc.mkdir(parents=True, exist_ok=True)
    with (disc / "certificates.json").open("w", encoding="utf-8") as f:
        json.dump([c.model_dump() for c in certificates], f, indent=2, ensure_ascii=False)
    with (disc / "mechanisms.json").open("w", encoding="utf-8") as f:
        json.dump(mechanisms, f, indent=2, ensure_ascii=False)
    with (disc / "tournament_results.json").open("w", encoding="utf-8") as f:
        json.dump(tournament_results, f, indent=2, ensure_ascii=False)
    with (disc / "theories.json").open("w", encoding="utf-8") as f:
        json.dump([], f)

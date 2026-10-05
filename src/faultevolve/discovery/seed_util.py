"""Deterministic seeds for discovery KD2."""

from __future__ import annotations

import hashlib


def seed_from(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).digest()[:4]
    return int.from_bytes(digest, "big")

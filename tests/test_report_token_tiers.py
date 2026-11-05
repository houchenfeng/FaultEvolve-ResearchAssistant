"""Report token tier helpers."""

from __future__ import annotations

from faultevolve.discovery.report import (
    build_token_tier_table,
    compute_tokens_per_score_gain_value,
)


def test_tokens_per_score_gain_na_for_discovery_only():
    assert compute_tokens_per_score_gain_value({"best_score": 1, "initial_score": 1}) == "n/a"
    assert compute_tokens_per_score_gain_value({}) == "n/a"


def test_token_tier_table_discovery_efficiency():
    table = build_token_tier_table(
        {
            "total_tokens": 1000,
            "generate_tokens": 400,
            "discovery_tokens": 100,
            "claims_tested": 2,
            "claims_confirmed": 0,
            "claims_discovered": 0,
            "discovery_token_share": 0.1,
        }
    )
    assert table["tokens_per_score_gain"] == "n/a"
    assert table["tokens_per_confirmed_claim"] == "n/a"
    assert table["tokens_per_candidate_tested"] == 50.0

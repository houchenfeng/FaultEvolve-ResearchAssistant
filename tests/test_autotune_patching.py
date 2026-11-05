"""Patch parse/apply tests."""

from __future__ import annotations

import ast

import pytest

from faultevolve.optimization.patching import (
    Patch,
    PatchRejectReason,
    apply_patch,
    module_spans,
    parse_patch,
    source_hash,
)

PARENT = """x = 1
# FE-BLOCK-BEGIN feature
feat = 2
# FE-BLOCK-END feature
# FE-BLOCK-BEGIN model
model = 3
# FE-BLOCK-END model
"""


def _static_ok(code: str) -> str:
    return ""


def test_pt1_single_hunk():
    from faultevolve.optimization.patching import Hunk

    ph = source_hash(PARENT)
    patch = Patch(ph, "feature", [Hunk("feat = 2", "feat = 99")])
    parent_copy = PARENT
    res = apply_patch(parent_copy, patch, static_check=_static_ok, max_hunks=3, max_changed_lines=10)
    assert res.ok
    assert parent_copy == PARENT
    assert "feat = 99" in (res.code or "")


def test_pt8_unified_diff_rejected():
    out = parse_patch("--- a.py\n+++ b.py\n")
    assert hasattr(out, "ok") and out.ok is False
    assert out.reason == PatchRejectReason.UNSUPPORTED_FORMAT


def test_pt9_no_blocks():
    assert module_spans("print(1)\n") == {}

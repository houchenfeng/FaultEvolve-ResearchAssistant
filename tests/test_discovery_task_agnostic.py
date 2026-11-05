"""Ensure the discovery package stays task-agnostic.

Two layers, because the token scan alone only catches symptoms:

* the word scan below catches task vocabulary that leaked into the package;
* the import scan catches the *coupling* that put it there -- ``discovery`` may
  depend on the task-neutral contract (``faultevolve.tasks.protocol``) but never
  on a concrete adapter such as ``faultevolve.tasks.hdd_adapter``.  That import
  is exactly what made ``factors.py`` hard-code HDD column names.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "faultevolve" / "discovery"


def test_discovery_sources_task_agnostic():
    pattern = re.compile(r"smart|serial|hdd|vendor", re.IGNORECASE)
    hits: list[str] = []
    for path in ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{i}:{line.strip()}")
    assert hits == []


def test_discovery_imports_only_the_task_neutral_protocol():
    offenders: list[str] = []
    for path in ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if "faultevolve.tasks" not in line:
                continue
            if "faultevolve.tasks.protocol" in line:
                continue
            offenders.append(f"{path.relative_to(ROOT)}:{i}:{line.strip()}")
    assert offenders == []

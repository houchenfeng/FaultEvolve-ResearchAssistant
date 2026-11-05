"""Engine sources must not hardcode dataset adapters."""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src" / "faultevolve"

_PATTERN = re.compile(
    r"smart|hdd|vendor|backblaze|alibaba|smartmem|dimm|disk_id|ssd",
    re.IGNORECASE,
)

#: Pinned by source text, not line number: inserting config fields above these
#: lines must not break the gate.
_ALLOWLIST = {
    (_SRC / "common/textutil.py", 'def vendor_from_model(model_name: str) -> str:'),
    (_SRC / "common/textutil.py", '"""Extract vendor prefix from disk model name."""'),
    (_SRC / "config.py", '"""Task adapter selection (default keeps legacy HDD MVP behavior)."""'),
    (_SRC / "config.py", 'adapter: str = "hdd"'),
}

_SCAN_DIRS = ["cloud", "common", "knowledge", "worker"]
_SCAN_FILES = [_SRC / "config.py"]


def _hits() -> set[tuple[Path, str]]:
    found: set[tuple[Path, str]] = set()
    for path in [
        *(p for sub in _SCAN_DIRS for p in (_SRC / sub).rglob("*.py")),
        *_SCAN_FILES,
    ]:
        for line in path.read_text(encoding="utf-8").splitlines():
            if _PATTERN.search(line):
                found.add((path, line.strip()))
    return found


def test_engine_sources_task_agnostic():
    assert _hits() == _ALLOWLIST


def test_new_adapters_not_imported_by_engine():
    for path in (_SRC / "cloud").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "backblaze_adapter" not in text
        assert "ssd_alibaba_adapter" not in text
        assert "smartmem_adapter" not in text

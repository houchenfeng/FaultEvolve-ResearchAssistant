"""Ensure benchmark/hdd_mvp protected paths remain byte-identical."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_HDD = _REPO / "benchmark/hdd_mvp"

_EXPECTED_SHA256: dict[str, str] = {
    "evaluator.py": "cddfaaab6dbe2ee661b634bf39f3585b3b5821c04e84944ea084455c333523a9",
    "init.py": "91744b4ba390ed377b8eb8884a5c0b19e1407765824f00aec5e857aad208caf2",
    "problem.md": "0f417e318421f36b98f1fbcaa823c7699bb08d2069393834e04a07fd151a4004",
    "prompt.md": "8a70862b64982193847bcb1eac74ddb982b85c90a0e64306b364d04f12f7b97a",
    "prepare_data.py": "723a4e773fd25ad2423cc0c876a9505207613b92a4c6611d60f0e72e2b239169",
    "knowledge/cards.jsonl": "9b4a1e384d6f39e6b2c54e42ca2de0982c0b804f041fa16d0d5a86ad4678eddb",
    "data/public/train_history.csv.gz": "f033f35b786108567351b3b5d9882bc171679c75c2e24e300f11df95e1505624",
    "data/public/train_labels.csv": "64b798410d78302ff77e4312b6c930edceee60c56d820f927be1b6804d503b27",
    "data/public/val_history.csv.gz": "0b8e75b409c28c8ee1a45a6e187c8e01bf7829c830727e3cff4850a035bc9091",
    "data/public/val_index.csv": "9abf34bcb5bbbc9cf8f2fdeabad505959418ed0aaed3ab61d5d72552820a44d8",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.mark.parametrize("rel,expected", _EXPECTED_SHA256.items())
def test_hdd_mvp_files_byte_identical(rel, expected):
    path = _HDD / rel
    assert path.exists(), rel
    assert _sha256(path) == expected

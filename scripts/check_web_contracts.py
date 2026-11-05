#!/usr/bin/env python
"""Fail the build when the committed front-end contract drifts from Python (TODO §1.6).

Regenerates every contract in a temporary directory, compares it with the
committed copy under ``web/openapi/``, lists what changed and exits non-zero.

Two notes that matter on this project:

* Comparison is done on **content with newlines normalised to LF**. This machine
  runs with ``core.autocrlf=true`` and the repo has no ``.gitattributes``, so the
  worktree copy of a committed LF file is CRLF. A byte-for-byte compare would
  therefore go red unconditionally -- the same trap documented in
  docs/plans/WEBUI_BASELINE.md §4.4. A pure line-ending difference is reported
  as a note, not as drift.
* Only files listed in ``export_web_contracts.CONTRACT_FILES`` are compared, so
  unrelated edits under ``web/`` are never mistaken for contract drift.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from export_web_contracts import CONTRACT_FILES, OPENAPI_DIR, build_all  # noqa: E402

SYNC_HINT = "run:  pnpm --dir web sync:contracts"


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_committed(path: Path) -> tuple[str | None, bool]:
    """Return ``(text, had_crlf)``; ``text`` is None when the file is absent."""
    if not path.exists():
        return None, False
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    had_crlf = "\r\n" in text
    return _normalise(text), had_crlf


def main() -> int:
    expected = build_all()
    missing: list[str] = []
    drifted: list[tuple[str, str, str]] = []
    notes: list[str] = []

    for name, _ in CONTRACT_FILES:
        path = OPENAPI_DIR / name
        committed, had_crlf = _read_committed(path)
        generated = expected[name]
        if committed is None:
            missing.append(name)
            continue
        if had_crlf:
            notes.append(f"{name}: worktree uses CRLF, content compared as LF")
        if committed != generated:
            drifted.append((name, committed, generated))

    if not missing and not drifted:
        print(f"contract check OK: {len(CONTRACT_FILES)} files match the Python source")
        for note in notes:
            print(f"  note: {note}")
        return 0

    if missing:
        print("missing contract files:")
        for name in missing:
            print(f"  - web/openapi/{name}")
    for name, committed, generated in drifted:
        print(f"drifted: web/openapi/{name}")
        diff = difflib.unified_diff(
            committed.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile=f"committed/{name}",
            tofile=f"regenerated/{name}",
            n=2,
        )
        for index, line in enumerate(diff):
            if index >= 40:
                print("  ... diff truncated ...")
                break
            print("  " + line.rstrip("\n"))

    print()
    print(f"the front-end contract is out of date; {SYNC_HINT}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

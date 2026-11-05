#!/usr/bin/env python
"""Turn a real run directory into a committed replay fixture, safely.

Why this is in the repo
-----------------------
The phase-0 baseline froze the first fixture with a redaction script that was
**deliberately kept outside the repository** (``WEBUI_BASELINE.md`` §6.4), which
left the fixture unreproducible: nobody could tell what had been redacted or
re-derive the file. This is that script, committed, so every fixture run in
``tests/fixtures/runs/`` can be traced back to a source run and a documented
redaction pass.

What it does
------------
1. copies the run (skipping ``fe.db-shm`` / ``fe.db-wal`` / ``fe.db-journal``);
2. redacts absolute host paths and secret-shaped strings in every text file;
3. redacts the same patterns inside every TEXT column of ``fe.db``, then switches
   the database to ``journal_mode=DELETE`` and ``VACUUM``s it, so the fixture is a
   single self-contained file;
4. re-scans the result and **exits non-zero** if anything still looks like a host
   path, a holdout reference, or a credential -- a fixture that fails this check
   must not be committed.

Deliberately not done: rewriting JSON formatting. Redaction happens on the raw
text so the original byte layout survives; every JSON/JSONL file is re-parsed
afterwards to prove it is still valid.

Usage::

    .venv/Scripts/python.exe scripts/build_run_fixture.py <src_run_dir> <dst_run_dir>
    .venv/Scripts/python.exe scripts/build_run_fixture.py --check <run_dir>
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

REDACTED = "<REDACTED_PATH>"

#: Host paths. The drive-letter form requires that the letter is not preceded by
#: another word character, so that a JSON escape such as ``"exist:\n"`` is not
#: mistaken for a path, and it accepts between one and four backslashes per
#: separator: a path written straight into a file uses one, a path inside a JSON
#: string uses two, and a JSON string nested in one uses four. Matching only the
#: leading ``C:\`` of ``C:\\Users\\..`` leaves ``\Users`` behind, which is an
#: invalid JSON escape -- the redacted file then no longer parses (measured on a
#: real run whose ``smoke_data_built`` event carried a temp directory).
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\{1,4}[^\\/:*?\"<>|\r\n]+)+"),
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\{1,4}(?=[\"'\s\])]|$)"),
    re.compile(r"/(?:home|root|tmp|mnt|media|Users|var|opt|srv|etc)/[^\s\"'<>]*"),
)

#: Credential shapes. Nothing here may survive into a fixture.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"(?:DASHSCOPE|MIYANG|FE|OPENALEX)_API_KEY\s*[=:]\s*\S+"),
)

#: Words that must never appear in a committed fixture.
_FORBIDDEN = ("holdout",)

_SKIP_NAMES = ("fe.db-shm", "fe.db-wal", "fe.db-journal")


def _redact(text: str) -> tuple[str, int]:
    hits = 0
    for pattern in _PATTERNS + _SECRET_PATTERNS:
        text, n = pattern.subn(REDACTED, text)
        hits += n
    return text, hits


def _is_texty(path: Path) -> bool:
    if path.suffix.lower() in {
        ".json", ".jsonl", ".log", ".txt", ".md", ".yaml", ".yml", ".csv", ".py",
    }:
        return True
    return False


def redact_files(root: Path) -> dict[str, int]:
    stats: dict[str, int] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in _SKIP_NAMES:
            continue
        if not _is_texty(path):
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        new, hits = _redact(text)
        if hits:
            path.write_text(new, encoding="utf-8", newline="")
            stats[str(path.relative_to(root))] = hits
        if path.suffix == ".json":
            json.loads(new)  # still valid?
        elif path.suffix == ".jsonl":
            for line in new.splitlines():
                if line.strip():
                    json.loads(line)
    return stats


def redact_database(db_path: Path) -> dict[str, int]:
    """Redact every TEXT column, then make the file self-contained."""
    stats: dict[str, int] = {}
    if not db_path.is_file():
        return stats

    con = sqlite3.connect(str(db_path))
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        tables = [
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            if not row[0].startswith("sqlite_")
        ]
        for table in tables:
            columns = [row[1] for row in con.execute(f'PRAGMA table_info("{table}")')]
            for column in columns:
                rows = con.execute(
                    f'SELECT rowid, "{column}" FROM "{table}" WHERE typeof("{column}")=\'text\''
                ).fetchall()
                for rowid, value in rows:
                    if not isinstance(value, str):
                        continue
                    new, hits = _redact(value)
                    if hits:
                        con.execute(
                            f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?', (new, rowid)
                        )
                        key = f"{table}.{column}"
                        stats[key] = stats.get(key, 0) + hits
        con.commit()
        con.execute("VACUUM")
        con.commit()
    finally:
        con.close()

    for name in _SKIP_NAMES:
        sidecar = db_path.parent / name
        if sidecar.exists():
            sidecar.unlink()
    return stats


def scan(root: Path) -> list[str]:
    """Return the list of remaining problems (empty means the fixture is clean)."""
    problems: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in _PATTERNS:
            for match in pattern.finditer(text):
                snippet = match.group(0)
                # The redaction marker itself contains no slash/drive letter.
                if REDACTED in snippet:
                    continue
                problems.append(f"{path.relative_to(root)}: host path {snippet[:80]!r}")
        for pattern in _SECRET_PATTERNS:
            for match in pattern.finditer(text):
                if REDACTED in match.group(0):
                    continue
                problems.append(f"{path.relative_to(root)}: secret-shaped string")
        low = text.lower()
        for word in _FORBIDDEN:
            if word in low:
                problems.append(f"{path.relative_to(root)}: forbidden word {word!r}")

    db_path = root / "fe.db"
    if db_path.is_file():
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = [
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                if not row[0].startswith("sqlite_")
            ]
            for table in tables:
                columns = [row[1] for row in con.execute(f'PRAGMA table_info("{table}")')]
                for column in columns:
                    for (value,) in con.execute(
                        f'SELECT "{column}" FROM "{table}" WHERE typeof("{column}")=\'text\''
                    ):
                        if not isinstance(value, str):
                            continue
                        for pattern in _PATTERNS + _SECRET_PATTERNS:
                            if pattern.search(value):
                                problems.append(f"fe.db {table}.{column}: pattern hit")
                                break
                        if any(word in value.lower() for word in _FORBIDDEN):
                            problems.append(f"fe.db {table}.{column}: forbidden word")
        finally:
            con.close()

    for name in _SKIP_NAMES:
        if (root / name).exists():
            problems.append(f"sidecar {name} must not be shipped")
    return problems


def build(src: Path, dst: Path) -> int:
    if not src.is_dir():
        print(f"FAIL source run not found: {src}", file=sys.stderr)
        return 1
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*_SKIP_NAMES))

    file_stats = redact_files(dst)
    db_stats = redact_database(dst / "fe.db")

    print(f"copied {src} -> {dst}")
    print("redactions:")
    if not file_stats and not db_stats:
        print("  (none needed)")
    for name, hits in sorted(file_stats.items()):
        print(f"  {name}: {hits}")
    for name, hits in sorted(db_stats.items()):
        print(f"  fe.db {name}: {hits}")

    problems = scan(dst)
    if problems:
        print("\nSCAN FAILED -- this fixture must not be committed:", file=sys.stderr)
        for line in problems[:40]:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("\nscan clean: no host paths, no holdout mentions, no secret-shaped strings")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src", nargs="?", help="source run directory")
    parser.add_argument("dst", nargs="?", help="destination fixture directory")
    parser.add_argument("--check", metavar="RUN_DIR", help="only scan an existing fixture")
    args = parser.parse_args()

    if args.check:
        problems = scan(Path(args.check))
        for line in problems:
            print(f"FAIL {line}", file=sys.stderr)
        if problems:
            return 1
        print(f"{args.check}: clean")
        return 0

    if not args.src or not args.dst:
        parser.error("src and dst are required unless --check is used")
    return build(Path(args.src), Path(args.dst))


if __name__ == "__main__":
    raise SystemExit(main())

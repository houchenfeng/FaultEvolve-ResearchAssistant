"""``scripts/build_run_fixture.py`` really redacts, and really keeps files readable.

The gate exists so a fixture can be committed at all, so these tests are about the
two ways it can fail silently:

* it eats part of a host path and leaves the rest -- which on Windows is worse than
  a leak, because the leftover ``\\Users`` inside a JSON string is an invalid escape
  and the redacted ``events.jsonl`` no longer parses. Measured: a real run's
  ``smoke_data_built`` event carries a temp directory, and the drive pattern used to
  match only the leading ``C:\\`` of ``C:\\\\Users\\\\..``;
* it reports clean while a host path, a private-test-set name or a key shape is
  still in the tree or in ``fe.db``.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_run_fixture.py"


@pytest.fixture(scope="module")
def builder():
    spec = importlib.util.spec_from_file_location("build_run_fixture", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: A Windows path as the engine holds it. ``json.dumps`` escapes the separators, so
#: writing these into a JSON file produces the two-backslash form the redactor has
#: to consume whole; ``NESTED`` is what a path looks like one JSON layer deeper.
WIN_TEMP = "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\fe_smoke_69h8z96k"
WIN_RUN = "C:\\Users\\Administrator\\faultevolve\\build\\island_runs\\15l4nd01"
NESTED = json.dumps({"artifact": WIN_RUN})
POSIX = "/home/faultevolve/runs/15l4nd01"


def _write_run(src: Path) -> Path:
    """A minimal run directory shaped like what the engine writes."""
    src.mkdir(parents=True)
    (src / "run_summary.json").write_text(
        json.dumps(
            {"output_dir": WIN_TEMP, "artifacts": WIN_RUN, "nested": NESTED, "exp": "15l4nd01"}
        ),
        encoding="utf-8",
    )
    (src / "events.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "smoke_data_built", "payload": {"temp_dir": WIN_TEMP}}),
                json.dumps({"type": "iteration_complete", "payload": {"out": WIN_RUN}}),
                json.dumps({"type": "node_created", "payload": {"dir": POSIX}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    logs = src / "logs"
    logs.mkdir()
    (logs / "engine.log").write_text(
        f"wrote {WIN_RUN}\nrelative build\\island_runs stays\n", encoding="utf-8"
    )
    con = sqlite3.connect(src / "fe.db")
    con.execute("CREATE TABLE node (id TEXT, evidence_json TEXT)")
    con.execute(
        "INSERT INTO node VALUES (?, ?)",
        ("a1b2c3", json.dumps({"evaluation": {"artifact": WIN_TEMP}})),
    )
    con.execute("INSERT INTO node VALUES (?, ?)", ("d4e5f6", "exist:\\n keep me"))
    con.commit()
    con.close()
    return src


def test_host_paths_redacted_and_every_json_still_parses(builder, tmp_path):
    src = _write_run(tmp_path / "run")
    dst = tmp_path / "fixture"

    assert builder.build(src, dst) == 0

    summary = json.loads((dst / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["output_dir"] == builder.REDACTED
    assert summary["artifacts"] == builder.REDACTED
    assert WIN_RUN not in summary["nested"] and WIN_TEMP not in json.dumps(summary)

    events = [
        json.loads(line)
        for line in (dst / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert events[0]["payload"]["temp_dir"] == builder.REDACTED
    assert events[1]["payload"]["out"] == builder.REDACTED
    assert events[2]["payload"]["dir"] == builder.REDACTED

    con = sqlite3.connect(dst / "fe.db")
    rows = dict(con.execute("SELECT id, evidence_json FROM node"))
    con.close()
    assert json.loads(rows["a1b2c3"])["evaluation"]["artifact"] == builder.REDACTED
    # A look-alike that is not a path must survive untouched, or redaction is a
    # blunt instrument that rewrites evaluation evidence.
    assert rows["d4e5f6"] == "exist:\\n keep me"

    log = (dst / "logs" / "engine.log").read_text(encoding="utf-8")
    assert builder.REDACTED in log
    assert "build\\island_runs stays" in log


def test_bare_drive_root_is_redacted_and_stays_valid_json(builder, tmp_path):
    """A root with no components is still a host path -- and still needs escaping care.

    A path component may contain a space (real ones do), so redaction eats the prose
    that follows a path up to the closing quote. That over-redaction is the safe
    direction; the test therefore asserts nothing survives that looks like a host
    path, not the exact remaining wording.
    """
    src = tmp_path / "run"
    src.mkdir()
    (src / "run_summary.json").write_text(
        json.dumps({"runs_dir": "C:\\", "note": "wrote C:\\ somewhere"}), encoding="utf-8"
    )
    dst = tmp_path / "fixture"

    assert builder.build(src, dst) == 0

    summary = json.loads((dst / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["runs_dir"] == builder.REDACTED
    assert summary["note"].startswith("wrote ")
    assert builder.REDACTED in summary["note"]
    assert not any(p.search(json.dumps(summary)) for p in builder._PATTERNS)


def test_scanner_rejects_a_host_path_left_after_redaction(builder, tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "run_summary.json").write_text(
        json.dumps({"output_dir": WIN_TEMP}), encoding="utf-8"
    )
    problems = builder.scan(fixture)
    assert problems, "an escaped host path must not pass the scan"
    assert "run_summary.json" in problems[0]


def test_scanner_rejects_secrets_and_private_split_words(builder, tmp_path):
    fixture = tmp_path / "fixture"
    (fixture / "logs").mkdir(parents=True)
    (fixture / "logs" / "engine.log").write_text(
        "DASHSCOPE_API_KEY=sk-abcdefgh12345\nreading holdout rows\n", encoding="utf-8"
    )
    problems = "\n".join(builder.scan(fixture))
    assert "secret-shaped string" in problems
    assert "forbidden word" in problems


def test_scanner_rejects_database_sidecars(builder, tmp_path):
    fixture = _write_run(tmp_path / "fixture")
    (fixture / "fe.db-wal").write_bytes(b"journal")
    assert "sidecar" in "\n".join(builder.scan(fixture))
    builder.redact_database(fixture / "fe.db")
    assert not (fixture / "fe.db-wal").exists()

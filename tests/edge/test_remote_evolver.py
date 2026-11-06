"""Remote evolver loop and the outbound data gate, without SSH or an LLM."""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from pathlib import Path

import pytest

from faultevolve.edge import boundary

REPO = Path(__file__).resolve().parents[2]


def _load_evolver():
    spec = importlib.util.spec_from_file_location("edge_remote_evolver", REPO / "scripts" / "edge_remote_evolver.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_extract_code_takes_longest_block_and_keeps_contract() -> None:
    ev = _load_evolver().Evolver
    text = "Use a calibrated threshold.\n```python\nx = 1\n```\n```python\nimport argparse\n# --data-dir --out\nprint(1)\n```"
    assert "argparse" in ev.extract_code(text)
    with pytest.raises(ValueError):
        ev.extract_code("```python\nprint('no contract')\n```")
    with pytest.raises(ValueError):
        ev.extract_code("no code at all")


def test_gate_only_lets_whitelisted_scalars_out() -> None:
    packet = boundary.gate("t", {
        "candidate_id": "abc", "combined_score": 39.380531, "caught": 6,
        "serial_numbers": ["A", "B"], "smart_rows": [[1, 2]], "secret": "x", "auprc": [0.1],
    })
    assert packet["allowed"] == {"candidate_id": "abc", "combined_score": 39.38053, "caught": 6}
    assert {b["field"] for b in packet["blocked"]} == {"serial_numbers", "smart_rows", "secret", "auprc"}


def test_error_kind_drops_the_message() -> None:
    from faultevolve.edge.local_eval import error_kind

    err = ('exit 1: Traceback (most recent call last):\n  File "C:\\tmp\\abc.py", line 368, in <module>\n'
           '    main()\n  File "C:\\tmp\\abc.py", line 120, in main\nKeyError: \'ZA1234 serial\'')
    assert error_kind(err, "abc.py") == "KeyError @ line 120"
    assert error_kind("timeout after 900s", "abc.py") == "timeout"
    assert error_kind("3 query disks have no prediction", "abc.py") == "invalid_output"


def test_replay_loop_round_trip(tmp_path: Path) -> None:
    mod = _load_evolver()
    root = tmp_path / "session"
    (root / "seeds").mkdir(parents=True)
    (root / "replay").mkdir()
    (root / "task").mkdir()
    (root / "task" / "prompt.md").write_text("task", encoding="utf-8")
    (root / "seeds" / "init.py").write_text("# --data-dir --out\n", encoding="utf-8")
    (root / "replay" / "01_worse.py").write_text("# --data-dir --out worse\n", encoding="utf-8")
    (root / "replay" / "02_better.py").write_text("# --data-dir --out better\n", encoding="utf-8")
    (root / "config.json").write_text(json.dumps({"mode": "demo", "provider": "replay", "generations": 2,
                                                  "replay_think_s": 0}), encoding="utf-8")
    scores = {"init": 22.8, "worse": 12.9, "better": 39.4}
    seen: list[str] = []

    def laptop() -> None:
        deadline = time.time() + 30
        while time.time() < deadline and len(seen) < 3:
            for meta in sorted((root / "candidates").glob("*.json")):
                cid = meta.stem
                if cid in seen:
                    continue
                seen.append(cid)
                allowed = boundary.gate("t", {"candidate_id": cid, "validity": 1,
                                              "combined_score": scores[cid], "smart_rows": [[0]]})["allowed"]
                (root / "results" / f"{cid}.json").write_text(json.dumps(allowed), encoding="utf-8")
            time.sleep(0.05)

    t = threading.Thread(target=laptop, daemon=True)
    ev = mod.Evolver(root)
    t.start()
    ev.run()
    t.join(5)

    status = json.loads((root / "status.json").read_text(encoding="utf-8"))
    assert seen == ["init", "worse", "better"]
    assert status["state"] == "done"
    assert status["best"]["id"] == "better"
    assert [h["parent"] for h in status["history"]] == [None, "init", "init"]
    # Nothing but whitelisted scalars ever reached the server side.
    for cid in seen:
        assert "smart_rows" not in json.loads((root / "results" / f"{cid}.json").read_text(encoding="utf-8"))

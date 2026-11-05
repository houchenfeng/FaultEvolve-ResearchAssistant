"""Generate the *deliberately failing* demo run fixture (TODO §12.4 E2E-04).

Why this exists
---------------
E2E-04 has to walk "故意失败候选 → 查看失败原因 → 查看 repair 关联 → 刷新保持一致".
No run the engine produces under ``--mock`` contains a failed candidate: the
mock path always succeeds, and the committed demo run
(``hdd_mvp_demo_7510f100``) has every node at ``status=done`` -- its node
``8a7c8524`` even carries the intent "Intentionally use wrong LightGBM parameter
to trigger repair" but evaluates fine, so pointing a test at it would prove
nothing.

So this script *synthesises* a second run, and says so: every field below is
placed where the engine places it, not where it would be convenient for the UI.
Concretely, ``cloud/tree.py`` and ``cloud/engine.py`` decide the shapes:

* ``tree.py:459`` ``create_repair_node`` -- the repairer's ``parent_id`` is the
  **failed node's parent**, its ``depth`` equals the failed node's, and it
  carries ``operator=repair`` + ``repair_parent_id=<failed id>``. So the repair
  edge is *not* the parent edge, and the two never overlap.
* ``engine.py:2009`` ``increment_repair_count(failed_node.id)`` and
  ``tree.py:235`` ``mark_repair_attempted`` -- ``repair_count`` /
  ``repair_attempted`` live on the **failed** node.
* ``engine.py:2006/2166`` ``mark_repair_exhausted(root.id)`` -- ``exhausted``
  lands on the **root of the repair chain**, i.e. the original failed node.

Usage::

    python scripts/make_failure_fixture.py            # writes into tests/fixtures/runs
    python scripts/make_failure_fixture.py --check    # verify only, no write

The output is deterministic: same input -> byte-identical files, so re-running
it produces no diff.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO / "tests" / "fixtures" / "runs"
DEMO_RUN_ID = "hdd_mvp_demo_7510f100"

#: Deliberately failing run. ``4b81c0d2`` is the experiment id inside the
#: artifacts; the directory (and therefore the run id) is prefixed the same way
#: the real CLI names run directories.
EXPERIMENT_ID = "4b81c0d2"
FAIL_RUN_ID = f"hdd_mvp_faildemo_{EXPERIMENT_ID}"

ROOT = "c0ffee01"          # init, evaluated
FAILED_A = "fa11ed01"      # refine -> sandbox error, repaired successfully
REPAIR_A = "f1xed001"      # repair of FAILED_A, done
FAILED_B = "fa11ed02"      # refine -> timeout, repair exhausted
REPAIR_B = "f1xed002"      # repair of FAILED_B, itself invalid

CREATED_AT = "2026-10-03T09:00:00.000000+00:00"

#: Timeline of the synthetic run. Kept in the same order the engine would emit
#: it so the event stream tells the same story as the tree.
EVENTS: list[tuple[str, dict[str, object]]] = [
    ("init_evaluated", {
        "node_id": ROOT,
        "score": 22.807355886970594,
        "metric": {"f1_p10": 0.22935, "auprc": 0.19546, "recall_at_far": 0.27381,
                   "run_time_s": 3.66, "split": "val"},
    }),
    ("smoke_data_built", {"path": "<REDACTED_PATH>", "sample_fraction": 0.02}),
    ("node_created", {"node_id": FAILED_A, "operator": "refine", "parent_id": ROOT}),
    ("smoke_failed", {
        "node_id": FAILED_A,
        "error_class": "sandbox_error",
        "reason": "LightGBM 参数 'num_leavs' 未知，候选进程退出码 1",
    }),
    ("iteration_complete", {"node_id": FAILED_A, "status": "invalid", "score": 0.0}),
    ("node_created", {"node_id": REPAIR_A, "operator": "repair", "repair_parent_id": FAILED_A}),
    ("repair_success", {"node_id": REPAIR_A, "repair_parent_id": FAILED_A,
                        "attempt": 1, "score": 18.5124}),
    ("iteration_complete", {"node_id": REPAIR_A, "status": "done", "score": 18.5124}),
    ("node_created", {"node_id": FAILED_B, "operator": "refine", "parent_id": ROOT}),
    ("smoke_failed", {
        "node_id": FAILED_B,
        "error_class": "timeout",
        "reason": "候选在 900s 内未写出 pred.csv",
    }),
    ("iteration_complete", {"node_id": FAILED_B, "status": "invalid", "score": 0.0}),
    ("node_created", {"node_id": REPAIR_B, "operator": "repair", "repair_parent_id": FAILED_B}),
    ("repair_smoke_failed", {"node_id": REPAIR_B, "repair_parent_id": FAILED_B, "attempt": 1}),
    ("repair_failed", {"node_id": REPAIR_B, "repair_parent_id": FAILED_B,
                       "reason": "达到最大修复次数（3），链根已标记 exhausted"}),
    ("iteration_complete", {"node_id": REPAIR_B, "status": "invalid", "score": 0.0}),
    ("run_finished", {"status": "finished", "stop_reason": "max_iterations",
                      "best_node_id": ROOT, "best_score": 22.807355886970594}),
]


def _ts(index: int) -> str:
    """Deterministic timestamps, 4 s apart, starting at 09:00:05."""
    import datetime as _dt

    base = _dt.datetime(2026, 10, 3, 9, 0, 5, tzinfo=_dt.timezone.utc)
    return (base + _dt.timedelta(seconds=4 * index)).isoformat()


# --------------------------------------------------------------------------
# programs
# --------------------------------------------------------------------------

_PROGRAM_TEMPLATE = '''"""HDD failure prediction candidate (fixture, synthetic).

I/O contract: python {node_id}.py --data-dir <dir> --split <val|test> --out <pred.csv>
"""

import argparse
import os

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--split", default="val")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    history = pd.read_csv(os.path.join(args.data_dir, "train_history.csv.gz"))
    labels = pd.read_csv(os.path.join(args.data_dir, "train_labels.csv"))
    index = pd.read_csv(os.path.join(args.data_dir, f"{{args.split}}_index.csv"))
{body}
    out = index[["serial_number"]].copy()
    out["score"] = model.predict_proba(feats)[:, 1]
    out["alarm"] = (out["score"] >= threshold).astype(int)
    out.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
'''


def _program(node_id: str, body: str) -> str:
    return _PROGRAM_TEMPLATE.format(node_id=node_id, body=body)


PROGRAMS: dict[str, tuple[str, str]] = {
    # node id -> (program body, intent)
    ROOT: (
        '''
    merged = history.merge(labels, on=["serial_number", "model", "cutoff_date"])
    feats = merged.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()
    model = LogisticRegression(class_weight="balanced", max_iter=200)
    model.fit(feats, merged["label"].to_numpy())
    threshold = 0.5
    feats = index.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()
''',
        "Initial solution: logistic regression on the cutoff-day SMART snapshot.",
    ),
    FAILED_A: (
        '''
    import lightgbm as lgb

    merged = history.merge(labels, on=["serial_number", "model", "cutoff_date"])
    feats = merged.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()
    # 故意写错的参数名：正确拼写是 num_leaves
    model = lgb.LGBMClassifier(num_leavs=63, learning_rate=0.05)
    model.fit(feats, merged["label"].to_numpy())
    threshold = 0.5
    feats = index.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()
''',
        "切换到 LightGBM，使用更大的树容量与更低学习率。",
    ),
    REPAIR_A: (
        '''
    import lightgbm as lgb

    merged = history.merge(labels, on=["serial_number", "model", "cutoff_date"])
    feats = merged.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()
    # 修复：参数名改回 num_leaves
    model = lgb.LGBMClassifier(num_leaves=63, learning_rate=0.05)
    model.fit(feats, merged["label"].to_numpy())
    threshold = 0.5
    feats = index.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()
''',
        "修复 LightGBM 参数拼写错误（num_leavs -> num_leaves）。",
    ),
    FAILED_B: (
        '''
    merged = history.merge(labels, on=["serial_number", "model", "cutoff_date"])
    feats = merged.filter(regex="smart_.*_raw").fillna(0.0).to_numpy()
    model = LogisticRegression(class_weight="balanced", max_iter=5000)
    # 故意的全量网格搜索：900s 预算内跑不完
    best = None
    for c in np.logspace(-3, 3, 60):
        model.set_params(C=c)
        model.fit(feats, merged["label"].to_numpy())
        best = model
    model = best
    threshold = 0.5
    feats = index.filter(regex="smart_.*_raw").fillna(0.0).to_numpy()
''',
        "改用 raw SMART 列并做 C 的网格搜索。",
    ),
    REPAIR_B: (
        '''
    merged = history.merge(labels, on=["serial_number", "model", "cutoff_date"])
    feats = merged.filter(regex="smart_.*_raw").fillna(0.0).to_numpy()
    model = LogisticRegression(class_weight="balanced", max_iter=5000)
    model.fit(feats, merged["label"].to_numpy())
    threshold = 0.5
    feats = index.filter(regex="smart_.*_raw").fillna(0.0).to_numpy()
''',
        "去掉网格搜索，直接用默认 C。",
    ),
}


def _code(node_id: str) -> str:
    body, _intent = PROGRAMS[node_id]
    return _program(node_id, body)


def _intent(node_id: str) -> str:
    return PROGRAMS[node_id][1]


# --------------------------------------------------------------------------
# tree.json
# --------------------------------------------------------------------------


def build_tree() -> dict[str, object]:
    return {
        "experiment_id": EXPERIMENT_ID,
        "nodes": [
            {"id": ROOT, "branch_id": "main", "depth": 0, "operator": "init",
             "score": 22.807355886970594, "status": "done", "hypothesis_status": "open",
             "intent": _intent(ROOT), "visit_count": 4, "adopted_cards": []},
            {"id": FAILED_A, "branch_id": "main", "depth": 1, "operator": "refine",
             "score": 0.0, "status": "invalid", "hypothesis_status": "refuted",
             "intent": _intent(FAILED_A), "visit_count": 0, "adopted_cards": []},
            {"id": REPAIR_A, "branch_id": "main", "depth": 1, "operator": "repair",
             "score": 18.5124, "status": "done", "hypothesis_status": "open",
             "intent": _intent(REPAIR_A), "visit_count": 0, "adopted_cards": []},
            {"id": FAILED_B, "branch_id": "main", "depth": 1, "operator": "refine",
             "score": 0.0, "status": "invalid", "hypothesis_status": "refuted",
             "intent": _intent(FAILED_B), "visit_count": 0, "adopted_cards": []},
            {"id": REPAIR_B, "branch_id": "main", "depth": 1, "operator": "repair",
             "score": 0.0, "status": "invalid", "hypothesis_status": "refuted",
             "intent": _intent(REPAIR_B), "visit_count": 0, "adopted_cards": []},
        ],
        "edges": [
            {"source": ROOT, "target": FAILED_A},
            {"source": ROOT, "target": FAILED_B},
            # The repairer's parent is the *failed node's parent* (tree.py:462),
            # so these two are parent edges, not repair edges.
            {"source": ROOT, "target": REPAIR_A},
            {"source": ROOT, "target": REPAIR_B},
        ],
    }


# --------------------------------------------------------------------------
# database
# --------------------------------------------------------------------------

#: ``node`` rows. ``evidence_json`` mirrors ``NodeEvidence``: the evaluation
#: dict is what ``replay_service._evaluation_from`` reads ``error_info`` from.
NODES: list[dict[str, object]] = [
    {
        "id": ROOT, "parent_id": None, "depth": 0, "operator": "init",
        "status": "done", "hypothesis_status": "open", "visit_count": 4,
        "children_json": json.dumps([FAILED_A, REPAIR_A, FAILED_B, REPAIR_B]),
        "evidence": {
            "evaluation": {"validity": 1.0, "combined_score": 22.807355886970594,
                           "cost_time": 3.6616, "error_info": "",
                           "metric": {"f1_p10": 0.22935, "auprc": 0.19546,
                                      "recall_at_far": 0.27381, "run_time_s": 3.66}},
        },
        "repair_attempted": 0, "repair_count": 0, "repair_parent_id": None,
        "error_class": "", "repair_exhausted": 0,
        "hypothesis_fail_count": 4, "card_ids_json": "[]", "insight_ids_json": "[]",
    },
    {
        "id": FAILED_A, "parent_id": ROOT, "depth": 1, "operator": "refine",
        "status": "invalid", "hypothesis_status": "refuted", "visit_count": 0,
        "children_json": "[]",
        "evidence": {
            "evaluation": {
                "validity": 0.0, "combined_score": 0.0, "cost_time": 1.4021,
                "error_info": (
                    "SandboxError: LGBMClassifier 收到未知参数 'num_leavs'"
                    "（应为 num_leaves）；候选进程退出码 1，validity=0"
                ),
                "metric": {},
            },
            "delta_score": -22.807355886970594, "noise_delta": 0.0,
        },
        # engine.py:2009 / tree.py:235 -- these belong to the FAILED node.
        "repair_attempted": 1, "repair_count": 1, "repair_parent_id": None,
        "error_class": "sandbox_error", "repair_exhausted": 0,
        "hypothesis_fail_count": 1, "card_ids_json": "[]", "insight_ids_json": "[]",
    },
    {
        "id": REPAIR_A, "parent_id": ROOT, "depth": 1, "operator": "repair",
        "status": "done", "hypothesis_status": "open", "visit_count": 0,
        "children_json": "[]",
        "evidence": {
            "evaluation": {"validity": 1.0, "combined_score": 18.5124,
                           "cost_time": 2.1183, "error_info": "",
                           "metric": {"f1_p10": 0.19012, "auprc": 0.16004,
                                      "recall_at_far": 0.23117, "run_time_s": 2.12}},
            "delta_score": 18.5124, "noise_delta": 0.0,
        },
        # tree.py:469 -- the repairer only points back at what it repairs.
        "repair_attempted": 0, "repair_count": 0, "repair_parent_id": FAILED_A,
        "error_class": "", "repair_exhausted": 0,
        "hypothesis_fail_count": 0, "card_ids_json": "[]", "insight_ids_json": "[]",
    },
    {
        "id": FAILED_B, "parent_id": ROOT, "depth": 1, "operator": "refine",
        "status": "invalid", "hypothesis_status": "refuted", "visit_count": 0,
        "children_json": "[]",
        "evidence": {
            "evaluation": {
                "validity": 0.0, "combined_score": 0.0, "cost_time": 900.0,
                "error_info": "TimeoutError: 候选在 900s 预算内未写出 pred.csv（网格搜索未收敛）",
                "metric": {},
            },
            "delta_score": -22.807355886970594, "noise_delta": 0.0,
        },
        "repair_attempted": 1, "repair_count": 3, "repair_parent_id": None,
        "error_class": "timeout",
        # engine.py:2006 -- exhausted is stamped on the chain ROOT.
        "repair_exhausted": 1,
        "hypothesis_fail_count": 1, "card_ids_json": "[]", "insight_ids_json": "[]",
    },
    {
        "id": REPAIR_B, "parent_id": ROOT, "depth": 1, "operator": "repair",
        "status": "invalid", "hypothesis_status": "refuted", "visit_count": 0,
        "children_json": "[]",
        "evidence": {
            "evaluation": {
                "validity": 0.0, "combined_score": 0.0, "cost_time": 1.1177,
                "error_info": "SmokeError: 修复后的候选仍未通过 smoke（第 3 次尝试，链已耗尽）",
                "metric": {},
            },
            "delta_score": 0.0, "noise_delta": 0.0,
        },
        "repair_attempted": 0, "repair_count": 0, "repair_parent_id": FAILED_B,
        "error_class": "smoke_failed", "repair_exhausted": 0,
        "hypothesis_fail_count": 1, "card_ids_json": "[]", "insight_ids_json": "[]",
    },
]

NODE_COLUMNS = (
    "id", "experiment_id", "parent_id", "branch_id", "depth", "operator",
    "artifact_json", "evidence_json", "status", "hypothesis_status", "visit_count",
    "expand_count", "children_json", "insight_ids_json", "card_ids_json",
    "branch_memory_json", "repair_attempted", "hypothesis_fail_count",
    "repair_count", "repair_parent_id", "error_class", "repair_exhausted",
    "created_at",
)


def _artifact_json(node_id: str) -> str:
    return json.dumps(
        {"code": _code(node_id), "intent": _intent(node_id),
         "hypothesis": f"{_intent(node_id)}（fixture 合成）"},
        ensure_ascii=False,
    )


def write_database(dst: Path, demo_db: Path) -> None:
    """Create ``fe.db`` with the demo's *schema* and this run's own rows.

    Copying the demo database and deleting rows would leave experiment-scoped
    tables (``card_stats``, ``branch_offered_cards``, ``node_adopted_cards``)
    pointing at another run's ids, and ``/knowledge/cards`` does not filter all
    of them by ``experiment_id``. Rebuilding from the schema avoids leaking a
    second run's knowledge cards into this one.
    """
    src = sqlite3.connect(f"file:{demo_db}?mode=ro", uri=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    out = sqlite3.connect(str(dst))
    try:
        out.execute("PRAGMA journal_mode=DELETE")
        for (name, sql) in src.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
        ):
            # ``sqlite_sequence`` is an internal bookkeeping table that only
            # exists once an AUTOINCREMENT column has been used; recreating it
            # is rejected, and it is not needed here.
            if name.startswith("sqlite_"):
                continue
            out.execute(sql)
        for (name, sql) in src.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ):
            out.execute(sql)

        out.execute(
            "INSERT INTO experiment (id, name, status, config_json, problem_md,"
            " prompt_md, best_node_id, best_score, iterations_done, total_tokens,"
            " created_at, updated_at)"
            " SELECT ?, name, status, config_json, problem_md, prompt_md, ?, ?, ?, ?,"
            "        ?, ? FROM experiment LIMIT 1",
            (EXPERIMENT_ID, ROOT, 22.807355886970594, 4, 3950, CREATED_AT, CREATED_AT),
        )

        placeholders = ", ".join("?" * len(NODE_COLUMNS))
        for row in NODES:
            out.execute(
                f"INSERT INTO node ({', '.join(NODE_COLUMNS)}) VALUES ({placeholders})",
                (
                    row["id"], EXPERIMENT_ID, row["parent_id"], "main", row["depth"],
                    row["operator"], _artifact_json(str(row["id"])),
                    json.dumps(row["evidence"], ensure_ascii=False), row["status"],
                    row["hypothesis_status"], row["visit_count"], 0,
                    row["children_json"], row["insight_ids_json"], row["card_ids_json"],
                    json.dumps({"summary": "", "top_insight_ids": [],
                                "refuted_hypotheses": []}),
                    row["repair_attempted"], row["hypothesis_fail_count"],
                    row["repair_count"], row["repair_parent_id"], row["error_class"],
                    row["repair_exhausted"], CREATED_AT,
                ),
            )

        # Same events as events.jsonl, same ids: replay_service cross-checks the
        # two and emits a ContractWarning when they disagree.
        for index, (kind, payload) in enumerate(EVENTS, start=1):
            out.execute(
                "INSERT INTO event (id, experiment_id, type, payload_json, ts)"
                " VALUES (?, ?, ?, ?, ?)",
                (index, EXPERIMENT_ID, kind, json.dumps(payload, ensure_ascii=False),
                 _ts(index)),
            )
        out.commit()
        out.execute("VACUUM")
        out.commit()
    finally:
        out.close()
        src.close()


# --------------------------------------------------------------------------
# run_summary.json
# --------------------------------------------------------------------------

#: Patches applied on top of the demo summary so the numbers agree with the
#: five-node tree above instead of describing a run that never happened.
SUMMARY_PATCH: dict[str, object] = {
    "experiment_id": EXPERIMENT_ID,
    "status": "finished",
    "stop_reason": "max_iterations",
    "iterations_done": 4,
    "iteration_events": 4,
    "best_node_id": ROOT,
    "best_score": 22.807355886970594,
    "initial_score": 22.807355886970594,
    "improvement": 0.0,
    "valid_rate": 0.4,
    "generative_valid_rate": 0.0,
    "operator_counts": {"refine": 2, "repair": 2},
    "operator_valid_rate": {"refine": 0.0, "repair": 0.5},
    "operator_mean_delta": {"refine": -22.807355886970594, "repair": 9.2562},
    "operator_tokens": {"refine": 1500, "repair": 900},
    "operator_posteriors": {
        "refine": {"alpha": 1.0, "beta": 4.0, "mean": 0.2},
        "repair": {"alpha": 1.0, "beta": 2.0, "mean": 0.3333},
    },
    "repair_attempts": 2,
    "repair_iterations": 2,
    "repair_successes": 1,
    "repair_tokens": 900,
    "total_tokens": 3950,
    "smoke_tests": 5,
    "smoke_failures": 2,
    "smoke_fixes": 1,
    "smoke_time_s_total": 12.305,
    "avg_smoke_time_s": 2.461,
    "total_eval_time_s": 908.3,
    "wall_time_s": 41.7,
    "tokens_per_score_gain": 3950000.0,
    # No knowledge cards were injected into this synthetic run.
    "cards_adopted": 0,
    "cards_adopted_valid": 0,
    "cards_offered": 0,
    "card_adoption_rate": 0.0,
    "card_stats": [],
    "knowledge_tokens": 0,
    "knowledge_token_share": 0.0,
    "literature_card_mean_delta": None,
    "discovered_card_mean_delta": None,
}


def write_summary(dst: Path, demo_summary: Path) -> None:
    data = json.loads(demo_summary.read_text(encoding="utf-8"))
    data.update(SUMMARY_PATCH)
    dst.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------


def generate(root: Path) -> Path:
    demo = root / DEMO_RUN_ID
    out = root / FAIL_RUN_ID
    if out.exists():
        shutil.rmtree(out)

    (out / "programs").mkdir(parents=True)
    (out / "logs").mkdir(parents=True)
    (out / "discovery").mkdir(parents=True)
    # Git cannot track an empty directory; the demo run keeps a placeholder and
    # so does this one.
    (out / "logs" / ".gitkeep").write_text("", encoding="utf-8")

    (out / "tree.json").write_text(
        json.dumps(build_tree(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    lines = [
        json.dumps(
            {"id": index, "experiment_id": EXPERIMENT_ID, "type": kind,
             "payload": payload, "ts": _ts(index)},
            ensure_ascii=False,
        )
        for index, (kind, payload) in enumerate(EVENTS, start=1)
    ]
    (out / "events.jsonl").write_text("\n".join(lines) + "\n",
                                      encoding="utf-8", newline="\n")
    write_summary(out / "run_summary.json", demo / "run_summary.json")
    write_database(out / "fe.db", demo / "fe.db")

    for node_id in PROGRAMS:
        (out / "programs" / f"{node_id}.py").write_text(
            _code(node_id), encoding="utf-8", newline="\n"
        )

    # The discovery artifacts are empty lists in every run today; copy the
    # demo's so the discovery page renders "empty" rather than "missing".
    for name in ("phenomena.json", "preregistration.json", "controls.json",
                 "discovered_cards.snapshot.jsonl"):
        source = demo / "discovery" / name
        if source.is_file():
            shutil.copyfile(source, out / "discovery" / name)
    return out


def check(out: Path) -> int:
    """Assert the fixture actually carries the failure story. Returns failures."""
    failures: list[str] = []

    tree = json.loads((out / "tree.json").read_text(encoding="utf-8"))
    by_id = {n["id"]: n for n in tree["nodes"]}
    for node_id, expected in ((FAILED_A, "invalid"), (FAILED_B, "invalid"),
                              (REPAIR_B, "invalid")):
        if by_id.get(node_id, {}).get("status") != expected:
            failures.append(f"tree.json: {node_id} status != {expected}")

    db = sqlite3.connect(f"file:{out / 'fe.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = {r["id"]: dict(r) for r in db.execute("SELECT * FROM node")}
    if rows[FAILED_A]["error_class"] != "sandbox_error":
        failures.append("fe.db: FAILED_A error_class wrong")
    if rows[FAILED_B]["repair_exhausted"] != 1:
        failures.append("fe.db: FAILED_B repair_exhausted != 1")
    if rows[REPAIR_A]["repair_parent_id"] != FAILED_A:
        failures.append("fe.db: REPAIR_A repair_parent_id wrong")
    if rows[REPAIR_B]["repair_parent_id"] != FAILED_B:
        failures.append("fe.db: REPAIR_B repair_parent_id wrong")
    info = json.loads(rows[FAILED_A]["evidence_json"])["evaluation"]["error_info"]
    if "num_leavs" not in info:
        failures.append("fe.db: FAILED_A evaluation.error_info missing the reason")
    event_count = db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    db.close()

    jsonl_count = sum(
        1 for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines() if line
    )
    if event_count != jsonl_count:
        failures.append(f"events: db {event_count} != jsonl {jsonl_count}")

    summary = json.loads((out / "run_summary.json").read_text(encoding="utf-8"))
    if summary["experiment_id"] != EXPERIMENT_ID:
        failures.append("run_summary.json: experiment_id wrong")
    if summary["repair_successes"] != 1:
        failures.append("run_summary.json: repair_successes != 1")

    for line in failures:
        print(f"FAIL {line}", file=sys.stderr)
    return len(failures)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify the existing fixture instead of writing it")
    args = parser.parse_args()

    target = FIXTURE_ROOT / FAIL_RUN_ID
    if args.check:
        if not target.is_dir():
            print(f"FAIL missing fixture: {target}", file=sys.stderr)
            return 1
        return 1 if check(target) else 0

    out = generate(FIXTURE_ROOT)
    broken = check(out)
    print(f"wrote {out} ({broken} problem(s))")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())

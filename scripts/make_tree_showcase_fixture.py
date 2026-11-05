"""Generate the *tree showcase* fixture (TODO §5.1 / §12.5).

Why this exists
---------------
The committed demo run (`hdd_mvp_demo_7510f100`) has **6 nodes, all at depth
0/1, all `init`/`refine`, all `status=done`, and 5 edges that are all plain
parent edges**. That shape cannot exercise a single visual feature phase 7
built:

* 2 depth bands instead of 5+ (banding collapses);
* no crossover edge, no repair edge (the edge legend has nothing to label);
* every node lands on the same significance tier (no best / progress / noise /
  unknown contrast, no dashed border);
* improvement = 0, so the best path is one hop.

Phase 7 noticed this and worked around it with a throwaway tree in a scratch
directory, which is why the committed tree kept looking "unimproved" the moment
that scratch was gone. This script makes the showcase tree a *fixture* instead.

Shape (21 nodes, depth 0..5, mirroring the concept drawing
`docs/images/frontend-concepts/02-evolution-workbench.png`):

* one best path  ``n0 -> n1 -> n4 -> n8 -> n13 -> n18`` with monotonically
  rising scores, so the green highlight is a real path;
* two ``crossover`` nodes whose second parent is recorded in ``node_parents``
  with ``role='secondary'`` (the only place the engine records it);
* one repair chain ``n15 (timeout, invalid) -> n16 (repair, done)`` -- the
  repairer's ``parent_id`` is the failed node's *parent* (``tree.py:459``),
  so the repair edge and the parent edge stay distinct;
* all four significance tiers populated, computed the same way the backend
  does it: ``|delta| <= |noise|`` means noise, either missing means unknown,
  ``is_best`` comes from ``run_summary.best_node_id``.

Usage::

    python scripts/make_tree_showcase_fixture.py            # write
    python scripts/make_tree_showcase_fixture.py --check    # verify only
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

EXPERIMENT_ID = "7c1a2e09"
RUN_ID = f"hdd_mvp_treedemo_{EXPERIMENT_ID}"

CREATED_AT = "2026-10-03T11:00:00.000000+00:00"

# --------------------------------------------------------------------------
# the tree itself: (id, parent, depth, operator, score, delta, noise, status,
#                   hypothesis, error_class, repair_parent_id, second_parent)
# --------------------------------------------------------------------------

N = [
    # id        parent  d  operator            score   delta    noise  status     hypo         error            repair   2nd
    ("n0a1b2c3", None,   0, "init",              12.46,  None,    None,  "done",    "open",      "",              None,    None),
    ("n1d4e5f6", "n0a1b2c3", 1, "refine",       15.92,  3.46,    0.50,  "done",    "refuted",   "",              None,    None),
    ("n2a7b8c9", "n0a1b2c3", 1, "refine",       14.31,  1.85,    2.00,  "done",    "refuted",   "",              None,    None),
    ("n3d0e1f2", "n0a1b2c3", 1, "refine",        0.00,  None,    None,  "invalid", "refuted",   "timeout",       None,    None),
    ("n4a3b4c5", "n1d4e5f6", 2, "refine",       20.11,  4.19,    0.50,  "done",    "refuted",   "",              None,    None),
    ("n5d6e7f8", "n1d4e5f6", 2, "refine",       18.07,  2.15,    3.00,  "done",    "refuted",   "",              None,    None),
    ("n6a9b0c1", "n2a7b8c9", 2, "refine",       22.18,  7.87,    0.50,  "done",    "refuted",   "",              None,    None),
    ("n7d2e3f4", "n2a7b8c9", 2, "refine",       17.06,  2.75,    0.50,  "done",    "refuted",   "",              None,    None),
    ("n8a5b6c7", "n4a3b4c5", 3, "refine",       24.12,  4.01,    0.50,  "done",    "refuted",   "",              None,    None),
    ("n9d8e9f0", "n4a3b4c5", 3, "recall_focus", 21.03,  0.92,    0.50,  "done",    "refuted",   "",              None,    None),
    ("n10a1b2d3","n5d6e7f8", 3, "refine",       26.41,  8.34,    0.50,  "done",    "refuted",   "",              None,    None),
    ("n11d3e4f5","n5d6e7f8", 3, "refine",       23.18,  5.11,    0.50,  "done",    "refuted",   "",              None,    "n6a9b0c1"),
    ("n12a5b6d7","n7d2e3f4", 3, "refine",       19.34,  2.28,    5.00,  "done",    "refuted",   "",              None,    None),
    ("n13d7e8f9","n8a5b6c7", 4, "refine",       27.56,  3.44,    0.50,  "done",    "refuted",   "",              None,    None),
    ("n14a7b8d9","n8a5b6c7", 4, "refine",       25.11,  0.99,    1.20,  "done",    "refuted",   "",              None,    None),
    ("n15d9e0fa","n10a1b2d3",4, "refine",        0.00,  None,    None,  "invalid", "refuted",   "timeout",       None,    None),
    # 引擎 tree.py:459 create_repair_node：parent_id = 失败节点的 parent_id、
    # depth = 失败节点的 depth，repair_parent_id 才指向失败节点本身。
    ("n16a9b0db","n10a1b2d3", 4, "repair",       31.48,  9.30,    0.50,  "done",    "open",      "",              "n15d9e0fa", None),
    ("n17d1e2fc","n12a5b6d7",4, "threshold_calibrate", 22.17, 2.83, 0.50, "done",  "refuted",   "",              None,    None),
    ("n18a3b4dd","n13d7e8f9",5, "refine",       33.70,  6.14,    0.50,  "done",    "supported", "",              None,    None),
    ("n19d5e6fe","n13d7e8f9",5, "refine",       31.12,  3.56,    0.50,  "done",    "refuted",   "",              None,    None),
    ("n20a7b8df","n16a9b0db",5, "inject",       29.08, -2.40,    0.50,  "done",    "refuted",   "",              None,    None),
]

BEST_NODE = "n18a3b4dd"
BEST_SCORE = 33.70
ROOT_SCORE = 12.46

INTENTS = {
    "init": "初始解：cutoff 当日 SMART 的加权逻辑回归",
    "refine": "换特征窗口并重训",
    "recall_focus": "按失败召回定向补特征",
    "threshold_calibrate": "用分位数重选告警阈值",
    "inject": "注入跨分支的知识卡后重训",
    "repair": "修复超时的网格搜索",
}

NODE_BY_ID = {row[0]: row for row in N}


def _parent_chain(node_id: str) -> list[str]:
    """IDs from the root down to ``node_id`` along ``parent_id``."""
    chain: list[str] = []
    cursor: str | None = node_id
    while cursor:
        chain.append(cursor)
        cursor = NODE_BY_ID[cursor][1]
    return list(reversed(chain))


# --------------------------------------------------------------------------
# programs
# --------------------------------------------------------------------------

_TEMPLATE = '''"""HDD failure prediction candidate ({node_id}).

Fixture program for the tree showcase run. Generation {depth}, operator {operator}.
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
    # {note}
    merged = history.merge(labels, on=["serial_number", "model", "cutoff_date"])
    feats = merged.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()
    model = LogisticRegression(class_weight="balanced", max_iter=200, C={c})
    model.fit(feats, merged["label"].to_numpy())
    query = index.filter(regex="smart_.*_normalized").fillna(0.0).to_numpy()
    out = index[["serial_number"]].copy()
    out["score"] = model.predict_proba(query)[:, 1]
    out["alarm"] = (out["score"] >= {threshold}).astype(int)
    out.to_csv(args.out, index=False)


if __name__ == "__main__":
    main()
'''


def _code(node_id: str) -> str:
    _id, _parent, depth, operator, score, _d, _n, status, _h, _e, _r, _s = NODE_BY_ID[node_id]
    note = {
        "init": "初始阈值取 0.5，特征是 log1p 的十个 cutoff 日读数",
        "refine": "把 14 天窗口的趋势差分并进来，再重选阈值",
        "recall_focus": "只对漏报样本加权，提高召回",
        "threshold_calibrate": "阈值改由训练集 F1 的 90 分位决定",
        "inject": "吸收知识卡后把 C 收紧，防止过拟合",
        "repair": "去掉网格搜索，直接用默认正则强度",
    }[operator]
    return _TEMPLATE.format(
        node_id=node_id, depth=depth, operator=operator, note=note,
        c=round(0.1 + (score or 1.0) / 40.0, 3), threshold=round(0.3 + depth * 0.05, 2),
    )


# --------------------------------------------------------------------------
# tree.json / events
# --------------------------------------------------------------------------


def build_tree() -> dict[str, object]:
    nodes = [
        {
            "id": row[0], "branch_id": "main", "depth": row[2], "operator": row[3],
            "score": row[4], "status": row[7], "hypothesis_status": row[8],
            "intent": INTENTS[row[3]], "visit_count": 3 if row[2] <= 1 else 0,
            "adopted_cards": ["FE01"] if row[3] == "inject" else [],
        }
        for row in N
    ]
    edges = [
        {"source": row[1], "target": row[0]}
        for row in N
        if row[1] is not None
    ]
    return {"experiment_id": EXPERIMENT_ID, "nodes": nodes, "edges": edges}


def build_events() -> list[tuple[str, dict[str, object]]]:
    """One ``node_created`` per node, one ``iteration_complete`` per depth, a finish."""
    events: list[tuple[str, dict[str, object]]] = [
        ("smoke_data_built", {"path": "<REDACTED_PATH>", "sample_fraction": 0.02}),
    ]
    for row in N:
        events.append((
            "node_created",
            {"node_id": row[0], "operator": row[3],
             **({"parent_id": row[1]} if row[1] else {}),
             **({"repair_parent_id": row[10]} if row[10] else {})},
        ))
        if row[7] == "invalid":
            events.append((
                "smoke_failed",
                {"node_id": row[0], "error_class": row[9],
                 "reason": "候选在 900s 预算内未写出 pred.csv"},
            ))
        events.append((
            "iteration_complete",
            {"node_id": row[0], "status": row[7], "score": row[4]},
        ))
    events.append((
        "run_finished",
        {"status": "finished", "stop_reason": "max_iterations",
         "best_node_id": BEST_NODE, "best_score": BEST_SCORE},
    ))
    return events


# --------------------------------------------------------------------------
# database
# --------------------------------------------------------------------------

NODE_COLUMNS = (
    "id", "experiment_id", "parent_id", "branch_id", "depth", "operator",
    "artifact_json", "evidence_json", "status", "hypothesis_status", "visit_count",
    "expand_count", "children_json", "insight_ids_json", "card_ids_json",
    "branch_memory_json", "repair_attempted", "hypothesis_fail_count",
    "repair_count", "repair_parent_id", "error_class", "repair_exhausted",
    "created_at",
)


def _evidence(row: tuple) -> dict[str, object]:
    _id, _p, _d, _op, score, delta, noise, status, _h, error, _r, _s = row
    evaluation: dict[str, object] = {
        "validity": 1.0 if status == "done" else 0.0,
        "combined_score": score,
        "cost_time": 2.0 + (len(_id) % 7) / 10.0,
        "error_info": "",
        "metric": {"f1_p10": round((score or 0) / 100.0, 5), "run_time_s": 2.4},
    }
    if error:
        evaluation["error_info"] = f"TimeoutError: 候选在 900s 预算内未写出 pred.csv（{error}）"
    evidence: dict[str, object] = {"evaluation": evaluation}
    if delta is not None:
        evidence["delta_score"] = delta
    if noise is not None:
        evidence["noise_delta"] = noise
    return evidence


def write_database(dst: Path, demo_db: Path) -> None:
    """Schema from the demo, rows from :data:`N` (see make_failure_fixture)."""
    src = sqlite3.connect(f"file:{demo_db}?mode=ro", uri=True)
    if dst.exists():
        dst.unlink()
    out = sqlite3.connect(str(dst))
    try:
        out.execute("PRAGMA journal_mode=DELETE")
        for name, sql in src.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
        ):
            if name.startswith("sqlite_"):
                continue
            out.execute(sql)
        for name, sql in src.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
        ):
            out.execute(sql)

        out.execute(
            "INSERT INTO experiment (id, name, status, config_json, problem_md,"
            " prompt_md, best_node_id, best_score, iterations_done, total_tokens,"
            " created_at, updated_at)"
            " SELECT ?, name, status, config_json, problem_md, prompt_md, ?, ?, ?, ?,"
            "        ?, ? FROM experiment LIMIT 1",
            (EXPERIMENT_ID, BEST_NODE, BEST_SCORE, 5, 5200, CREATED_AT, CREATED_AT),
        )

        children: dict[str, list[str]] = {}
        for row in N:
            if row[1]:
                children.setdefault(row[1], []).append(row[0])

        for row in N:
            node_id, parent, _d, _op, _s, _de, _n, _st, _h, error, repair, second = row
            # 引擎口径：repair_count / repair_attempted 在失败节点上；这里让
            # n15 被 n16 修好一次，所以 n15 计数 1。
            failed_count = 1 if any(r[10] == node_id for r in N) else 0
            out.execute(
                f"INSERT INTO node ({', '.join(NODE_COLUMNS)}) VALUES ({', '.join('?' * len(NODE_COLUMNS))})",
                (
                    node_id, EXPERIMENT_ID, parent, "main", row[2], row[3],
                    json.dumps({"code": _code(node_id), "intent": INTENTS[row[3]],
                                "hypothesis": f"{INTENTS[row[3]]}（fixture 合成）"},
                               ensure_ascii=False),
                    json.dumps(_evidence(row), ensure_ascii=False), row[7], row[8],
                    3 if row[2] <= 1 else 0, 0,
                    json.dumps(children.get(node_id, [])), "[]",
                    json.dumps(["FE01"] if row[3] == "inject" else []),
                    json.dumps({"summary": "", "top_insight_ids": [],
                                "refuted_hypotheses": []}),
                    1 if failed_count else 0, 0, failed_count, repair, error,
                    0, CREATED_AT,
                ),
            )
            if second:
                out.execute(
                    "INSERT INTO node_parents (experiment_id, node_id, parent_id, role)"
                    " VALUES (?, ?, ?, 'secondary')",
                    (EXPERIMENT_ID, node_id, second),
                )

        for index, (kind, payload) in enumerate(build_events(), start=1):
            out.execute(
                "INSERT INTO event (id, experiment_id, type, payload_json, ts)"
                " VALUES (?, ?, ?, ?, ?)",
                (index, EXPERIMENT_ID, kind, json.dumps(payload, ensure_ascii=False),
                 (f"2026-10-03T11:00:{index % 60:02d}.{index * 1000 % 1000000:06d}"
                  "+00:00")),
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

SUMMARY_PATCH: dict[str, object] = {
    "experiment_id": EXPERIMENT_ID,
    "status": "finished",
    "stop_reason": "max_iterations",
    "iterations_done": 5,
    "iteration_events": 5,
    "best_node_id": BEST_NODE,
    "best_score": BEST_SCORE,
    "initial_score": ROOT_SCORE,
    "improvement": round(BEST_SCORE - ROOT_SCORE, 6),
    "valid_rate": round(sum(1 for r in N if r[7] == "done") / len(N), 4),
    "generative_valid_rate": round(
        sum(1 for r in N if r[7] == "done" and r[3] != "repair")
        / sum(1 for r in N if r[3] != "repair" and r[3] != "init"),
        4,
    ),
    "operator_counts": {
        name: sum(1 for r in N if r[3] == name)
        for name in sorted({r[3] for r in N})
    },
    "repair_attempts": 1,
    "repair_iterations": 1,
    "repair_successes": 1,
    "repair_tokens": 600,
    "total_tokens": 5200,
    "smoke_tests": len(N),
    "smoke_failures": 2,
    "smoke_fixes": 1,
    "crossover_count": sum(1 for r in N if r[11]),
    "crossover_best_gain": 5.11,
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
    out = root / RUN_ID
    if out.exists():
        shutil.rmtree(out)

    (out / "programs").mkdir(parents=True)
    (out / "logs").mkdir(parents=True)
    (out / "discovery").mkdir(parents=True)
    (out / "logs" / ".gitkeep").write_text("", encoding="utf-8")

    (out / "tree.json").write_text(
        json.dumps(build_tree(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    lines = [
        json.dumps(
            {"id": index, "experiment_id": EXPERIMENT_ID, "type": kind,
             "payload": payload, "ts": ""},
            ensure_ascii=False,
        )
        for index, (kind, payload) in enumerate(build_events(), start=1)
    ]
    (out / "events.jsonl").write_text("\n".join(lines) + "\n",
                                      encoding="utf-8", newline="\n")
    write_summary(out / "run_summary.json", demo / "run_summary.json")
    write_database(out / "fe.db", demo / "fe.db")

    for row in N:
        (out / "programs" / f"{row[0]}.py").write_text(
            _code(row[0]), encoding="utf-8", newline="\n"
        )
    for name in ("phenomena.json", "preregistration.json", "controls.json",
                 "discovered_cards.snapshot.jsonl"):
        source = demo / "discovery" / name
        if source.is_file():
            shutil.copyfile(source, out / "discovery" / name)
    return out


def check(out: Path) -> int:
    """The whole point is *visual coverage*: assert every tier is reachable."""
    failures: list[str] = []

    tree = json.loads((out / "tree.json").read_text(encoding="utf-8"))
    by_id = {n["id"]: n for n in tree["nodes"]}
    depths = sorted({n["depth"] for n in tree["nodes"]})
    if depths != [0, 1, 2, 3, 4, 5]:
        failures.append(f"depth 层级不足 6 层：{depths}")

    # parent_id 与 depth 必须自洽（repair 节点同 depth，见 tree.py:459）。
    for node in tree["nodes"]:
        parent_id = NODE_BY_ID[node["id"]][1]
        if parent_id is None:
            continue
        if node["depth"] != by_id[parent_id]["depth"] + 1:
            failures.append(
                f"{node['id']} depth={node['depth']} 但父 {parent_id} "
                f"depth={by_id[parent_id]['depth']}"
            )

    # 后端同源的噪声带判定：|delta| <= |noise|。
    tiers = {"best": 0, "progress": 0, "noise": 0, "unknown": 0}
    for row in N:
        delta, noise = row[5], row[6]
        if row[0] == BEST_NODE:
            tiers["best"] += 1
        elif delta is None or noise is None:
            tiers["unknown"] += 1
        elif abs(delta) <= abs(noise):
            tiers["noise"] += 1
        else:
            tiers["progress"] += 1
    for tier, count in tiers.items():
        if count == 0:
            failures.append(f"显著性档 {tier} 没有节点，视觉上验不到")

    db = sqlite3.connect(f"file:{out / 'fe.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    seconds = {
        r["node_id"]: r["parent_id"]
        for r in db.execute("SELECT node_id, parent_id FROM node_parents WHERE role='secondary'")
    }
    if seconds.get("n11d3e4f5") != "n6a9b0c1":
        failures.append(f"crossover 第二父缺失：{seconds}")
    repairer = dict(db.execute("SELECT * FROM node WHERE repair_parent_id IS NOT NULL").fetchone() or {})
    if repairer.get("parent_id") != NODE_BY_ID["n15d9e0fa"][1]:
        failures.append("修复节点的 parent 不是失败节点的父节点（引擎 tree.py:459）")
    event_count = db.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    db.close()

    jsonl_count = sum(
        1 for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines() if line
    )
    if event_count != jsonl_count:
        failures.append(f"events: db {event_count} != jsonl {jsonl_count}")

    summary = json.loads((out / "run_summary.json").read_text(encoding="utf-8"))
    if summary["best_node_id"] != BEST_NODE:
        failures.append("run_summary.best_node_id 错")
    best_path = _parent_chain(BEST_NODE)
    if len(best_path) != 6:
        failures.append(f"最优路径只有 {len(best_path)} 跳，看不出是一条链：{best_path}")

    for line in failures:
        print(f"FAIL {line}", file=sys.stderr)
    return len(failures)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    target = FIXTURE_ROOT / RUN_ID
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

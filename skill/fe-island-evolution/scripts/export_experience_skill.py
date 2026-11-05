#!/usr/bin/env python3
"""Draft a reusable experience Skill from one finished island run.

Reads only committed facts -- ``fe.db`` rows and ``run_summary.json`` -- and
writes a draft plus a machine-readable evidence index into the run's own
``skills/`` directory. It never writes into the project ``skill/`` tree and
never copies candidate source code or raw data into the draft, so a draft can
be shared without leaking the task's files.

Usage:
    python export_experience_skill.py <fe.db> <run_summary.json> [--out-dir DIR] [--force]

Exit codes: 0 wrote a draft, 2 usage or input error.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

MAX_TEXT_CHARS = 400

PROJECT_SKILLS_ROOT = Path(__file__).resolve().parents[2]

KIND_LABEL = {
    "best": "有效操作",
    "failure": "避错提示",
    "knowledge": "知识卡用法",
}


def _fail(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(2)


def _truncate(text: str) -> str:
    clean = " ".join((text or "").split())
    return clean[:MAX_TEXT_CHARS] + ("…" if len(clean) > MAX_TEXT_CHARS else "")


def _scalar_metrics(raw: Any) -> dict[str, Any]:
    """Keep only numbers a reader can act on, never a whole metric blob."""
    if not isinstance(raw, dict):
        return {}
    keep = {}
    for key in ("combined_score", "delta_vs_parent", "validity", "cost_time"):
        value = raw.get(key)
        if isinstance(value, (int, float)):
            keep[key] = round(float(value), 4)
    if "previous_published_best" in raw and "gain_vs_published_best" in raw:
        keep["gain_vs_published_best"] = round(float(raw["gain_vs_published_best"]), 4)
    return keep


def _read_rows(con: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    try:
        return [dict(row) for row in con.execute(sql, params).fetchall()]
    except sqlite3.OperationalError as exc:
        _fail(f"run database does not carry the island schema: {exc}")
        return []


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _node_facts(con: sqlite3.Connection, node_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Per-node score movement, read from the evaluator's own evidence rows."""
    facts: dict[str, dict[str, Any]] = {}
    for node_id in node_ids:
        row = con.execute(
            "SELECT island_id, operator, parent_id, status, evidence_json "
            "FROM node WHERE id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            continue
        evidence = json.loads(row["evidence_json"] or "{}")
        evaluation = evidence.get("evaluation") or {}
        facts[node_id] = {
            "island_id": row["island_id"],
            "operator": row["operator"],
            "status": row["status"],
            "score": evaluation.get("combined_score"),
            "delta_score": evidence.get("delta_score"),
            "noise_delta": evidence.get("noise_delta"),
        }
    return facts


def collect(db_path: Path) -> dict[str, Any]:
    con = _connect(db_path)
    experiment_id = next(
        iter(
            [
                row["experiment_id"]
                for row in _read_rows(
                    con, "SELECT DISTINCT experiment_id FROM island_state LIMIT 1"
                )
            ]
        ),
        None,
    )
    if experiment_id is None:
        _fail(f"{db_path} holds no island run; this script only exports island runs")

    identity_rows = _read_rows(con, "SELECT identity_json FROM run_identity WHERE experiment_id = ?",
                               (experiment_id,))
    identity = json.loads(identity_rows[0]["identity_json"]) if identity_rows else {}
    profiles = {
        row["island_id"]: row["profile"]
        for row in _read_rows(
            con, "SELECT island_id, profile FROM island_state WHERE experiment_id = ?",
            (experiment_id,),
        )
    }
    summaries = _read_rows(
        con,
        "SELECT summary_id, kind, source_island_id, source_node_id, summary_text, "
        "conditions, metrics_json, confidence_status, created_at "
        "FROM exchange_summary WHERE experiment_id = ? ORDER BY created_at, summary_id",
        (experiment_id,),
    )
    summary_ids = [row["summary_id"] for row in summaries]
    placeholders = ",".join("?" * len(summary_ids)) or ""
    deliveries = _read_rows(
        con,
        f"SELECT delivery_id, summary_id, target_island_id, status, reason "
        f"FROM exchange_delivery WHERE experiment_id = ? AND summary_id IN ({placeholders})"
        if summary_ids
        else "SELECT delivery_id, summary_id, target_island_id, status, reason "
             "FROM exchange_delivery WHERE experiment_id = ?",
        (experiment_id, *summary_ids) if summary_ids else (experiment_id,),
    )
    delivery_ids = [row["delivery_id"] for row in deliveries]
    d_placeholders = ",".join("?" * len(delivery_ids)) or ""
    applications = _read_rows(
        con,
        f"SELECT application_id, delivery_id, candidate_node_id, evaluation_id, score "
        f"FROM summary_application WHERE experiment_id = ? AND delivery_id IN ({d_placeholders})"
        if delivery_ids
        else "SELECT application_id, delivery_id, candidate_node_id, evaluation_id, score "
             "FROM summary_application WHERE experiment_id = ?",
        (experiment_id, *delivery_ids) if delivery_ids else (experiment_id,),
    )
    by_delivery: dict[str, list[dict]] = {}
    for row in applications:
        by_delivery.setdefault(row["delivery_id"], []).append(row)
    node_facts = _node_facts(
        con, sorted({row["candidate_node_id"] for row in applications})
    )
    con.close()

    rules: list[dict[str, Any]] = []
    for summary in summaries:
        summary_deliveries = [d for d in deliveries if d["summary_id"] == summary["summary_id"]]
        accepted = [d for d in summary_deliveries if d["status"] == "accepted"]
        adopted: list[dict[str, Any]] = []
        for delivery in accepted:
            for application in by_delivery.get(delivery["delivery_id"], []):
                node = node_facts.get(application["candidate_node_id"]) or {}
                delta = node.get("delta_score")
                noise = node.get("noise_delta")
                adopted.append({
                    "delivery_id": delivery["delivery_id"],
                    "target_island_id": delivery["target_island_id"],
                    "application_id": application["application_id"],
                    "candidate_node_id": application["candidate_node_id"],
                    "evaluation_id": application["evaluation_id"],
                    "score": application["score"],
                    "delta_score": round(delta, 4) if isinstance(delta, (int, float)) else None,
                    "noise_delta": round(noise, 4) if isinstance(noise, (int, float)) else None,
                    # Stated as a comparison against this candidate's own noise
                    # band, because that is the only threshold the run measured.
                    "beat_noise": (
                        bool(isinstance(delta, (int, float)) and isinstance(noise, (int, float))
                             and delta > noise)
                    ),
                })
        metrics = _scalar_metrics(json.loads(summary["metrics_json"] or "{}"))
        rules.append({
            "kind": summary["kind"],
            "summary_id": summary["summary_id"],
            "source_island_id": summary["source_island_id"],
            "source_profile": profiles.get(summary["source_island_id"], ""),
            "source_node_id": summary["source_node_id"],
            "action": _truncate(summary["summary_text"]),
            "conditions": _truncate(summary["conditions"]) or "运行未记录适用条件",
            "metrics": metrics,
            "confidence_status": summary["confidence_status"],
            "deliveries": len(summary_deliveries),
            "accepted": len(accepted),
            "rejected": sum(1 for d in summary_deliveries if d["status"] == "rejected"),
            "rejection_reasons": sorted(
                {d["reason"] for d in summary_deliveries if d["status"] == "rejected" and d["reason"]}
            ),
            "adopted_by": adopted,
        })

    return {
        "experiment_id": experiment_id,
        "identity": identity,
        "profiles": profiles,
        "rules": rules,
    }


def render_markdown(data: dict[str, Any], summary: dict[str, Any], task_dir: str) -> str:
    experiment_id = data["experiment_id"]
    identity = data["identity"]
    lines = [
        f"# 运行 {experiment_id} 的经验 Skill 草稿",
        "",
        "状态：草稿。本文件由 `export_experience_skill.py` 从已落库的事实生成，"
        "未经第二次运行验证，不得直接合入 `skill/fe-island-evolution`。",
        "",
        "## 本次运行的适用范围与局限",
        "",
        f"- 任务契约指纹：task `{identity.get('task_fp', '')}`、"
        f"evaluator `{identity.get('evaluator_fp', '')}`、"
        f"init `{identity.get('init_fp', '')}`、数据指纹 `{identity.get('data_fp') or '未记录'}`。"
        "换任务或换评估器即换指纹，本文件的每条结论都只在这组指纹下成立。",
        f"- 岛环：{', '.join(f'{iid}:{data['profiles'].get(iid, '')}' for iid in identity.get('island_ids', []))}。",
        f"- 种子：{identity.get('seed', '')}；迭代 {summary.get('iterations_done')}，"
        f"停止原因 {summary.get('stop_reason', '')}；"
        f"总 token {summary.get('total_tokens', 0)}。",
        "- 结论口径：分数只来自本地评估器；LLM 的自述不构成分数证据。"
        "被采纳后的分数变化只与该候选自身的噪声带比较，不声称因果。",
        "",
    ]

    if not data["rules"]:
        lines += [
            "## 可泛化规则",
            "",
            "本次运行没有产出任何岛间摘要，因此**未得到可泛化规则**。"
            "以下事实仍然成立，供下一次运行对照：",
            "",
            f"- 各岛尝试数："
            + "，".join(
                f"{iid} {island.get('attempts')} 次尝试 / "
                f"{island.get('valid_evaluations')} 次有效评估 / "
                f"{island.get('invalid_evaluations')} 次无效评估"
                for iid, island in (summary.get("islands") or {}).items()
            )
            + "。",
            f"- 交换计数：{json.dumps(summary.get('exchange') or {}, ensure_ascii=False)}。",
            "",
            "单凭一次运行无法区分“策略无效”与“预算太小”，因此不据此给出避错规则。",
            "",
        ]
        return "\n".join(lines) + "\n"

    for kind in ("best", "failure", "knowledge"):
        group = [rule for rule in data["rules"] if rule["kind"] == kind]
        if not group:
            invalid = sum(
                int(island.get("invalid_evaluations") or 0)
                for island in (summary.get("islands") or {}).values()
            )
            lines += [
                f"## {KIND_LABEL[kind]}（0 条）",
                "",
                f"本次运行没有产出该类摘要（全岛无效评估 {invalid} 次），"
                "因此不据此给出条目；缺失不等于该类写法普遍安全或普遍无效。",
                "",
            ]
            continue
        lines += [f"## {KIND_LABEL[kind]}（{len(group)} 条）", ""]
        for index, rule in enumerate(group, start=1):
            gain = rule["metrics"].get("delta_vs_parent")
            lines += [
                f"### {kind}-{index}｜来源岛 {rule['source_island_id']}"
                f"（{rule['source_profile']}）",
                "",
                f"- 操作：{rule['action']}",
                f"- 适用条件：{rule['conditions']}；"
                f"仅在该岛画像 {rule['source_profile']} 的树内产生过。",
                f"- 证据：run `{experiment_id}`、summary `{rule['summary_id']}`、"
                f"来源节点 `{rule['source_node_id']}`；"
                f"评估器读数 {json.dumps(rule['metrics'], ensure_ascii=False)}；"
                f"置信度 {rule['confidence_status']}。",
                f"- 观察结果：投递 {rule['deliveries']} 次，"
                f"采纳 {rule['accepted']} 次，拒绝 {rule['rejected']} 次，"
                f"采纳后生成的已评估候选 {len(rule['adopted_by'])} 个"
                + (f"（拒绝原因 {', '.join(rule['rejection_reasons'])}）"
                   if rule["rejection_reasons"] else "")
                + "。",
            ]
            for adoption in rule["adopted_by"][:3]:
                lines.append(
                    f"  - 岛 {adoption['target_island_id']} 用摘要生成候选 "
                    f"`{adoption['candidate_node_id']}`（application "
                    f"`{adoption['application_id']}`，评估 "
                    f"`{adoption['evaluation_id'] or '未完成'}`）："
                    f"得分 {adoption['score']}，相对父节点 "
                    f"{adoption['delta_score']}，噪声带 {adoption['noise_delta']}，"
                    f"{'超出噪声带' if adoption['beat_noise'] else '未超出噪声带'}。"
                )
            if kind == "best":
                lines.append(
                    "- 失败条件：同一操作复现时 `delta_vs_parent <= 0`，"
                    f"或涨幅落在该候选自身的噪声带内（本次来源节点涨幅为 {gain}）。"
                    "换任务指纹后无法复现，本条对该任务不适用。"
                )
            else:
                lines.append(
                    "- 失败条件：本条只说明该写法在来源岛的这批候选上失败过，"
                    "不构成跨任务的禁止；若同类写法在新任务上得到正收益，应改写为“条件不适用”。"
                )
            lines += [
                f"- 复验命令：`fe evolve local {task_dir} --mock --report-only "
                f"--resume {experiment_id}` 重建报告核对 `exchange` 与 `cost`；"
                f"再按本脚本重新导出，比较 `{rule['summary_id']}` 的读数是否一致。",
                "",
            ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="export_experience_skill.py",
        description=(
            "从一次三岛运行的 fe.db 与 run_summary.json 导出经验 Skill 草稿"
            "与机器可读证据索引（只写脱敏结论，不写候选源码或原始数据）。"
        ),
    )
    parser.add_argument("db", help="运行数据库 fe.db 的路径")
    parser.add_argument("summary", help="该运行的 run_summary.json 路径")
    parser.add_argument(
        "--out-dir",
        help="输出目录，默认为 run_summary.json 同级的 skills/ 子目录",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已存在的草稿（默认拒绝，以免抹掉上一轮证据）",
    )
    parser.add_argument(
        "--task-dir",
        default="<task_dir>",
        help="写进复验命令里的任务目录名，默认占位符",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    summary_path = Path(args.summary)
    if not db_path.exists():
        _fail(f"run database not found: {db_path}")
    if not summary_path.exists():
        _fail(f"run summary not found: {summary_path}")
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"{summary_path} is not valid JSON: {exc}")

    out_dir = Path(args.out_dir) if args.out_dir else summary_path.parent / "skills"
    resolved = out_dir.resolve()
    if resolved == PROJECT_SKILLS_ROOT or PROJECT_SKILLS_ROOT in resolved.parents:
        _fail(
            f"refusing to write into the project skill tree ({PROJECT_SKILLS_ROOT}); "
            "a draft belongs to its run directory and must be reviewed before merging"
        )
    draft_path = resolved / "experience_skill_draft.md"
    index_path = resolved / "evidence_index.json"
    if draft_path.exists() and not args.force:
        _fail(f"{draft_path} already exists; pass --force to overwrite it")

    data = collect(db_path)
    resolved.mkdir(parents=True, exist_ok=True)
    evidence = {
        "schema": "fe-experience-evidence/1",
        "experiment_id": data["experiment_id"],
        "run_identity": data["identity"],
        "island_profiles": data["profiles"],
        "run_summary_view": {
            key: summary.get(key)
            for key in ("status", "stop_reason", "iterations_done", "best_score",
                        "total_tokens", "islands", "exchange", "cost")
            if key in summary
        },
        "rule_count": len(data["rules"]),
        "rules": data["rules"],
        "sanitization": {
            "source_code_included": False,
            "raw_data_included": False,
            "api_keys_included": False,
            "summary_text_max_chars": MAX_TEXT_CHARS,
        },
        "review_status": "draft_not_cross_run_verified",
    }
    draft_path.write_text(
        render_markdown(data, summary, args.task_dir), encoding="utf-8"
    )
    index_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "experiment_id": data["experiment_id"],
        "rules": len(data["rules"]),
        "draft": str(draft_path),
        "evidence_index": str(index_path),
        "review_status": "draft_not_cross_run_verified",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Export evaluator-backed stage metrics and a self-contained delivery report."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import sqlite3
import shutil
import zipfile
from typing import Any

from faultevolve.effect_report import PERFORMANCE_KEYS, _baseline_features, program_complexity
from faultevolve.research_campaign import describe_route, write_json


def _load(path: Path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def token_usage(calls: list[dict]) -> dict:
    fresh = [c for c in calls if not c["cached"]]
    prompt = sum(c["prompt_tokens"] or 0 for c in fresh)
    completion = sum(c["completion_tokens"] or 0 for c in fresh)
    by_stage = Counter()
    for call in fresh:
        by_stage[call["stage"] or call["purpose"]] += (call["prompt_tokens"] or 0) + (call["completion_tokens"] or 0)
    return {"calls": len(calls), "prompt_tokens": prompt, "completion_tokens": completion,
            "total_tokens": prompt + completion, "by_stage": dict(by_stage),
            "cached_calls": len(calls) - len(fresh),
            "unknown_usage_calls": sum(c["outcome"] != "ok" or not ((c["prompt_tokens"] or 0) +
                (c["completion_tokens"] or 0)) for c in fresh)}


def _row(phase: str, node: dict, evaluation: dict | None, code: str, *, round_number: int | None,
         usage: dict | None = None, features: int | None = None, **extra) -> dict:
    valid = (evaluation or {}).get("validity") == 1.
    metric = (evaluation or {}).get("metric") or {}
    try:
        complexity = program_complexity(code, features)
        route = describe_route("report", code, "report")
    except (SyntaxError, ValueError, TypeError):
        complexity, route = {}, None
    performance = {key: ((evaluation or {}).get("combined_score") if key == "combined_score" else metric.get(key))
                   if valid else None for key in PERFORMANCE_KEYS}
    return {"round": round_number, "phase": phase, "node_id": node["id"],
            "parent_id": node.get("parent_id"), "island_id": node.get("island_id"),
            "operator": node.get("operator"), "valid": valid,
            **performance, "runtime_s": (evaluation or {}).get("cost_time"),
            "task_metrics": metric if valid else {},
            "sample_count": metric.get("sample_count"), "weighted_population": metric.get("weighted_population"),
            "estimated_parameters": complexity.get("estimated_parameters"),
            "parameter_count_kind": "静态容量估计，非训练后实测；无法确定时为空",
            "source_lines": complexity.get("source_lines"), "ast_nodes": complexity.get("ast_nodes"),
            "branch_points": complexity.get("branch_points"), "functions": complexity.get("functions"),
            "model_families": complexity.get("model_families", []),
            "ensemble_fits": complexity.get("ensemble_fits"),
            "declared_hyperparameters": (route or {}).get("default_parameters", {}),
            "prompt_tokens": (usage or {}).get("prompt_tokens", 0),
            "completion_tokens": (usage or {}).get("completion_tokens", 0),
            "total_tokens": (usage or {}).get("total_tokens", 0),
            "token_stages": (usage or {}).get("by_stage", {}),
            "error": (evaluation or {}).get("error_info", ""),
            "source_sha256": hashlib.sha256(code.encode()).hexdigest(), **extra}


def observations(rows: list[dict], total_tokens: int) -> dict:
    baseline = next((r["combined_score"] for r in rows if r["phase"] == "baseline"), None)
    defaults = {r["node_id"]: r for r in rows if r["phase"] == "structure_default"}
    selected = [r for r in rows if r["phase"] == "structure_selected"]
    best, last_improvement = baseline, 0
    gains, convergence = [], []
    for row in selected:
        score = row["combined_score"]
        if score is not None and (best is None or score > best):
            best, last_improvement = score, row["round"]
        default = defaults.get(row["node_id"], {}).get("combined_score")
        if score is not None and default is not None:
            gains.append({"round": row["round"], "node_id": row["node_id"], "gain": score - default})
        convergence.append({"round": row["round"], "score": score, "best_so_far": best,
                            "cumulative_tokens": row.get("cumulative_tokens")})
    gain = best - baseline if best is not None and baseline is not None else None
    return {"last_improvement_round": last_improvement,
            "rounds_after_last_improvement": len(selected) - last_improvement,
            "valid_structure_rounds": sum(r["valid"] for r in selected),
            "invalid_structure_rounds": sum(not r["valid"] for r in selected),
            "paired_tuning_gains": gains, "tuning_improved_structures": sum(g["gain"] > 0 for g in gains),
            "overall_gain": gain,
            "tokens_per_ros_point": total_tokens / gain if gain is not None and gain > 0 else None,
            "convergence": convergence,
            "evidence_scope": "仅为本次运行的描述性观察；不是多次重复或独立测试上的因果结论"}


def build_delivery_report(output: Path, db: Path, task: Path) -> dict:
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        experiment = dict(conn.execute("SELECT * FROM experiment").fetchone())
        nodes = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM node ORDER BY created_at,id")}
        events = [dict(r) for r in conn.execute("SELECT * FROM event ORDER BY id")]
        calls = [dict(r) for r in conn.execute("SELECT * FROM llm_call ORDER BY created_at,id")]
    for event in events:
        event["payload"] = json.loads(event["payload_json"])
    for node in nodes.values():
        node["artifact"] = json.loads(node["artifact_json"])
        node["evaluation"] = json.loads(node["evidence_json"] or "{}").get("evaluation")
    completed = [e for e in events if e["type"] == "iteration_complete"]
    round_map = {event["payload"].get("node_id"): i for i, event in enumerate(completed, 1)}
    attempts = [e for e in events if e["type"] == "attempt_started"]
    first_start = attempts[0]["ts"] if attempts else ""
    baseline_calls = [c for c in calls if not first_start or c["created_at"] <= first_start]
    roots = [n for n in nodes.values() if n["operator"] == "init"]
    baseline = roots[0] if roots else None
    rows, trials = [], []
    if baseline:
        rows.append(_row("baseline", baseline, baseline["evaluation"], baseline["artifact"]["code"],
                         round_number=0, usage=token_usage(baseline_calls), features=_baseline_features(task)))
    previous_end = first_start
    for number, event in enumerate(completed, 1):
        node = nodes.get(event["payload"].get("node_id"))
        if node is None:
            continue
        round_calls = [c for c in calls if previous_end < c["created_at"] <= event["ts"]]
        previous_end = event["ts"]
        directory = output / "hyperparameters/structures" / node["id"]
        ledger = _load(directory / "ledger.json", {})
        if ledger.get("trials"):
            default = ledger["trials"][0]
            default_dir = directory / "runs" / default["candidate_id"]
            rows.append(_row("structure_default", node, _load(default_dir / "evaluation.json"),
                             (default_dir / "candidate.py").read_text(), round_number=number))
        selected = _row("structure_selected", node, node["evaluation"], node["artifact"]["code"],
                        round_number=number, usage=token_usage(round_calls),
                        cumulative_tokens=token_usage([c for c in calls if c["created_at"] <= event["ts"]])["total_tokens"],
                        completed_trials=ledger.get("completion_count", 0),
                        delta_score=event["payload"].get("delta"), outcome=event["payload"].get("outcome"))
        rows.append(selected)
    # Repair nodes and their trials remain visible even without a separate outer round.
    for node in nodes.values():
        if node["operator"] == "repair" and node["evaluation"] is not None:
            rows.append(_row("repair_selected", node, node["evaluation"], node["artifact"]["code"],
                             round_number=None, tokens_in_parent_round=True))
        directory = output / "hyperparameters/structures" / node["id"]
        ledger = _load(directory / "ledger.json", {})
        for trial in ledger.get("trials", []):
            run = directory / "runs" / trial["candidate_id"]
            trials.append(_row("parameter_trial", node, _load(run / "evaluation.json"),
                (run / "candidate.py").read_text(), round_number=round_map.get(node["id"]),
                candidate_id=trial["candidate_id"], trial_number=trial["trial_number"],
                parameters=trial["parameters"], depth=trial["depth"],
                parameter_parent_id=trial.get("parent_id"),
                evaluation_wall_s=trial["execution"].get("duration_seconds")))
    workflow = _load(output / "workflow-result.json", {})
    inputs = _load(db.parent / "workflow/manifest.json", {})
    state = _load(output / "workflow.json", {})
    summary = _load(output / "run_summary.json", {})
    scored = [n for n in nodes.values() if (n["evaluation"] or {}).get("validity") == 1.]
    best = max(scored, key=lambda n: n["evaluation"]["combined_score"], default=None)
    grouped = defaultdict(list)
    for call in calls:
        grouped[call["island_id"]].append(call)
    tail_calls = [c for c in calls if previous_end and c["created_at"] > previous_end]
    rollup = token_usage(calls)
    report = {"schema": "faultevolve.closed-loop-delivery/v1", "run_id": experiment["id"],
        "state": state.get("state", experiment["status"]), "phase": state.get("phase"),
        "split": workflow.get("split", inputs.get("evaluation_split", "val")), "iterations_done": experiment["iterations_done"],
        "completed_trials": len(trials), "best_node_id": best["id"] if best else None,
        "best_score": best["evaluation"]["combined_score"] if best else None,
        "baseline_score": (baseline["evaluation"] or {}).get("combined_score") if baseline else None,
        "token_usage": rollup, "tokens_by_island": {k: token_usage(v) for k, v in grouped.items()},
        "llm_calls": [{k: c.get(k) for k in ("id", "node_id", "island_id", "stage", "purpose", "model",
            "prompt_tokens", "completion_tokens", "latency_ms", "cached", "outcome", "created_at",
            "request_id", "transport_attempts")} for c in calls],
        "unallocated_post_round_tokens": token_usage(tail_calls),
        "stage_metrics": rows, "parameter_trials": trials,
        "observations": observations(rows, rollup["total_tokens"]),
        "workflow": workflow, "run_summary": summary,
        "data_workflow": _load(output / "data-workflow.json", {}),
        "exchange_counts": dict(Counter(e["type"] for e in events if e["type"].startswith("exchange_"))),
        "insight_count": sum(e["type"] == "insight_extracted" for e in events),
        "limitations": [
            "仅使用当前任务的本地评估划分；未启动私有测试，尚无独立泛化证据。",
            "准确率为机队权重下 (TP+TN)/总权重，另列无权样本准确率；precision 是精确率。",
            "故障样本占比很低，单看准确率会掩盖漏告；需同时比较召回率、误告率、漏告率和ROS。",
            "TP/FP/FN/TN 为机队加权数量，可能为小数，不能当作抽样盘的整数计数。",
            "参数量是源码静态容量估计；未知保持空值。未测量训练后模型文件大小、FLOPs或真实内存。",
            "逐轮 Token 按上轮完成至本轮完成的时间窗口归属，包括本轮反思和修复；内层参数试验为0。",
            "Token 来自提供商用量账本，缓存命中不算新增消耗；未知用量单独计数，不推算费用。",
            "未知/无效评估保持空值；运行中报告仅反映已完成的记录。",
        ]}
    return report


def _csv(path: Path, rows: list[dict]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})


def _format(value, percentage=False):
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value * 100:.3f}%" if percentage else f"{value:,.3f}"
    return str(value)


def markdown_report(report: dict) -> str:
    text = ["# 逐结构闭环反馈完整运行报告", "",
        f"运行：`{report['run_id']}`；状态：**{report['state']}**；本地评估划分：{report['split']}。", "",
        f"已完成 {report['iterations_done']} 轮结构演化、{report['completed_trials']} 次参数试验。"
        f"初始评分 {_format(report['baseline_score'])}，当前最优评分 {_format(report['best_score'])}。", "",
        "## 各迭代阶段的预测性能", "",
        "| 轮次 | 阶段 | 岛 | 评分 | 准确率 | 精确率 | 召回率 | 误告率 | 漏告率 | 加权误告数 | 加权漏告数 |",
        "|---|---|---|---|---|---|---|---|---|---|---|"]
    labels = {"baseline": "原始基线", "structure_default": "结构默认参数", "structure_selected": "结构调优后", "repair_selected": "修复后"}
    for row in report["stage_metrics"]:
        values = [row["round"], labels[row["phase"]], row["island_id"], row["combined_score"]]
        text.append("| " + " | ".join([_format(v) for v in values] +
            [_format(row.get(k), True) for k in ("accuracy", "precision", "recall", "false_alarm_rate", "missed_detection_rate")] +
            [_format(row.get(k)) for k in ("false_positives", "false_negatives")]) + " |")
    text += ["", "## 模型规模、复杂度与逐轮 Token", "",
        "| 轮次 | 节点 | 模型族 | 参数量（静态估计） | 有效代码行 | AST 节点 | 分支点 | 运行秒数 | 本轮 Token | 累计 Token |",
        "|---|---|---|---|---|---|---|---|---|---|"]
    for row in report["stage_metrics"]:
        if row["phase"] == "structure_default":
            continue
        text.append("| " + " | ".join(_format(v) for v in (
            row["round"], row["node_id"], ", ".join(row["model_families"]), row["estimated_parameters"],
            row["source_lines"], row["ast_nodes"], row["branch_points"], row["runtime_s"], row["total_tokens"],
            row.get("cumulative_tokens"))) + " |")
    usage = report["token_usage"]
    observed = report.get("observations", {})
    text += ["", f"提供商已记录的新增 Token：**{usage['total_tokens']:,}**"
             f"（输入 {usage['prompt_tokens']:,}，输出 {usage['completion_tokens']:,}）；"
             f"未知用量调用 {usage['unknown_usage_calls']} 次，缓存命中 {usage['cached_calls']} 次。", "",
             "分阶段 Token：`" + json.dumps(usage["by_stage"], ensure_ascii=False) + "`。", "",
             "## 闭环证据与解释", "",
             "系统按“提出结构 → 仅对该结构搜索参数 → 将选中代码及实测成绩写回节点 → "
             "更新选择与经验 → 下一轮”的顺序运行。每轮默认/调优后的配对指标见上表，"
             "每次参数试验见 parameter-trials.csv；逐结构原始提案与选中版本见 hyperparameters/structures/。", "",
             f"已记录经验提炼 {report['insight_count']} 次，岛间交流事件：`"
             + json.dumps(report["exchange_counts"], ensure_ascii=False) + "`。", "",
             "当前报告只描述本次轨迹；没有对照与重复试验，不能把收益单独归因于闭环、知识注入或某个算子。", "",
             f"本次最后刷新最优的轮次：{observed.get('last_improvement_round', '未记录')}；之后完成 "
             f"{observed.get('rounds_after_last_improvement', '未记录')} 轮。具有默认/调优配对记录的结构中，"
             f"{observed.get('tuning_improved_structures', '未记录')} 个在参数搜索后提高了评分。"
             "这些观察可用于规划下一次的停滞窗口和参数预算，但不能据单次轨迹直接规定通用停止阈值。", "",
             "## 指标定义与局限", ""]
    text.extend("- " + item for item in report["limitations"])
    text += ["", "## 交付文件", "", "- `stage-metrics.csv/json`：基线、各轮默认与调优后指标。",
             "- `parameter-trials.csv/json`：全部内层参数试验、参数配置、规模与复杂度。",
             "- `closed-loop-report.json`：完整汇总和提供商 Token 账本统计。",
             "- `../workflow-best.py`：全流程最终程序。", ""]
    return "\n".join(text)


def write_delivery_report(output: Path, db: Path, task: Path) -> dict:
    report = build_delivery_report(output, db, task)
    destination = output / "reports"
    destination.mkdir(exist_ok=True)
    write_json(destination / "closed-loop-report.json", report)
    write_json(destination / "stage-metrics.json", {"rows": report["stage_metrics"]})
    write_json(destination / "parameter-trials.json", {"rows": report["parameter_trials"]})
    _csv(destination / "stage-metrics.csv", report["stage_metrics"])
    _csv(destination / "parameter-trials.csv", report["parameter_trials"])
    _csv(destination / "token-ledger.csv", report["llm_calls"])
    _csv(destination / "convergence.csv", report["observations"]["convergence"])
    markdown = markdown_report(report)
    (destination / "完整运行报告.md").write_text(markdown, encoding="utf-8")
    columns = ["round", "phase", "island_id", "node_id", "combined_score", "accuracy", "precision", "recall",
               "false_alarm_rate", "missed_detection_rate", "false_positives", "false_negatives",
               "estimated_parameters", "source_lines", "ast_nodes", "total_tokens"]
    header = "".join(f"<th>{html.escape(k)}</th>" for k in columns)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(_format(row.get(k)))}</td>" for k in columns) + "</tr>"
                   for row in report["stage_metrics"])
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>逐结构闭环运行结果</title>'
        '<style>body{font:14px system-ui;margin:32px}table{border-collapse:collapse}th,td{padding:7px;border:1px solid #ddd;white-space:nowrap}th{position:sticky;top:0;background:#eee}input{padding:8px;margin-bottom:16px}pre{white-space:pre-wrap}</style>'
        '<h1>逐结构闭环运行结果</h1><p>参数量为静态估计；表格比例以0–1表示，完整中文口径见下方报告。</p>'
        '<input id="filter" placeholder="按轮次、阶段、岛或节点筛选" oninput="document.querySelectorAll(\'tbody tr\').forEach(r=>r.hidden=!r.textContent.includes(this.value))">'
        '<div style="overflow:auto"><table><thead><tr>' + header + '</tr></thead><tbody>' + body +
        '</tbody></table></div><h2>完整报告</h2><pre>' + html.escape(markdown) + '</pre></html>')
    (destination / "完整运行报告.html").write_text(page, encoding="utf-8")
    return report


def package_skill(report: dict, source: Path, output: Path) -> Path:
    if report["state"] != "finished":
        raise ValueError("运行未完成，不能把过程记录打包成已完成实验证据")
    destination = output / "skill" / "fe-closed-loop-tuning"
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("Skill 交付不跟随符号链接")
        if path.is_file() and path.suffix in {".md", ".yaml", ".yml", ".json"}:
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    evidence = {key: report[key] for key in ("run_id", "state", "split", "iterations_done", "completed_trials",
        "baseline_score", "best_score", "best_node_id", "token_usage", "exchange_counts", "insight_count", "limitations")}
    evidence["stage_metrics"] = report["stage_metrics"]
    evidence["observations"] = report.get("observations", {})
    reference = destination / "references"
    reference.mkdir(exist_ok=True)
    write_json(reference / "latest-run.json", evidence)
    (reference / "latest-run.md").write_text(markdown_report(report), encoding="utf-8")
    main = destination / "SKILL.md"
    main.write_text(main.read_text(encoding="utf-8") +
        "\n## 本次逐结构闭环实验证据\n\n"
        f"运行 `{report['run_id']}` 已完成 {report['iterations_done']} 轮结构演化与 "
        f"{report['completed_trials']} 次参数试验。见 [本次报告](references/latest-run.md) 和 "
        "[结构化证据](references/latest-run.json)。这些数字仅描述本次验证轨迹，"
        "不能作为其他任务的默认超参数或独立泛化证明。完整 CSV 和试验代码位于同一交付目录。\n",
        encoding="utf-8")
    archive = output / "fe-closed-loop-tuning.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path in destination.rglob("*"):
            if path.is_file():
                zipped.write(path, path.relative_to(destination.parent))
    return destination

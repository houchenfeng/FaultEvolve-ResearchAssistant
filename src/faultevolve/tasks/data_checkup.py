"""Read-only, aggregate quality checks on the adapter's train discovery view."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from faultevolve.tasks.protocol import DiscoveryFrames


def _fingerprint(frame: pd.DataFrame) -> str:
    """Identify the inspected view without exporting identifiers or raw values."""
    digest = hashlib.sha256()
    digest.update(json.dumps([(str(c), str(t)) for c, t in frame.dtypes.items()]).encode())
    digest.update(pd.util.hash_pandas_object(frame, index=False).to_numpy().tobytes())
    return digest.hexdigest()


def analyze_frames(frames: DiscoveryFrames) -> tuple[dict, dict, pd.DataFrame]:
    """Return facts, quality findings and coverage; never clean the input frames.

    Discovery adapters may filter or transform data before this function sees it.
    Consequently this report is explicitly scoped to that view, not the raw files.
    """
    labels = pd.DataFrame(frames.labels)
    history = pd.DataFrame(frames.history)
    issues: list[dict[str, Any]] = []

    def issue(code: str, severity: str, count: int, message: str, action: str, source: str) -> None:
        issues.append(dict(code=code, severity=severity, count=int(count), message=message,
                           recommendation=action, source=source))

    for name, frame, required in (
        ("labels", labels, [frames.unit_col, frames.label_col]),
        ("history", history, [frames.unit_col, frames.time_col]),
    ):
        if frame.empty:
            issue(f"{name}_empty", "blocking", 0, f"{name} 没有记录。",
                  "检查训练数据准备结果和适配器读取路径。", name)
        for col in required:
            if col not in frame:
                issue(f"{name}_missing_column", "blocking", 1, f"{name} 缺少必需字段 {col}。",
                      "按任务数据契约补齐字段，再重新体检。", f"{name}.{col}")
            elif frame[col].isna().any():
                issue(f"{name}_missing_key", "blocking", int(frame[col].isna().sum()),
                      f"{name}.{col} 存在空值。", "核对原始记录；不要把缺失标识或标签填成默认值。",
                      f"{name}.{col}")

    y = labels[frames.label_col] if frames.label_col in labels else pd.Series(dtype=float)
    n_positive = int(y.eq(1).sum())
    n_negative = int(y.eq(0).sum())
    invalid_labels = int((y.notna() & ~y.isin([0, 1])).sum())
    if invalid_labels:
        issue("invalid_labels", "blocking", invalid_labels, "标签包含 0/1 以外的取值。",
              "核对标签含义和生成规则，不自动转换为二分类。", f"labels.{frames.label_col}")
    if len(y) and (n_positive == 0 or n_negative == 0):
        issue("single_class", "blocking", n_positive + n_negative, "有效标签只有一个类别或没有有效类别。",
              "检查抽样与标签生成规则，补齐可用于二分类评估的数据。", f"labels.{frames.label_col}")

    if frames.unit_col in labels:
        duplicates = int(labels[frames.unit_col].dropna().duplicated().sum())
        if duplicates:
            issue("duplicate_label_units", "blocking", duplicates, "标签表中设备标识不唯一。",
                  "核对重复标签及冲突原因，确定去重规则后再处理。", f"labels.{frames.unit_col}")
    if {frames.unit_col, frames.time_col}.issubset(history.columns):
        duplicates = int(history.duplicated([frames.unit_col, frames.time_col]).sum())
        if duplicates:
            issue("duplicate_history_keys", "decision_required", duplicates, "历史表中设备与时间组合重复。",
                  "先确认是重复采集还是同一时间的合法多条事件，再确定聚合方式。",
                  f"history.[{frames.unit_col},{frames.time_col}]")

    if frames.unit_col in labels and frames.unit_col in history:
        label_units = pd.Index(labels[frames.unit_col].dropna().unique())
        history_units = pd.Index(history[frames.unit_col].dropna().unique())
        missing_history = len(label_units.difference(history_units))
        missing_labels = len(history_units.difference(label_units))
        if missing_history:
            issue("units_without_history", "blocking", missing_history, "部分有标签设备没有历史记录。",
                  "检查关联键、时间过滤和数据覆盖，避免静默丢弃设备。", "labels ↔ history")
        if missing_labels:
            issue("units_without_labels", "decision_required", missing_labels, "部分历史设备没有标签。",
                  "确认训练范围；如需排除，记录排除数量和原因。", "history ↔ labels")

    time_range = None
    if frames.time_col in history:
        times = history[frames.time_col]
        if pd.api.types.is_numeric_dtype(times):
            invalid_time = int((times.notna() & ~np.isfinite(times)).sum())
        else:
            parsed = pd.to_datetime(times, errors="coerce", utc=True, format="mixed")
            invalid_time = int((times.notna() & parsed.isna()).sum())
            if parsed.notna().any():
                time_range = {"start": parsed.min().isoformat(), "end": parsed.max().isoformat()}
        if invalid_time:
            issue("invalid_time", "blocking", invalid_time, "历史时间包含无法解析或非有限的值。",
                  "按数据契约统一时间格式和时区，再检查时间窗口。", f"history.{frames.time_col}")

    coverage_rows = []
    for col in history.columns:
        if col in (frames.unit_col, frames.time_col):
            continue
        series = history[col]
        missing = int(series.isna().sum())
        unique = int(series.nunique(dropna=True))
        non_finite = 0
        if pd.api.types.is_numeric_dtype(series):
            non_finite = int((series.notna() & ~np.isfinite(series)).sum())
        coverage_rows.append({
            "column": str(col), "dtype": str(series.dtype),
            "non_null_rate": float(series.notna().mean()) if len(series) else None,
            "missing_count": missing, "non_finite_count": non_finite,
            "unique_count": unique,
        })
        if len(series) and missing:
            severity = "decision_required" if missing / len(series) >= 0.5 else "minor"
            issue("missing_feature", severity, missing, f"字段 {col} 存在缺失。",
                  "先检查厂商或设备类型差异，再选择保留缺失、分组填补或删除；仅在训练数据拟合填补规则。",
                  f"history.{col}")
        if non_finite:
            issue("non_finite_feature", "decision_required", non_finite, f"字段 {col} 含无穷值。",
                  "检查计算溢出或采集异常，明确转换规则并记录影响行数。", f"history.{col}")
        if len(series) and unique == 1:
            issue("constant_feature", "minor", len(series) - missing, f"字段 {col} 的非空值为常量。",
                  "核对采集范围；在确认无业务作用后再从特征集中移除。", f"history.{col}")

    priority = {"blocking": 0, "decision_required": 1, "minor": 2}
    issues.sort(key=lambda item: priority[item["severity"]])
    counts = {level: sum(i["severity"] == level for i in issues)
              for level in ("blocking", "decision_required", "minor")}
    status = "blocked" if counts["blocking"] else "review" if issues else "ready"
    facts = {
        "n_samples": len(labels), "n_positive": n_positive, "n_negative": n_negative,
        "n_history_rows": len(history), "label_semantics": "1=failure",
        "columns": [str(c) for c in history.columns],
        "min_detectable_effect": None,
        "min_detectable_effect_note": "未进行功效分析，不能由数据体检推断最小可检测效应。",
        "quality_status": status,
    }
    quality = {
        "schema_version": "1.0", "scope": "adapter_train_view", "quality_status": status,
        "issue_counts": counts, "issues": issues, "time_range": time_range,
        "provenance": {
            "provider": "discovery_frames", "pandas_version": pd.__version__,
            "labels_sha256": _fingerprint(labels), "history_sha256": _fingerprint(history),
            "fingerprint_scope": "列名、类型和有序行值；不包含 DataFrame 索引",
        },
        "processing": {"mode": "read_only", "transformations_applied": []},
        "limitations": [
            "仅检查适配器返回的 train 视图；适配器可能已去重、截断历史或转换类型，不能据此证明原始文件无异常。",
            "未读取验证集、私有测试集或 eval_only；未检查跨划分设备重叠。",
            "未核对逐设备 cutoff 和标签生成过程，不能据此证明不存在未来信息泄漏。",
            "数值型时间不推断时间单位；报告中的日期范围仅来自可解析的日期字段。",
        ],
    }
    coverage = pd.DataFrame(coverage_rows, columns=[
        "column", "dtype", "non_null_rate", "missing_count", "non_finite_count", "unique_count",
    ])
    return facts, quality, coverage


def render_report(facts: dict, quality: dict) -> str:
    """Render an evidence-backed Chinese report without exposing row values."""
    statuses = {"blocked": "存在阻断问题", "review": "需要复核", "ready": "当前检查未发现问题"}
    levels = {"blocking": "阻断", "decision_required": "需决策", "minor": "一般"}
    lines = [
        "# 训练数据体检报告", "", f"结论：{statuses[quality['quality_status']]}。", "",
        "## 数据概况", "",
        f"标签记录 {facts['n_samples']} 条，正例 {facts['n_positive']} 条，负例 {facts['n_negative']} 条；"
        f"历史记录 {facts['n_history_rows']} 条。", "",
        "来源：适配器 discovery_frames 返回的 train 视图。所有统计均为聚合量。", "",
    ]
    if quality["time_range"]:
        span = quality["time_range"]
        lines += [f"历史时间范围：{span['start']} 至 {span['end']}。", ""]
    counts = quality["issue_counts"]
    lines += ["## 数据质量与处理建议", "",
              f"阻断问题 {counts['blocking']} 项，需决策问题 {counts['decision_required']} 项，"
              f"一般问题 {counts['minor']} 项。", ""]
    if not quality["issues"]:
        lines.append("在本次检查范围内未发现质量问题；未覆盖的检查见下方限制。")
    for item in quality["issues"]:
        lines.append(f"- **{levels[item['severity']]}**：{item['message']} 数量：{item['count']}。"
                     f"依据：`{item['source']}`。建议：{item['recommendation']}")
    lines += [
        "", "## 处理记录与后续流程", "",
        "本次仅体检，未执行清洗或修改输入数据。", "",
        "1. 先解决阻断问题，再按业务含义复核需决策问题。",
        "2. 将选定的转换规则写入独立处理脚本，输出到新的目录；记录输入版本、配置和各步骤影响行数。",
        "3. 仅用训练数据拟合填补、归一化及特征选择规则，再应用于后续划分。",
        "4. 重新体检处理结果；按任务契约另外核对时间划分、cutoff 和标签生成规则。", "",
        "## 可复现依据与限制", "",
        f"标签视图 SHA-256：`{quality['provenance']['labels_sha256']}`",
        f"历史视图 SHA-256：`{quality['provenance']['history_sha256']}`", "",
        facts["min_detectable_effect_note"], "",
        *[f"- {item}" for item in quality["limitations"]], "",
    ]
    return "\n".join(lines)

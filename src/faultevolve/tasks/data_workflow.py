"""Auditable HDD train preparation, with no changes to benchmark source files."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from faultevolve.config import DataWorkflowConfig
from faultevolve.research import _write_json
from faultevolve.research_campaign import digest
from faultevolve.tasks.data_checkup import analyze_frames, render_report
from faultevolve.tasks.protocol import DiscoveryFrames, PreparedWorkflowData


def prepare_hdd_workflow(public: Path, workspace: Path, policy: DataWorkflowConfig) -> PreparedWorkflowData:
    """Snapshot only the adapter's declared public/validation inputs."""
    data = prepare_train(public, workspace, policy)
    if data["state"] != "passed":
        raise ValueError("数据复检未通过：" + ", ".join(data["unresolved_codes"]))
    root = workspace / "data"
    files, validation = {}, {}
    if (public.parent / "meta.json").is_file():
        shutil.copyfile(public.parent / "meta.json", root / "meta.json")
        files["data/meta.json"] = digest(root / "meta.json")
    for name in ("val_history.csv.gz", "val_index.csv"):
        shutil.copyfile(public / name, root / "public" / name)
        validation[f"public/{name}"] = digest(root / "public" / name)
    labels = next((path for path in (public.parent / "eval_only/val_labels.csv",
        public.parent / "val_labels.csv", public / "val_labels.csv") if path.is_file()), None)
    if labels is None:
        raise ValueError("验证标签不可用；不能进入本地评估")
    (root / "eval_only").mkdir(exist_ok=True)
    shutil.copyfile(labels, root / "eval_only/val_labels.csv")
    validation["eval_only/val_labels.csv"] = digest(root / "eval_only/val_labels.csv")
    files.update({f"data/public/{name}": value for name, value in data["derived_sha256"].items()})
    files.update({f"data/{name}": value for name, value in validation.items()})
    source = Path(__file__)
    shutil.copyfile(source, workspace / "processing.py")
    files["processing.py"] = digest(workspace / "processing.py")
    return PreparedWorkflowData(data, {"HDD_BENCH_DATA_ROOT": str(root)}, files, validation)


def inspect_train(labels: pd.DataFrame, history: pd.DataFrame):
    """Inspect the full train tables before the discovery adapter filters them."""
    facts, quality, coverage = analyze_frames(DiscoveryFrames(
        labels=labels, history=history, unit_col="serial_number", time_col="date"))
    quality["scope"] = "raw_train_files"
    quality["provenance"]["provider"] = "workflow_train_csv"
    quality["limitations"] = [
        "只分析训练文件；未分析验证标签、私有测试集或跨划分重叠。",
        "未核验原始标签生成过程，不能据此证明标签没有未来信息。",
        "保留的缺失值与常量由候选算法处理；不在全量数据拟合填补或缩放规则。",
    ]

    def block(code: str, count: int, message: str):
        if count:
            quality["issues"].append({"code": code, "severity": "blocking", "count": int(count),
                "message": message, "recommendation": "核对训练数据契约后重新运行。", "source": "train"})

    for col in ("cutoff_date", "weight"):
        block("missing_train_metadata", int(col not in labels), f"训练标签缺少 {col}。")
    if "weight" in labels:
        weights = pd.to_numeric(labels["weight"], errors="coerce")
        block("invalid_weight", int((weights.isna() | ~np.isfinite(weights) | weights.le(0)).sum()),
              "训练权重必须为有限正数。")
    if "cutoff_date" in labels:
        cutoffs = pd.to_datetime(labels["cutoff_date"], errors="coerce", utc=True, format="mixed")
        block("invalid_cutoff", int(cutoffs.isna().sum()), "训练 cutoff 日期缺失或无法解析。")
        if ("serial_number" in labels and not labels["serial_number"].duplicated().any()
                and {"serial_number", "date"}.issubset(history)):
            mapped = history["serial_number"].map(pd.Series(cutoffs.array, index=labels["serial_number"]))
            times = pd.to_datetime(history["date"], errors="coerce", utc=True, format="mixed")
            block("future_history", int((times > mapped).sum()), "训练历史存在 cutoff 之后的记录。")
    for col in history:
        if col.startswith("smart_") or col == "capacity_bytes":
            numeric = pd.to_numeric(history[col], errors="coerce")
            block("invalid_numeric_feature", int((history[col].notna() & numeric.isna()).sum()),
                  f"数值特征 {col} 包含无法解析的值。")
    counts = {severity: sum(i["severity"] == severity for i in quality["issues"])
              for severity in ("blocking", "decision_required", "minor")}
    quality["issue_counts"] = counts
    facts["quality_status"] = quality["quality_status"] = (
        "blocked" if counts["blocking"] else "review" if quality["issues"] else "ready")
    return facts, quality, coverage


def _save_check(directory: Path, result) -> None:
    facts, quality, coverage = result
    _write_json(directory / "data_facts.json", facts)
    _write_json(directory / "data_quality.json", quality)
    coverage.to_csv(directory / "field_coverage.csv", index=False)
    report = render_report(facts, quality).replace(
        "适配器 discovery_frames 返回的 train 视图", "完整训练 CSV（适配器过滤之前）")
    (directory / "data_report.md").write_text(report, encoding="utf-8")


def prepare_train(public: Path, output: Path, policy: DataWorkflowConfig) -> dict:
    """Apply only declared deterministic rules, then gate on unresolved findings.

    Ground truth, identifiers and dates are never imputed or silently discarded.
    The derived train files are the files subsequently given to every candidate.
    """
    sources = {name: digest(public / name) for name in ("train_labels.csv", "train_history.csv.gz")}
    labels = pd.read_csv(public / "train_labels.csv")
    history = pd.read_csv(public / "train_history.csv.gz")
    before = inspect_train(labels, history)
    _save_check(output / "before", before)
    transformations = []
    if policy.drop_exact_duplicates:
        count = int(history.duplicated().sum())
        if count:
            history = history.drop_duplicates().copy()
            transformations.append({"rule": "drop_exact_history_duplicates", "affected": count,
                                    "reason": "仅删除所有字段完全相同的重复采集记录。"})
    if policy.nonfinite_to_missing:
        for col in history.select_dtypes(include="number"):
            if col in ("date", "serial_number"):
                continue
            mask = history[col].notna() & ~np.isfinite(history[col])
            count = int(mask.sum())
            if count:
                history.loc[mask, col] = np.nan
                transformations.append({"rule": "nonfinite_to_missing", "column": str(col),
                                        "affected": count, "reason": "将无穷特征值标记为缺失，保留记录。"})
    after = inspect_train(labels, history)
    _save_check(output / "after", after)
    quality = after[1]
    unresolved = [issue for issue in quality["issues"] if issue["severity"] == "blocking"
                  or (issue["severity"] == "decision_required" and issue["code"] not in policy.accepted_issues)]
    accepted = sorted({i["code"] for i in quality["issues"] if i["code"] in policy.accepted_issues})
    report = {"state": "blocked" if unresolved else "passed", "scope": "raw_train_files",
              "policy": policy.model_dump(), "source_sha256": sources,
              "before": before[0], "after": after[0], "transformations": transformations,
              "accepted_issues": accepted, "unresolved_codes": sorted({i["code"] for i in unresolved}),
              "source_data_unchanged": True,
              "comparison_note": "所有候选与初始解使用同一训练副本；跨实验比较须核对处理规则与数据指纹。"}
    if not unresolved:
        derived = output / "data/public"
        derived.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(public / "train_labels.csv", derived / "train_labels.csv")
        if transformations:
            history.to_csv(derived / "train_history.csv.gz", index=False, compression={"method": "gzip", "mtime": 0})
        else:
            shutil.copyfile(public / "train_history.csv.gz", derived / "train_history.csv.gz")
        # Recheck the serialized files that the evaluator will actually receive.
        serialized = inspect_train(pd.read_csv(derived / "train_labels.csv"),
                                   pd.read_csv(derived / "train_history.csv.gz"))
        _save_check(output / "after", serialized)
        report["after"] = serialized[0]
        unresolved_serialized = [i["code"] for i in serialized[1]["issues"] if i["severity"] == "blocking"
            or (i["severity"] == "decision_required" and i["code"] not in policy.accepted_issues)]
        if unresolved_serialized:
            report.update(state="blocked", unresolved_codes=sorted(set(unresolved_serialized)))
        report["derived_sha256"] = {name: digest(derived / name) for name in sources}
    if any(digest(public / name) != expected for name, expected in sources.items()):
        raise ValueError("体检期间训练源文件发生变化，请稳定输入后重新运行")
    _write_json(output / "report.json", report)
    return report

#!/usr/bin/env python
"""Export a real run's aggregate metrics, report and completed-run Skill."""

from pathlib import Path
import argparse
import json
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from faultevolve.delivery_report import package_skill
from faultevolve.reporting import export_workflow_reports
from faultevolve.research_campaign import snapshot_database


def main():
    parser = argparse.ArgumentParser(description="导出逐阶段指标、中文报告与闭环反馈 Skill")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--runs-dir", type=Path)
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--partial", action="store_true", help="仅导出运行中的已完成指标，不打包 Skill")
    args = parser.parse_args()
    if args.manifest:
        manifest = json.loads(args.manifest.read_text())
    else:
        if not args.run_id or args.runs_dir is None or args.artifacts_dir is None:
            parser.error("指定 --manifest，或同时指定 --run-id、--runs-dir、--artifacts-dir")
        from faultevolve.cloud.engine import _validate_experiment_id
        manifest = {"run_id": _validate_experiment_id(args.run_id), "runs_dir": str(args.runs_dir),
                    "artifacts_dir": str(args.artifacts_dir)}
    output = Path(manifest["artifacts_dir"]) / manifest["run_id"]
    db = Path(manifest["runs_dir"]) / manifest["run_id"] / "fe.db"
    task = db.parent / "workflow/task"
    report = export_workflow_reports(output, db, task)
    if not args.partial:
        if report["state"] != "finished":
            raise ValueError("正式运行尚未完成，当前报告仅包含已完成记录；不能发布完成状态的 Skill")
        skill = package_skill(report, REPO / "skill/fe-closed-loop-tuning", output)
        snapshot_database(db, db.parent / "delivery-snapshot.sqlite", output / "database/fe.db")
        print(json.dumps({"skill": str(skill), "zip": str(output / "fe-closed-loop-tuning.zip")}, ensure_ascii=False))
    print(json.dumps({k: report[k] for k in ("run_id", "state", "iterations_done", "completed_trials", "best_score", "token_usage")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Refresh aggregate reports and publish the completed experiment's Skill."""

from pathlib import Path
import argparse
import json
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from faultevolve.delivery_report import package_skill
from faultevolve.reporting import export_workflow_reports
from faultevolve.research_campaign import snapshot_database, write_json


def main():
    parser = argparse.ArgumentParser(description="监测正式运行，持续导出报告并在完成后打包 Skill")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    output = Path(manifest["artifacts_dir"]) / manifest["run_id"]
    db = Path(manifest["runs_dir"]) / manifest["run_id"] / "fe.db"
    while True:
        state_path = output / "workflow.json"
        state = json.loads(state_path.read_text()) if state_path.is_file() else {}
        if db.is_file():
            report = export_workflow_reports(output, db, db.parent / "workflow/task")
            print(json.dumps({k: report[k] for k in ("run_id", "state", "iterations_done", "completed_trials", "best_score", "token_usage")}), flush=True)
        else:
            report = None
        if state.get("state") == "finished":
            if report is None:
                raise ValueError("运行完成但缺少评估数据库")
            skill = package_skill(report, REPO / "skill/fe-closed-loop-tuning", output)
            validation = subprocess.run([sys.executable,
                str(Path.home() / ".codex/skills/.system/skill-creator/scripts/quick_validate.py"), str(skill)],
                capture_output=True, text=True)
            if validation.returncode:
                raise ValueError("Skill 校验失败，不能发布完成状态")
            snapshot_database(db, db.parent / "delivery-snapshot.sqlite", output / "database/fe.db")
            write_json(output / "DELIVERY.json", {"state": "finished", "run_id": report["run_id"],
                "report": "reports/完整运行报告.md", "interactive_report": "reports/完整运行报告.html",
                "stage_metrics": "reports/stage-metrics.csv", "parameter_trials": "reports/parameter-trials.csv",
                "tokens": "reports/token-ledger.csv", "skill": "skill/fe-closed-loop-tuning/SKILL.md",
                "skill_zip": "fe-closed-loop-tuning.zip", "skill_validated": True,
                "best_score": report["best_score"], "updated_at": time.time()})
            print(json.dumps({"delivery_finished": True, "output": str(output)}), flush=True)
            return
        if state.get("state") in {"failed", "paused", "cancelled"}:
            print(json.dumps({"delivery_finished": False, "state": state.get("state"), "error_type": state.get("error_type")}), flush=True)
            raise SystemExit(1)
        time.sleep(45)


if __name__ == "__main__":
    main()

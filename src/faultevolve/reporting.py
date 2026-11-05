"""Read-only projections of completed search evidence into reports and Web artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from faultevolve.research_campaign import write_json


def export_workflow_reports(output: Path, db: Path, task: Path | None = None) -> dict:
    """Build reports without an evaluator, model generation, or score updates.

    Only report artifacts are written. A failure cannot change the experiment's
    completion state or its selected executable.
    """
    task = task or db.parent / "workflow/task"
    try:
        from faultevolve.delivery_report import write_delivery_report
        from faultevolve.effect_report import build_effect_report

        workflow_path = output / "workflow-result.json"
        if workflow_path.is_file():
            workflow = json.loads(workflow_path.read_text())
            summary = json.loads((output / "run_summary.json").read_text())
            ledger_path = output / "hyperparameters/ledger.json"
            ledger = json.loads(ledger_path.read_text()) if ledger_path.is_file() else None
            effective = db.parent / "workflow/effective_config.json"
            config = json.loads(effective.read_text()) if effective.is_file() else {}
            effect = build_effect_report(output, db, task, summary, ledger,
                workflow["best_origin"], workflow.get("best_node_id"),
                target_score=config.get("stop", {}).get("target_score"),
                hierarchical=config.get("workflow", {}).get("hierarchical", {}).get("enabled", True))
            effect["split"] = workflow.get("split", "val")
            write_json(output / "effect-report.json", effect)
        result = write_delivery_report(output, db, task)
        write_json(output / "report-status.json", {"state": "finished"})
        return result
    except Exception as exc:
        write_json(output / "report-status.json", {"state": "failed", "error_type": type(exc).__name__})
        raise

#!/usr/bin/env python
"""Produce the WebUI demo run with the *real* engine, fully offline.

Why this exists
---------------
The committed single-tree fixture (``hdd_mvp_showcase_c89e2a01``) used to be
produced one of two ways, and neither survives a judge asking "where does this
number come from?":

* the committed mock run (``hdd_mvp_demo_7510f100``): 6 nodes, every child worse
  than ``init``, ``improvement = 0`` -- the workbench's depth bands, edge legend
  and significance tiers render nothing on it;
* ``scripts/make_tree_showcase_fixture.py``: 21 nodes whose scores/deltas/edges
  were *hand-written in that script*, so its numbers trace back to a source file
  rather than to an evaluator.

This script produces the demo run the defensible way:

* it drives the real engine through its public entry point
  (``run_local_evolution(..., mock=True)``);
* candidates are real Python programs: they go through the real static check,
  precheck, performance gate, smoke test, and are scored by the real
  ``benchmark/hdd_mvp/evaluator.py`` on the real validation split -- so every
  ROS/F1/AUPRC number in the run is an evaluator number;
* only the **LLM** is mocked. That is the single fact a fixture produced here
  must disclose (``build_run_fixture.py`` copies it into the fixture README, and
  the run summary carries it) -- the dedicated showcase pages that once labelled
  it 演示数据 were removed in D6.5; the run is now replayed by the same generic
  pages as any other run.
* operator bandit + crossover are switched on through a **generated config
  file** (the engine's own ``config_path`` parameter), so the tree really does
  contain the operator mix and the crossover/repair edge shapes the workbench
  draws.

``benchmark/hdd_mvp`` is read-only input here: the demo config is written next to
the artifacts, never into the task directory.

Usage::

    .venv/Scripts/python.exe scripts/make_demo_run.py
    .venv/Scripts/python.exe scripts/make_demo_run.py --seed 7 --iterations 12
    .venv/Scripts/python.exe scripts/make_demo_run.py --check
    .venv/Scripts/python.exe scripts/make_demo_run.py --check --require crossover,repair
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
TASK_DIR = REPO / "benchmark" / "hdd_mvp"
BASE_CONFIG = TASK_DIR / "evolve.yaml"

#: Everything this script writes stays under ``build/`` (git-ignored).
OUT_ROOT = REPO / "build" / "demo_runs"

#: The experiment id of the demo run. Kept stable on purpose: the fixture
#: directory, ``demo_run_ids`` and the E2E specs all refer to the same run.
DEMO_EXPERIMENT_ID = "d3m0a1b2"
DEMO_RUN_DIR = OUT_ROOT / DEMO_EXPERIMENT_ID

DEFAULT_ITERATIONS = 12
DEFAULT_SEED = 7


def build_demo_config(
    *,
    iterations: int,
    seed: int,
) -> dict:
    """Base task config plus what the demo needs to show real shapes.

    Only three things are changed, and each is justified:

    * ``operators.bandit`` -- without it the engine always returns REFINE, so a
      demo can never show operator mix or the operator statistics panel;
    * ``operators.crossover.enabled`` -- requires the bandit (enforced by
      ``OperatorsConfig._crossover_requires_bandit``), gives the second-parent
      edge the tree legend is built around;
    * iterations/seed -- run length and reproducibility.

    Everything else (judge provider ``none``, error analysis off, discovery off)
    stays exactly as the task ships: an offline demo must not pretend to call
    Jev or to have run knowledge discovery.
    """
    base = yaml.safe_load(BASE_CONFIG.read_text(encoding="utf-8")) or {}

    base.setdefault("budget", {})
    base["budget"]["max_iterations"] = iterations

    operators = base.setdefault("operators", {})
    operators["bandit"] = True
    operators.setdefault(
        "enabled",
        ["refine", "recall_focus", "threshold_calibrate", "inject"],
    )
    operators["crossover"] = {
        "enabled": True,
        "min_valid_nodes": 4,
        "runtime_budget_s": 300.0,
        "top_quantile": 0.3,
        "max_code_chars": 6000,
    }

    base["seed"] = seed
    return base


def write_demo_config(config: dict, dst: Path) -> None:
    """Validate through pydantic before writing, so a bad demo fails loudly."""
    from faultevolve.config import EvolveConfig

    EvolveConfig.from_dict(config)  # raises on an invalid combination

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )


def generate(*, iterations: int, seed: int, keep_existing: bool) -> Path:
    """Run one offline evolution and return its (single, self-contained) dir."""
    if DEMO_RUN_DIR.exists():
        if keep_existing:
            print(f"keeping existing {DEMO_RUN_DIR}")
            return DEMO_RUN_DIR
        shutil.rmtree(DEMO_RUN_DIR)

    config_path = OUT_ROOT / f"evolve.demo.{DEMO_EXPERIMENT_ID}.yaml"
    write_demo_config(build_demo_config(iterations=iterations, seed=seed), config_path)

    from faultevolve.cloud.engine import run_local_evolution

    print(f"running engine: mock=True iterations={iterations} seed={seed}")
    result = run_local_evolution(
        task_dir=TASK_DIR,
        mock=True,
        max_iterations=iterations,
        seed=seed,
        # artifacts_dir left None on purpose: the engine then writes the DB and
        # the artifacts into one directory, which is the shape the replay layer
        # (and therefore the fixture) expects.
        runs_dir=OUT_ROOT,
        experiment_id=DEMO_EXPERIMENT_ID,
        config_path=config_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return DEMO_RUN_DIR


# ---------------------------------------------------------------------------
# shape report / gate
# ---------------------------------------------------------------------------

#: Always required: without these the run is not a usable demo at all.
CORE_REQUIREMENTS = ("finished", "nodes", "scored", "cards")

#: Only required when named explicitly via --require. MockLLM can legitimately
#: fail to produce some of these, and pretending otherwise is what this whole
#: script exists to stop.
OPTIONAL_REQUIREMENTS = ("depth", "operators", "invalid", "repair", "crossover")


def inspect(run_dir: Path) -> tuple[dict, list[str]]:
    """Return (shapes, problems) for one run directory."""
    problems: list[str] = []
    shapes: dict[str, object] = {}

    summary_path = run_dir / "run_summary.json"
    tree_path = run_dir / "tree.json"
    db_path = run_dir / "fe.db"
    for path in (summary_path, tree_path):
        if not path.is_file():
            problems.append(f"missing {path.name}")
    if problems:
        return shapes, problems

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    tree = json.loads(tree_path.read_text(encoding="utf-8"))
    nodes = tree.get("nodes", [])
    edges = tree.get("edges", [])

    # A node is "scored" when the engine recorded a numeric combined_score.
    # Reading them from tree.json keeps this script independent of the DB
    # schema, but the DB is what the crossover/repair evidence lives in.
    scored = [n for n in nodes if isinstance(n.get("score"), (int, float))]
    depths = sorted({n["depth"] for n in nodes if isinstance(n.get("depth"), int)})
    operators = summary.get("operator_counts") or {}
    by_id = {n["id"]: n for n in nodes}
    best_id = summary.get("best_node_id")

    shapes["run_id"] = run_dir.name
    shapes["status"] = summary.get("status")
    shapes["iterations_done"] = summary.get("iterations_done")
    shapes["nodes"] = len(nodes)
    shapes["edges"] = len(edges)
    shapes["scored_nodes"] = len(scored)
    shapes["depths"] = depths
    shapes["best_node_id"] = best_id
    shapes["best_score"] = summary.get("best_score")
    shapes["initial_score"] = summary.get("initial_score")
    shapes["improvement"] = summary.get("improvement")
    shapes["operator_counts"] = operators
    shapes["cards_offered"] = summary.get("cards_offered")
    shapes["cards_adopted"] = summary.get("cards_adopted")
    shapes["smoke_failures"] = summary.get("smoke_failures")
    shapes["repair_attempts"] = summary.get("repair_attempts")
    shapes["crossover_count"] = summary.get("crossover_count")
    shapes["total_tokens"] = summary.get("total_tokens")

    if summary.get("status") != "finished":
        problems.append(f"status is {summary.get('status')!r}, not 'finished'")
    if len(nodes) < 5:
        problems.append(f"only {len(nodes)} nodes; too thin to render the tree")
    if len(scored) != len(nodes):
        problems.append(
            f"{len(nodes) - len(scored)} node(s) carry no numeric score "
            "(the UI must show 未评分, which is correct -- but the demo wants evaluated nodes)"
        )
    if best_id not in by_id:
        problems.append(f"best_node_id {best_id!r} is not in the tree")
    elif isinstance(shapes["best_score"], (int, float)):
        best_score = by_id[best_id].get("score")
        if best_score is None or abs(float(best_score) - float(shapes["best_score"])) > 1e-9:
            problems.append(
                f"best_score {shapes['best_score']} != node {best_id} score {best_score}"
            )
    if not (summary.get("cards_offered") or 0) > 0:
        problems.append("no knowledge card was ever offered (knowledge injection looks off)")
    if not (summary.get("cards_adopted") or 0) > 0:
        problems.append("no knowledge card was adopted, so the card panels stay empty")

    # --- DB-only shapes: second parent (crossover) and the repair chain -------
    secondary = 0
    repair_children = 0
    repair_bookkeeping = 0
    if db_path.is_file():
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            db.row_factory = sqlite3.Row
            secondary = db.execute(
                "SELECT COUNT(*) FROM node_parents WHERE role='secondary'"
            ).fetchone()[0]
            repair_children = db.execute(
                "SELECT COUNT(*) FROM node WHERE repair_parent_id IS NOT NULL"
            ).fetchone()[0]
            repair_bookkeeping = db.execute(
                "SELECT COUNT(*) FROM node WHERE repair_attempted = 1"
            ).fetchone()[0]
        except sqlite3.Error as exc:  # pragma: no cover - schema drift
            problems.append(f"sqlite: {exc}")
        finally:
            db.close()
    else:
        problems.append("missing fe.db (crossover/repair evidence lives there)")

    shapes["secondary_parents"] = secondary
    shapes["repair_nodes"] = repair_children
    shapes["repair_attempted_nodes"] = repair_bookkeeping

    return shapes, problems


def requirement_state(shapes: dict) -> dict[str, bool]:
    """Map each requirement name to whether the run satisfies it."""
    depths = shapes.get("depths") or []
    operators = shapes.get("operator_counts") or {}
    smoke_failures = shapes.get("smoke_failures") or 0
    scored = shapes.get("scored_nodes") or 0
    nodes = shapes.get("nodes") or 0
    return {
        "finished": shapes.get("status") == "finished",
        "nodes": nodes >= 5,
        "scored": nodes > 0 and scored == nodes,
        "cards": (shapes.get("cards_adopted") or 0) > 0,
        "depth": len(depths) >= 3,
        "operators": len(operators) >= 2,
        "invalid": bool(smoke_failures) or scored < nodes,
        "repair": bool(shapes.get("repair_nodes")) or bool(shapes.get("repair_attempted_nodes")),
        "crossover": bool(shapes.get("crossover_count")) or bool(shapes.get("secondary_parents")),
    }


def check(run_dir: Path, required: list[str]) -> int:
    if not run_dir.is_dir():
        print(f"FAIL missing demo run: {run_dir}", file=sys.stderr)
        return 1

    shapes, problems = inspect(run_dir)
    state = requirement_state(shapes)

    print(json.dumps(shapes, ensure_ascii=False, indent=2, default=str))

    print("\nshapes present:")
    for name, ok in state.items():
        print(f"  {'OK  ' if ok else 'MISS'} {name}")

    failures = list(problems)
    for name in required:
        if name not in state:
            failures.append(f"unknown requirement {name!r}")
        elif not state[name]:
            failures.append(f"required shape missing: {name}")

    for line in failures:
        print(f"FAIL {line}", file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the demo run, do not create it")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="reuse an existing build/demo_runs/<id>/ instead of regenerating it",
    )
    parser.add_argument(
        "--require",
        default="",
        help=(
            "comma-separated extra shapes that must be present "
            f"(any of: {', '.join(CORE_REQUIREMENTS + OPTIONAL_REQUIREMENTS)})"
        ),
    )
    args = parser.parse_args()

    required = ["finished", "nodes", "scored", "cards"]
    for item in (part.strip() for part in args.require.split(",")):
        if item:
            required.append(item)

    run_dir = DEMO_RUN_DIR
    if not args.check:
        run_dir = generate(
            iterations=args.iterations,
            seed=args.seed,
            keep_existing=args.keep_existing,
        )

    return check(run_dir, required)


if __name__ == "__main__":
    raise SystemExit(main())

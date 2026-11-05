#!/usr/bin/env python
"""Generate the committed **three-island** replay fixture (TODO D6.4).

Why this exists
---------------
The island UI has to be built and verified against a run that really has three
trees, a summary channel and per-island cost. Two existing fixtures cannot do it:

* ``hdd_mvp_demo_7510f100`` predates the island engine -- 116 flat fields, no
  ``islands``/``exchange``/``cost`` block, so the replay layer correctly answers
  ``missing``;
* ``hdd_mvp_showcase_c89e2a01`` has hand-written nodes and scores (see
  ``scripts/make_web_showcase_fixture.py``), so its numbers trace back to a
  source file rather than to an evaluator. TODO D6.5 forbids putting that in
  front of a judge as a product result.

This script makes the missing fixture the defensible way, reusing the two
mechanisms the repo already trusts:

* the **real engine** through ``run_local_evolution(mock=True)`` on
  ``benchmark/hdd_mvp``: candidates go through the real static check and are
  scored by the real evaluator on the validation split, so every ROS/F1 number is
  an evaluator number. Only the LLM is mocked, and the fixture README says so;
* ``scripts/build_run_fixture.py`` for the redaction pass, so no host path or
  credential can be committed.

Nothing is hand-authored here: the tree, the summaries and the cost ledger are
what the engine wrote. The run length and ``exchange_interval`` are chosen so the
summary channel actually fires -- a fixture with an empty exchange layer would
verify nothing.

Usage::

    .venv/Scripts/python.exe scripts/make_island_demo_run.py            # generate + install
    .venv/Scripts/python.exe scripts/make_island_demo_run.py --seed 11 --iterations 20
    .venv/Scripts/python.exe scripts/make_island_demo_run.py --check    # verify the fixture
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO / "tests" / "fixtures" / "runs"

EXPERIMENT_ID = "15l4nd01"
RUN_ID = f"hdd_mvp_islands_{EXPERIMENT_ID}"

OUT_ROOT = REPO / "build" / "island_runs"
DEFAULT_ITERATIONS = 18
DEFAULT_SEED = 7
#: Measured, not guessed: interval 2 over 18 iterations published a single summary
#: (2 deliveries, 10 applications), which leaves the per-island knowledge panel
#: with one conclusion to draw. Interval 1 publishes enough summaries to exercise
#: every delivery/application branch. See the TODO doc, section C.
DEFAULT_EXCHANGE_INTERVAL = 1

#: The exchange layer only fires once an island has something worth reporting, so
#: a short run can legitimately produce zero summaries. These are the shapes the
#: fixture must carry for the island UI to have anything to draw.
REQUIRED_SHAPES = (
    "three islands",
    "islands block",
    "exchange summaries",
    "deliveries",
    "applications",
    "evaluated applications",
    "per-island cost",
    "attempt total",
    "cost balance",
)


def _load_sibling(name: str):
    path = REPO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_island_config(
    *, iterations: int, seed: int, exchange_interval: int = DEFAULT_EXCHANGE_INTERVAL
) -> dict[str, Any]:
    """The demo config from ``make_demo_run``, plus the island layer.

    Only ``islands`` is added; the operator mix (bandit + crossover) and the
    judge/discovery settings stay exactly as ``make_demo_run.py`` chooses them, so
    the two fixtures differ in one respect: this one runs three trees.

    ``exchange_interval`` comes from ``DEFAULT_EXCHANGE_INTERVAL``, which was
    picked by measuring how many summaries each value actually publishes for this
    run length rather than by reading the config comment.
    """
    demo = _load_sibling("make_demo_run")
    config = demo.build_demo_config(iterations=iterations, seed=seed)
    config["islands"] = {
        "enabled": True,
        "exchange_interval": exchange_interval,
    }
    return config


def generate(
    *, iterations: int, seed: int, exchange_interval: int, keep_existing: bool
) -> Path:
    """Run one offline three-island evolution and return its run directory."""
    if OUT_ROOT.exists():
        if not keep_existing:
            shutil.rmtree(OUT_ROOT)
    else:
        OUT_ROOT.mkdir(parents=True)

    run_dir = OUT_ROOT / EXPERIMENT_ID
    if run_dir.exists():
        if keep_existing:
            print(f"keeping existing {run_dir}")
            return run_dir
        shutil.rmtree(run_dir)

    config_path = OUT_ROOT / f"evolve.islands.{EXPERIMENT_ID}.yaml"
    demo = _load_sibling("make_demo_run")
    demo.write_demo_config(
        build_island_config(
            iterations=iterations, seed=seed, exchange_interval=exchange_interval
        ),
        config_path,
    )

    from faultevolve.cloud.engine import run_local_evolution

    print(
        f"running engine: mock=True islands=on iterations={iterations} "
        f"seed={seed} exchange_interval={exchange_interval}"
    )
    result = run_local_evolution(
        task_dir=demo.TASK_DIR,
        mock=True,
        max_iterations=iterations,
        seed=seed,
        # artifacts_dir left None: database and artifacts in one directory, the
        # shape a committed fixture is stored in.
        runs_dir=OUT_ROOT,
        experiment_id=EXPERIMENT_ID,
        config_path=config_path,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return run_dir


def install(run_dir: Path) -> Path:
    """Redact the engine's output into the committed fixture directory."""
    builder = _load_sibling("build_run_fixture")
    target = FIXTURE_ROOT / RUN_ID
    if target.exists():
        shutil.rmtree(target)
    if builder.build(run_dir, target):
        raise SystemExit("redaction refused this fixture -- nothing installed")
    return target


# --------------------------------------------------------------------------
# shape gate
# --------------------------------------------------------------------------


def inspect(run_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """Report the island shapes the UI needs, and every promise that is unmet."""
    problems: list[str] = []
    shapes: dict[str, Any] = {}

    summary_path = run_dir / "run_summary.json"
    db_path = run_dir / "fe.db"
    if not summary_path.is_file():
        return shapes, [f"missing {summary_path.name}"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    islands = summary.get("islands")
    exchange = summary.get("exchange") or {}
    cost = summary.get("cost") or {}
    shapes["status"] = summary.get("status")
    shapes["iterations_done"] = summary.get("iterations_done")

    if not isinstance(islands, dict) or not islands:
        problems.append("islands block")
        islands = {}
    else:
        shapes["islands"] = sorted(islands)
        if len(islands) < 3:
            problems.append("three islands")

    if sum(int(row.get("attempts") or 0) for row in islands.values()) != summary.get(
        "iterations_done"
    ):
        problems.append("attempt total")
    shapes["exchange"] = {
        key: exchange.get(key)
        for key in ("summaries", "deliveries", "accepted", "rejected",
                    "applications", "evaluated_applications")
    }
    for key, shape in (
        ("summaries", "exchange summaries"),
        ("deliveries", "deliveries"),
        ("applications", "applications"),
        ("evaluated_applications", "evaluated applications"),
    ):
        if not exchange.get(key):
            problems.append(shape)

    by_island = cost.get("by_island") or {}
    if not by_island:
        problems.append("per-island cost")
    else:
        shapes["cost_islands"] = sorted(by_island)
        tokens = sum(int(row.get("tokens") or 0) for row in by_island.values())
        if tokens + int(cost.get("shared_tokens") or 0) != int(cost.get("total_tokens") or 0):
            problems.append("cost balance")

    # The node table is the ground truth for "three trees really exist".
    if db_path.is_file():
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            per_island = dict(
                conn.execute("SELECT island_id, COUNT(*) FROM node GROUP BY island_id")
            )
            shapes["nodes_per_island"] = per_island
            if len([k for k in per_island if k]) < 3:
                problems.append("three islands")
            shapes["summary_rows"] = conn.execute(
                "SELECT COUNT(*) FROM exchange_summary"
            ).fetchone()[0]
            shapes["summary_kinds"] = dict(
                conn.execute("SELECT kind, COUNT(*) FROM exchange_summary GROUP BY kind")
            )
            shapes["summary_sources"] = dict(
                conn.execute(
                    "SELECT source_island_id, COUNT(*) FROM exchange_summary GROUP BY "
                    "source_island_id"
                )
            )
            shapes["application_rows"] = conn.execute(
                "SELECT COUNT(*) FROM summary_application"
            ).fetchone()[0]
            shapes["graft_node_rows"] = conn.execute(
                "SELECT COUNT(*) FROM node WHERE operator = ?", ("summary_cross",)
            ).fetchone()[0]
        finally:
            conn.close()
    return shapes, problems


def check(run_dir: Path) -> int:
    shapes, problems = inspect(run_dir)
    print(json.dumps(shapes, ensure_ascii=False, indent=2))
    if problems:
        for problem in problems:
            print(f"FAIL {problem}", file=sys.stderr)
        return 1
    print(f"OK {run_dir.name} carries: {', '.join(REQUIRED_SHAPES)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--exchange-interval", type=int, default=DEFAULT_EXCHANGE_INTERVAL
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="reuse the engine output in build/ instead of running again",
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="generate and inspect only; leave the committed fixture untouched",
    )
    args = parser.parse_args()

    target = FIXTURE_ROOT / RUN_ID
    if args.check:
        if not target.is_dir():
            print(f"FAIL missing fixture: {target}", file=sys.stderr)
            return 1
        return check(target)

    run_dir = generate(
        iterations=args.iterations,
        seed=args.seed,
        exchange_interval=args.exchange_interval,
        keep_existing=args.keep_existing,
    )
    shapes, problems = inspect(run_dir)
    print(json.dumps(shapes, ensure_ascii=False, indent=2))
    if problems:
        for problem in problems:
            print(f"MISSING {problem}", file=sys.stderr)
        print("not installed: the run does not carry what the island UI needs",
              file=sys.stderr)
        return 1
    if args.no_install:
        print(f"--no-install: leaving {target} untouched")
        return 0
    installed = install(run_dir)
    return check(installed)


if __name__ == "__main__":
    raise SystemExit(main())

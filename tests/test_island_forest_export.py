"""S6/D6.1: a live three-island run writes the whole forest, not its first tree.

``tree.json`` and ``programs/`` are what the web API replays, so an export that
covered only ``engine.tree`` -- one island's handle -- made a three-island run
arrive in the UI as a single island with a third of its nodes. The export now
reads the store per island, which is also what ``rebuild_run_report()`` does, so
the two paths cannot disagree.

The runs here are the CLI's own, on the toy task, with ``--mock``: no evaluator,
no LLM cost, nothing from the benchmark.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from faultevolve.cli import app
from faultevolve.cloud.engine import rebuild_run_report
from faultevolve.cloud.store import Store

REPO = Path(__file__).resolve().parents[1]
TOY_TASK = REPO / "tests" / "fixtures" / "toy_task"

ISLANDS_CONFIG: dict[str, Any] = {
    "task": {"adapter": "famou"},
    "budget": {"max_iterations": 6},
    "islands": {"enabled": True, "exchange_interval": 1},
}


def _evolve(tmp: Path, config: dict[str, Any] | None, iterations: int) -> dict[str, Any]:
    """Run ``fe evolve local --mock`` and point at the run it wrote."""
    runs, artifacts = tmp / "runs", tmp / "artifacts"
    argv = ["evolve", "local", str(TOY_TASK), "--mock", "-n", str(iterations)]
    if config is not None:
        file = tmp / "config.yaml"
        file.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        argv += ["--config-file", str(file)]
    argv += ["--runs-dir", str(runs), "--artifacts-dir", str(artifacts), "--json"]
    result = CliRunner().invoke(app, argv)
    assert result.exit_code == 0, result.output + getattr(result, "stderr", "")
    run_id = json.loads(result.output[result.output.index("{"):])["experiment_id"]
    art_dir = artifacts / run_id
    return {
        "run_id": run_id,
        "art_dir": art_dir,
        "db_path": runs / run_id / "fe.db",
        "tree": json.loads((art_dir / "tree.json").read_text(encoding="utf-8")),
    }


def _db_nodes(db_path: Path, experiment_id: str) -> dict[str, str]:
    """node id -> island id, straight from the run's own database."""
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        return dict(
            connection.execute(
                "SELECT id, island_id FROM node WHERE experiment_id = ?", (experiment_id,)
            )
        )
    finally:
        connection.close()


def _shape(tree: dict[str, Any]) -> list[tuple[str, str, int]]:
    return sorted(
        (str(node["id"]), str(node.get("island_id")), int(node["depth"]))
        for node in tree["nodes"]
    )


@pytest.fixture(scope="module")
def island_run(tmp_path_factory) -> dict[str, Any]:
    return _evolve(tmp_path_factory.mktemp("forest"), ISLANDS_CONFIG, 6)


# ------------------------------------------------------------------- the live export


def test_the_live_export_carries_every_islands_nodes(island_run) -> None:
    tree = island_run["tree"]
    assert {node["id"] for node in tree["nodes"]} == set(
        _db_nodes(island_run["db_path"], island_run["run_id"])
    )
    assert sorted({node["island_id"] for node in tree["nodes"]}) == ["a", "b", "c"]
    roots = [node for node in tree["nodes"] if node["depth"] == 0]
    assert len(roots) == 3, "one root per island, so three trees and never one chain"
    assert {node["island_id"] for node in roots} == {"a", "b", "c"}


def test_the_live_export_carries_every_islands_programs(island_run) -> None:
    programs = {p.stem for p in (island_run["art_dir"] / "programs").glob("*.py")}
    assert programs == set(_db_nodes(island_run["db_path"], island_run["run_id"]))


def test_no_edge_crosses_islands(island_run) -> None:
    """Tree edges are intra-island; a cross-island link is a summary, not a parent."""
    island_of = {node["id"]: node["island_id"] for node in island_run["tree"]["nodes"]}
    for edge in island_run["tree"]["edges"]:
        assert island_of[edge["source"]] == island_of[edge["target"]], edge


# ----------------------------------------------------- live and rebuilt are one story


def test_a_rebuild_exports_the_same_forest_as_the_live_run(island_run) -> None:
    out = island_run["art_dir"].parent.parent / "rebuilt"
    rebuild_run_report(Store(island_run["db_path"], read_only=True), island_run["run_id"], out)
    rebuilt = json.loads((out / "tree.json").read_text(encoding="utf-8"))
    assert _shape(rebuilt) == _shape(island_run["tree"])
    assert sorted((e["source"], e["target"]) for e in rebuilt["edges"]) == sorted(
        (e["source"], e["target"]) for e in island_run["tree"]["edges"]
    )


# ------------------------------------------------------------------- the legacy shape


def test_a_run_without_an_islands_config_file_still_exports_its_forest(tmp_path) -> None:
    """No ``--config-file`` is not one tree any more: the default ring must be whole.

    Measured, not assumed -- a default mock run starts a three-island ring, so the
    export has to cover every island's nodes here too.
    """
    run = _evolve(tmp_path, None, 3)
    recorded = _db_nodes(run["db_path"], run["run_id"])
    assert {node["id"] for node in run["tree"]["nodes"]} == set(recorded)
    assert {node.get("island_id") for node in run["tree"]["nodes"]} == set(recorded.values())
    assert list((run["art_dir"] / "programs").glob("*.py"))

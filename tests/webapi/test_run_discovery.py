"""Run discovery over real server layouts, with a provenance manifest (TODO D6.1/D6.2).

Three facts drive every test here, and each was measured rather than assumed:

* a run may sit any number of levels below its root (a NAS nests runs under a
  date and a batch folder);
* ``fe evolve --runs-dir A --artifacts-dir B`` writes ``fe.db`` into ``A`` and
  every report artifact into ``B``, so one run has two homes;
* whether a run is real cannot be read off its name, so the server reports the
  evidence it holds and says *unverified* when it has none.

The committed fixture is the payload: copying it around reproduces a complete run
directory, and moving its ``fe.db`` out reproduces the split layout.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from faultevolve.webapi import run_discovery  # noqa: E402
from faultevolve.webapi.app import create_app  # noqa: E402
from faultevolve.webapi.run_registry import (  # noqa: E402
    STATUS_COMPLETED,
    RunRecord,
    insert_record,
)
from faultevolve.webapi.settings import WebSettings  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "runs" / "hdd_mvp_demo_7510f100"
RUN_ID = "hdd_mvp_demo_7510f100"
INIT_NODE_ID = "62d6cf09"
BEST_SCORE = 22.807355886970594

#: What the fixture's tree holds, used to prove the *artifacts* half was read.
FIXTURE_NODE_COUNT = 6


def _copy_run(target: Path, *, best_score: float | None = None) -> Path:
    """A full copy of the committed fixture, optionally with a different score.

    ``best_score`` is rewritten so two copies of the same run id are tellable
    apart in a reply -- the point of the duplicate-id tests.
    """
    shutil.copytree(FIXTURE_DIR, target)
    if best_score is not None:
        summary_path = target / "run_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["best_score"] = best_score
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False), encoding="utf-8"
        )
    return target


def _settings(*roots: Path, **extra) -> WebSettings:
    """Settings that accept every root given, so the scan may enter all of them."""
    return WebSettings(
        runs_root=roots[0] if roots else None,
        artifacts_root=roots[1] if len(roots) > 1 else None,
        allowed_path_roots=[root for root in roots],
        **extra,
    )


def _client(settings: WebSettings) -> TestClient:
    return TestClient(create_app(settings), raise_server_exceptions=False)


# --------------------------------------------------------------------------
# D6.1: multi-level layouts
# --------------------------------------------------------------------------


def test_a_run_nested_under_date_and_batch_folders_is_found(tmp_path: Path) -> None:
    """The NAS layout a real server uses is listed *and* readable.

    The first version of this layer only looked at direct children, so a run at
    ``2026-10/batch-3/<id>/`` could appear nowhere -- or, worse, be named by a
    link that then 404'd. Both halves have to resolve from one scan.
    """
    root = tmp_path / "vol" / "evolve"
    nested = root / "2026-10" / "batch-3" / RUN_ID
    _copy_run(nested)
    client = _client(_settings(root))

    rows = client.get("/api/runs").json()
    assert [row["run_id"] for row in rows] == [RUN_ID]
    assert rows[0]["data_state"] == "complete"
    detail = client.get(f"/api/runs/{RUN_ID}").json()
    assert detail["outcome"]["best_score"] == pytest.approx(BEST_SCORE)
    tree = client.get(f"/api/runs/{RUN_ID}/tree").json()
    assert len(tree["nodes"]) == FIXTURE_NODE_COUNT


def test_the_depth_limit_is_a_real_limit(tmp_path: Path) -> None:
    """Beyond ``discovery_max_depth`` a run is not scanned -- and says nothing.

    The bound is what keeps list latency off the whole volume, so it has to
    actually stop the walk instead of being a documented suggestion.
    """
    root = tmp_path / "vol"
    _copy_run(root / "a" / "b" / "c" / RUN_ID)

    shallow = _client(_settings(root, discovery_max_depth=2))
    assert shallow.get("/api/runs").json() == []

    deep = _client(_settings(root, discovery_max_depth=4))
    assert [row["run_id"] for row in deep.get("/api/runs").json()] == [RUN_ID]


def test_a_directory_holding_no_run_artifact_is_not_a_run(tmp_path: Path) -> None:
    """Depth no longer decides; the files do.

    A data folder one level under the root used to be listed as a run purely
    because it was a directory with an id-shaped name.
    """
    root = tmp_path / "vol"
    (root / "smartSMART_data").mkdir(parents=True)
    (root / "smartSMART_data" / "raw_rows.csv").write_text("a,b\n", encoding="utf-8")
    _copy_run(root / RUN_ID)

    rows = _client(_settings(root)).get("/api/runs").json()
    assert [row["run_id"] for row in rows] == [RUN_ID]


# --------------------------------------------------------------------------
# D6.1: a run with two homes
# --------------------------------------------------------------------------


def test_split_run_and_artifact_roots_read_as_one_run(tmp_path: Path) -> None:
    """``fe.db`` under one root and reports under the other: one row, both readable.

    Each assertion names which half it proves -- the tree comes from the
    artifacts root, the evaluation numbers from the database root.
    """
    db_root = tmp_path / "runs"
    art_root = tmp_path / "artifacts"
    _copy_run(art_root / RUN_ID)
    (db_root / RUN_ID).mkdir(parents=True)
    shutil.move(
        str(art_root / RUN_ID / "fe.db"), str(db_root / RUN_ID / "fe.db")
    )
    client = _client(_settings(db_root, art_root))

    rows = client.get("/api/runs").json()
    assert [row["run_id"] for row in rows] == [RUN_ID], "the halves are one run"
    assert rows[0]["run_type"] == "evolve"

    detail = client.get(f"/api/runs/{RUN_ID}").json()
    assert detail["artifact_states"]["run_summary"] == "available"
    assert detail["artifact_states"]["database"] == "available"
    tree = client.get(f"/api/runs/{RUN_ID}/tree").json()
    assert len(tree["nodes"]) == FIXTURE_NODE_COUNT
    node = client.get(f"/api/runs/{RUN_ID}/nodes/{INIT_NODE_ID}").json()
    assert node["evaluation"]["combined_score"] == pytest.approx(BEST_SCORE)


def test_two_complete_copies_of_a_run_id_are_not_merged(tmp_path: Path) -> None:
    """Pairing is for complementary halves only.

    Two directories that each hold a whole run are two runs. Picking one would
    show one run's score under the other's name, which is the failure mode the
    TODO calls out as 不能列表显示出来但详情找错位置.
    """
    left = tmp_path / "mirror-a"
    right = tmp_path / "mirror-b"
    _copy_run(left / RUN_ID, best_score=11.0)
    _copy_run(right / RUN_ID, best_score=99.0)
    client = _client(_settings(left, right))

    rows = client.get("/api/runs").json()
    assert len(rows) == 2
    ids = {row["external_id"] for row in rows}
    assert len(ids) == 2, "both stay addressable"
    assert RUN_ID in ids, "the first occurrence keeps the bare id"
    scores = sorted(row["best_score"] for row in rows)
    assert scores == [11.0, 99.0], "neither copy overwrites the other"


def test_the_bare_id_names_the_first_hit_and_the_suffix_the_second(
    tmp_path: Path,
) -> None:
    """Which copy the bare id means must be deterministic, not whichever won a race."""
    left = tmp_path / "mirror-a"
    right = tmp_path / "mirror-b"
    _copy_run(left / RUN_ID, best_score=11.0)
    _copy_run(right / RUN_ID, best_score=99.0)
    client = _client(_settings(left, right))

    rows = client.get("/api/runs").json()
    suffixed = next(row["external_id"] for row in rows if row["external_id"] != RUN_ID)

    assert client.get(f"/api/runs/{RUN_ID}").json()["outcome"]["best_score"] == 11.0
    assert client.get(f"/api/runs/{suffixed}").json()["outcome"]["best_score"] == 99.0
    manifest = client.get("/api/runs/provenance").json()
    assert [entry["external_id"] for entry in manifest["runs"]] == [RUN_ID, suffixed]


# --------------------------------------------------------------------------
# D6.1: a run shape that has no tree
# --------------------------------------------------------------------------


def test_a_database_only_run_is_listed_and_admits_it_has_no_tree(
    tmp_path: Path,
) -> None:
    """No tree.json means no tree, reported -- never an invented one.

    A run directory holding only ``fe.db`` is a real finding: it is the mid-flight
    or artifacts-not-yet-copied case. It must still be listed with its state, and
    the tree endpoint must return an empty tree that explains itself.
    """
    root = tmp_path / "runs"
    (root / RUN_ID).mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "fe.db", root / RUN_ID / "fe.db")
    client = _client(_settings(root))

    rows = client.get("/api/runs").json()
    assert [row["run_type"] for row in rows] == ["database"]
    assert rows[0]["data_state"] == "live"

    detail = client.get(f"/api/runs/{RUN_ID}").json()
    assert detail["artifact_states"]["tree"] == "missing"
    assert detail["outcome"] is None

    tree = client.get(f"/api/runs/{RUN_ID}/tree").json()
    assert tree["nodes"] == []
    assert tree["best_node_id"] is None
    assert any(warning["field"] == "tree" for warning in tree["warnings"])


# --------------------------------------------------------------------------
# D6.2: origin, fixtures, and the reconciling counts
# --------------------------------------------------------------------------


def test_a_fixture_root_leaves_the_product_listing(tmp_path: Path) -> None:
    """Fixture data is excluded by configuration, not by name.

    Two halves to this: a run *named* like a demonstration but sitting in the
    normal roots stays listed, because a name is not evidence; and a run with an
    unremarkable name that sits under a configured fixture root is excluded,
    because the location is.
    """
    root = tmp_path / "vol"
    _copy_run(root / "runs" / RUN_ID)
    unremarkable = "hdd_mvp_nightly_9f2c31"
    _copy_run(root / "fixtures" / unremarkable, best_score=42.0)
    _copy_run(root / "runs" / "looks_like_a_fixture", best_score=7.0)
    settings = _settings(root, fixture_roots=[root / "fixtures"])
    client = _client(settings)

    rows = client.get("/api/runs").json()
    assert sorted(row["run_id"] for row in rows) == sorted(
        [RUN_ID, "looks_like_a_fixture"]
    )
    manifest = client.get("/api/runs/provenance").json()
    assert manifest["excluded_fixtures"] == 1
    assert manifest["listed"] == 2
    origins = {entry["run_id"]: entry["origin"] for entry in manifest["runs"]}
    assert origins[unremarkable] == "fixture"
    assert origins["looks_like_a_fixture"] == "unverified"
    # A bookmarked demo link keeps working even though the row is not listed.
    assert client.get(f"/api/runs/{unremarkable}").status_code == 200


def test_a_run_this_service_started_is_reported_real(tmp_path: Path) -> None:
    """The registry row is the evidence; without it the honest answer is unverified."""
    root = tmp_path / "runs"
    _copy_run(root / "started-by-me")
    _copy_run(root / "copied-in-by-hand")
    settings = _settings(root, run_registry=tmp_path / "registry.db")
    insert_record(
        settings,
        RunRecord(
            run_id="started-by-me",
            execution_backend="local_process",
            server_profile_id=None,
            pid=4242,
            status=STATUS_COMPLETED,
            task_dir="benchmark/hdd_mvp",
            db_dir=str(root / "started-by-me"),
            artifacts_dir=str(root / "started-by-me"),
            log_dir=None,
        ),
    )

    origins = {
        entry["run_id"]: entry["origin"]
        for entry in _client(settings).get("/api/runs/provenance").json()["runs"]
    }
    assert origins["started-by-me"] == "real"
    # Nothing else on the volume can prove a run really ran, so it is not claimed.
    assert origins["copied-in-by-hand"] == "unverified"


def test_the_provenance_counts_reconcile(tmp_path: Path) -> None:
    """scanned = runs + paired, and runs = listed + fixtures.

    The identity is the whole point of the manifest: a run that disappeared
    between walking the volume and building the listing would break it.
    """
    db_root = tmp_path / "runs"
    art_root = tmp_path / "artifacts"
    _copy_run(art_root / RUN_ID)
    (db_root / RUN_ID).mkdir(parents=True)
    shutil.move(str(art_root / RUN_ID / "fe.db"), str(db_root / RUN_ID / "fe.db"))
    _copy_run(db_root / "whole")
    fixture_id = "hdd_mvp_fixture_111111"
    _copy_run(db_root / "fixtures" / fixture_id)

    settings = _settings(db_root, art_root, fixture_roots=[db_root / "fixtures"])
    manifest = _client(settings).get("/api/runs/provenance").json()

    assert manifest["scanned"] == len(manifest["runs"]) + manifest["paired"]
    assert manifest["paired"] == 1
    assert len(manifest["runs"]) == manifest["listed"] + manifest["excluded_fixtures"]
    assert manifest["listed"] == 2
    assert manifest["unverified"] == 2


def test_the_provenance_manifest_carries_no_host_path(tmp_path: Path) -> None:
    """Relative paths only: a listing is not a map of the server's filesystem."""
    root = tmp_path / "vol"
    _copy_run(root / "2026-10" / RUN_ID)
    body = _client(_settings(root)).get("/api/runs/provenance").text

    assert str(tmp_path) not in body
    # A host path would show up as a drive prefix or a separator; JSON's own
    # colons are field separators, not evidence.
    for marker in ("\\", "holdout", f"{root.drive}/", f"{root.drive}\\"):
        assert marker not in body


# --------------------------------------------------------------------------
# D6.2: scan errors are data, not a 500 and not silence
# --------------------------------------------------------------------------


def test_an_unreadable_part_of_the_volume_is_reported_and_the_rest_still_lists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hitting the visit ceiling stops the crawl and says so in the manifest."""
    root = tmp_path / "vol"
    _copy_run(root / RUN_ID)
    monkeypatch.setattr(run_discovery, "MAX_VISITS", 1)

    manifest = _client(_settings(root)).get("/api/runs/provenance").json()
    assert manifest["errors"], "the ceiling has to be visible"
    assert any("visit ceiling" in error["reason"] for error in manifest["errors"])
    assert manifest["errors_truncated"] is False


def test_the_error_manifest_caps_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root full of things the server may not read cannot flood the reply.

    The cap is reported as ``errors_truncated`` rather than silently dropping
    entries, so an operator knows the manifest is partial.
    """
    root = tmp_path / "vol"
    for name in ("first", "second", "third"):
        (root / name).mkdir(parents=True)
    monkeypatch.setattr(
        Path, "is_symlink", lambda self: self.parent == root, raising=True
    )
    monkeypatch.setattr(run_discovery, "MAX_ERRORS", 2)

    manifest = _client(_settings(root)).get("/api/runs/provenance").json()
    assert len(manifest["errors"]) == 2
    assert manifest["errors_truncated"] is True


def test_a_symbolic_link_is_recorded_and_never_descended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A link that points back into the volume would otherwise never finish.

    This Windows setup cannot create a directory symlink without extra
    privileges, so the scan is driven at the seam it actually uses -- the
    ``is_symlink`` answer on an entry it can see.
    """
    root = tmp_path / "vol"
    _copy_run(root / "linked" / RUN_ID)
    _copy_run(root / RUN_ID)
    monkeypatch.setattr(
        Path, "is_symlink", lambda self: self.name == "linked", raising=True
    )
    client = _client(_settings(root))

    rows = client.get("/api/runs").json()
    assert [row["run_id"] for row in rows] == [RUN_ID], "nothing behind the link"
    manifest = client.get("/api/runs/provenance").json()
    assert manifest["errors"] == [
        {"relative_path": "linked", "reason": "symbolic link skipped"}
    ]

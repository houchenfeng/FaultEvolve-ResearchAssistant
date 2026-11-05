"""树的三种边与噪声带分类（TODO 5.1 / 5.4）。

真实 demo 运行里 crossover 与 repair 一次都没发生过（实测 ``node_parents``
0 行），所以这些用例**在合成的数据库上**验证：把 fixture 复制到 tmp_path，
再按引擎真实的写法插入 ``node_parents`` 行与 ``repair_parent_id``。

引擎侧的对照事实：``cloud/engine.py`` 在 crossover 时调用
``store.add_node_parent(..., "primary")`` 与 ``(..., "secondary")``，
repair 节点把失败节点写进 ``node.repair_parent_id``。这里照抄那两种写法。
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from faultevolve.webapi.app import create_app
from faultevolve.webapi.replay_service import _within_noise


def _node_ids(run_dir: Path) -> list[str]:
    payload = json.loads((run_dir / "tree.json").read_text(encoding="utf-8"))
    return [str(node["id"]) for node in payload["nodes"]]


@contextmanager
def _db(run_dir: Path) -> Iterator[sqlite3.Connection]:
    """A writable connection that really closes.

    ``with sqlite3.connect(...)`` only ends the transaction; the file handle
    stays open, and Windows then refuses to let a later test delete ``fe.db``.
    Commit on success, roll back on error, always close.
    """
    conn = sqlite3.connect(run_dir / "fe.db")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _tree_of(settings, run_id: str) -> dict:
    return TestClient(create_app(settings)).get(f"/api/runs/{run_id}/tree").json()


def _kinds(body: dict) -> set[str]:
    return {edge["kind"] for edge in body["edges"]}


def test_the_real_run_has_only_plain_parent_edges(client: TestClient, run_id: str) -> None:
    """Baseline: with an empty ``node_parents`` the answer is "no crossover".

    This is the honest state of every run committed so far, and the UI has to
    render it without inventing a second parent.
    """
    body = _tree_of(client.app.state.settings, run_id)
    assert body["edges"], "the fixture run does have a tree"
    assert _kinds(body) == {"parent"}
    assert all(node["second_parent_ids"] == [] for node in body["nodes"])


def test_second_parent_becomes_a_crossover_edge(mutable_run) -> None:
    """``role='secondary'`` is what makes an edge a crossover edge."""
    settings, run_id, run_dir = mutable_run
    parent_a, parent_b, child = _node_ids(run_dir)[:3]
    experiment_id = json.loads(
        (run_dir / "run_summary.json").read_text(encoding="utf-8")
    ).get("experiment_id", "")

    with _db(run_dir) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO node_parents"
            " (experiment_id, node_id, parent_id, role) VALUES (?, ?, ?, ?)",
            (experiment_id, child, parent_a, "primary"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO node_parents"
            " (experiment_id, node_id, parent_id, role) VALUES (?, ?, ?, ?)",
            (experiment_id, child, parent_b, "secondary"),
        )

    body = _tree_of(settings, run_id)
    node = next(item for item in body["nodes"] if item["id"] == child)
    assert node["second_parent_ids"] == [parent_b]
    assert "crossover_second_parent" in _kinds(body)
    assert {
        "source": parent_b,
        "target": child,
        "kind": "crossover_second_parent",
    } in body["edges"]


def test_primary_role_alone_does_not_create_a_second_parent(mutable_run) -> None:
    """Only ``secondary`` counts; ``primary`` is already ``parent_id``."""
    settings, run_id, run_dir = mutable_run
    parent_a, _parent_b, child = _node_ids(run_dir)[:3]
    experiment_id = json.loads(
        (run_dir / "run_summary.json").read_text(encoding="utf-8")
    ).get("experiment_id", "")

    with _db(run_dir) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO node_parents"
            " (experiment_id, node_id, parent_id, role) VALUES (?, ?, ?, ?)",
            (experiment_id, child, parent_a, "primary"),
        )

    body = _tree_of(settings, run_id)
    node = next(item for item in body["nodes"] if item["id"] == child)
    assert node["second_parent_ids"] == []
    assert "crossover_second_parent" not in _kinds(body)


def test_repair_parent_becomes_a_repair_edge(mutable_run) -> None:
    """A repair child is linked to the node it repairs, with its own line kind."""
    settings, run_id, run_dir = mutable_run
    failed, repairer = _node_ids(run_dir)[1], _node_ids(run_dir)[2]

    with _db(run_dir) as conn:
        conn.execute(
            "UPDATE node SET repair_parent_id = ? WHERE id = ?", (failed, repairer)
        )

    body = _tree_of(settings, run_id)
    node = next(item for item in body["nodes"] if item["id"] == repairer)
    assert node["repair_parent_id"] == failed
    assert "repair" in _kinds(body)
    assert {
        "source": failed,
        "target": repairer,
        "kind": "repair",
    } in body["edges"]


def test_the_three_kinds_can_coexist_without_duplicates(mutable_run) -> None:
    """All three kinds at once, and no edge emitted twice.

    The relationship that appears twice is ``init -> child``: ``tree.json``
    already lists it as a plain parent edge, and the engine's ``secondary`` row
    says the child also came from a crossover with that same node. Both facts
    are true, so both edges are kept -- one per kind.
    """
    settings, run_id, run_dir = mutable_run
    init, child, repairer, repaired = _node_ids(run_dir)[:4]
    experiment_id = json.loads(
        (run_dir / "run_summary.json").read_text(encoding="utf-8")
    ).get("experiment_id", "")

    with _db(run_dir) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO node_parents"
            " (experiment_id, node_id, parent_id, role) VALUES (?, ?, ?, ?)",
            (experiment_id, child, init, "secondary"),
        )
        conn.execute(
            "UPDATE node SET repair_parent_id = ? WHERE id = ?", (repaired, repairer)
        )

    body = _tree_of(settings, run_id)
    assert _kinds(body) == {"parent", "crossover_second_parent", "repair"}

    keys = [(edge["source"], edge["target"], edge["kind"]) for edge in body["edges"]]
    assert len(keys) == len(set(keys)), "an edge must not be emitted twice"

    # init -> child is both the plain tree edge and the crossover fact.
    both = [key for key in keys if key[0] == init and key[1] == child]
    assert {key[2] for key in both} == {"parent", "crossover_second_parent"}
    assert {"source": repaired, "target": repairer, "kind": "repair"} in body["edges"]


def test_a_second_parent_outside_the_node_list_warns_instead_of_vanishing(
    mutable_run,
) -> None:
    """A dangling parent is reported; the node itself is still returned."""
    settings, run_id, run_dir = mutable_run
    child = _node_ids(run_dir)[2]
    experiment_id = json.loads(
        (run_dir / "run_summary.json").read_text(encoding="utf-8")
    ).get("experiment_id", "")

    with _db(run_dir) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO node_parents"
            " (experiment_id, node_id, parent_id, role) VALUES (?, ?, ?, ?)",
            (experiment_id, child, "deadbeef", "secondary"),
        )

    body = _tree_of(settings, run_id)
    assert any(node["id"] == child for node in body["nodes"]), "node still listed"
    assert body["warnings"], "a dangling parent must produce a warning"
    assert any("deadbeef" in warning["reason"] for warning in body["warnings"])


def test_a_missing_database_yields_no_crossover_claims(mutable_run) -> None:
    """Losing fe.db means "unknown", and unknown must not become an edge."""
    settings, run_id, run_dir = mutable_run
    child = _node_ids(run_dir)[2]
    experiment_id = json.loads(
        (run_dir / "run_summary.json").read_text(encoding="utf-8")
    ).get("experiment_id", "")
    with _db(run_dir) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO node_parents"
            " (experiment_id, node_id, parent_id, role) VALUES (?, ?, ?, ?)",
            (experiment_id, child, _node_ids(run_dir)[1], "secondary"),
        )
    (run_dir / "fe.db").unlink()

    body = _tree_of(settings, run_id)
    assert all(node["second_parent_ids"] == [] for node in body["nodes"])
    assert "crossover_second_parent" not in _kinds(body)


# --------------------------------------------------------------------------
# within_noise_band (TODO 5.4)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("delta", "noise", "expected"),
    [
        (0.5, 1.0, True),
        (-0.5, 1.0, True),
        (2.0, 1.0, False),
        (-2.0, 1.0, False),
        # Exactly on the boundary counts as inside: an improvement that merely
        # ties the noise is not evidence of progress.
        (1.0, 1.0, True),
        (None, 1.0, None),
        (1.0, None, None),
        (None, None, None),
        (0.0, 1.0, True),
    ],
)
def test_within_noise_is_three_valued(
    delta: float | None, noise: float | None, expected: bool | None
) -> None:
    assert _within_noise(delta, noise) is expected


def test_zero_delta_is_inside_the_band_not_missing() -> None:
    """``0.0`` is a measurement; only ``None`` is ignorance."""
    assert _within_noise(0.0, 0.0) is True
    assert _within_noise(0.0, None) is None


def test_node_and_score_point_agree_on_the_noise_band(mutable_run) -> None:
    """The two places that show the band must use one function.

    The node drawer and the score timeline both render it; if they computed it
    separately they would eventually disagree, and the user would see a node
    called "有效改进" sitting inside the band on the chart.
    """
    settings, run_id, run_dir = mutable_run
    target = next(
        node
        for node in json.loads((run_dir / "tree.json").read_text(encoding="utf-8"))["nodes"]
        if node["operator"] == "refine"
    )
    with _db(run_dir) as conn:
        conn.execute(
            "UPDATE node SET evidence_json = ? WHERE id = ?",
            (json.dumps({"delta_score": 0.4, "noise_delta": 1.0}), target["id"]),
        )

    client = TestClient(create_app(settings))
    tree_body = client.get(f"/api/runs/{run_id}/tree").json()
    scores = client.get(f"/api/runs/{run_id}/scores").json()

    node_band = next(n for n in tree_body["nodes"] if n["id"] == target["id"])[
        "within_noise_band"
    ]
    point_band = next(p for p in scores if p["node_id"] == target["id"])[
        "within_noise_band"
    ]
    assert node_band is True
    assert node_band == point_band


def test_a_node_without_evidence_reports_unknown_not_false(
    client: TestClient, run_id: str
) -> None:
    """The demo init node has no delta recorded, so the band is unknown."""
    body = _tree_of(client.app.state.settings, run_id)
    init = body["nodes"][0]
    assert init["delta_score"] is None
    assert init["within_noise_band"] is None


# --------------------------------------------------------------------------
# offered_card_ids：PRD 10.2「高亮知识卡传播路径」的最小数据（契约 1.3.0）
# --------------------------------------------------------------------------


def test_the_real_run_reports_the_cards_its_branch_was_offered(
    client: TestClient, run_id: str
) -> None:
    """The demo run's only branch was offered 17 cards; 2 of 6 nodes used 2.

    Both numbers are measured from the committed fixture, not assumed: every
    node is on ``main``, ``branch_offered_cards`` has 17 distinct cards for that
    branch, and exactly two nodes carry ``adopted_cards = ['FE01', 'M01']``.
    """
    body = _tree_of(client.app.state.settings, run_id)
    for item in body["nodes"]:
        assert item["branch_id"] == "main"
        assert len(item["offered_card_ids"]) == 17

    adopters = [item for item in body["nodes"] if item["adopted_card_ids"]]
    assert len(adopters) == 2
    for item in adopters:
        assert item["adopted_card_ids"] == ["FE01", "M01"]


def test_an_adopted_card_may_be_absent_from_the_offer_list(
    client: TestClient, run_id: str
) -> None:
    """A card can be adopted without ever appearing in the offer log.

    Measured on the committed demo run: the two adopting nodes use ``FE01`` and
    ``M01``, but only ``M01`` was ever offered to ``main``. ``FE01`` shows up in
    ``card_stats`` and ``branch_refuted_cards`` instead -- it was injected from
    the knowledge library rather than offered per round, and was later refuted.

    So "adopted ⊆ offered" is **not** an invariant of the artifacts, and the UI
    must not compute "N of M offered" in a way that implies it is. This test
    pins the observed reality so a future "cleanup" of the offer log does not
    silently change what the tree claims.
    """
    body = _tree_of(client.app.state.settings, run_id)
    adopting = [item for item in body["nodes"] if "FE01" in item["adopted_card_ids"]]
    assert adopting, "the demo run does adopt FE01"
    for item in adopting:
        assert "FE01" not in item["offered_card_ids"]
        assert "M01" in item["offered_card_ids"]


def test_offered_cards_are_scoped_to_the_nodes_own_branch(
    mutable_run,
) -> None:
    """Two branches must not see each other's cards."""
    settings, run_id, run_dir = mutable_run
    experiment_id = json.loads(
        (run_dir / "run_summary.json").read_text(encoding="utf-8")
    ).get("experiment_id", "")

    with _db(run_dir) as conn:
        # tree.json says every node is on "main"; put one card on main and
        # another on a branch no node belongs to.
        conn.execute(
            "INSERT OR IGNORE INTO branch_offered_cards"
            " (experiment_id, branch_id, card_id, iteration, was_invalid, offered_at)"
            " VALUES (?, ?, ?, ?, 0, '2026-10-02T00:00:00')",
            (experiment_id, "main", "card-main-1", 1),
        )
        conn.execute(
            "INSERT OR IGNORE INTO branch_offered_cards"
            " (experiment_id, branch_id, card_id, iteration, was_invalid, offered_at)"
            " VALUES (?, ?, ?, ?, 0, '2026-10-02T00:00:00')",
            (experiment_id, "other-branch", "card-other-1", 1),
        )

    body = _tree_of(settings, run_id)
    offered = {card for item in body["nodes"] for card in item["offered_card_ids"]}
    assert "card-main-1" in offered
    assert "card-other-1" not in offered, "a node must not see another branch's cards"


def test_a_card_offered_twice_to_one_branch_appears_once(
    mutable_run,
) -> None:
    """The same (branch, card) offered in two rounds is still one card."""
    settings, run_id, run_dir = mutable_run
    experiment_id = json.loads(
        (run_dir / "run_summary.json").read_text(encoding="utf-8")
    ).get("experiment_id", "")

    with _db(run_dir) as conn:
        for iteration in (1, 2, 3):
            conn.execute(
                "INSERT OR IGNORE INTO branch_offered_cards"
                " (experiment_id, branch_id, card_id, iteration, was_invalid, offered_at)"
                " VALUES (?, 'main', 'card-retry', ?, 0, '2026-10-02T00:00:00')",
                (experiment_id, iteration),
            )

    body = _tree_of(settings, run_id)
    counts = [
        item["offered_card_ids"].count("card-retry")
        for item in body["nodes"]
        if "card-retry" in item["offered_card_ids"]
    ]
    assert counts, "the card should reach the branch at least once"
    assert all(count == 1 for count in counts)


def test_cards_are_ordered_by_offer_iteration(
    mutable_run,
) -> None:
    """Order follows the run, not the primary key or the filesystem."""
    settings, run_id, run_dir = mutable_run
    experiment_id = json.loads(
        (run_dir / "run_summary.json").read_text(encoding="utf-8")
    ).get("experiment_id", "")

    with _db(run_dir) as conn:
        # Insert out of order on purpose: later iteration first.
        for card, iteration in (("card-late", 9), ("card-early", 2), ("card-mid", 5)):
            conn.execute(
                "INSERT OR IGNORE INTO branch_offered_cards"
                " (experiment_id, branch_id, card_id, iteration, was_invalid, offered_at)"
                " VALUES (?, 'main', ?, ?, 0, '2026-10-02T00:00:00')",
                (experiment_id, card, iteration),
            )

    body = _tree_of(settings, run_id)
    offered = body["nodes"][0]["offered_card_ids"]
    positions = [offered.index(c) for c in ("card-early", "card-mid", "card-late") if c in offered]
    assert positions == sorted(positions), f"cards out of order: {offered}"


def test_a_run_without_the_table_reports_no_offered_cards(
    mutable_run,
) -> None:
    """Losing the table means "nothing offered", not an error."""
    settings, run_id, run_dir = mutable_run
    with _db(run_dir) as conn:
        conn.execute("DROP TABLE branch_offered_cards")

    body = _tree_of(settings, run_id)
    assert all(item["offered_card_ids"] == [] for item in body["nodes"])

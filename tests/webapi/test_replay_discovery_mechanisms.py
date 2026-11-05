"""``/discovery`` 的机制与比赛数据（TODO 6.3）。

三个字段在契约里声明了、在实现里是死的，全部在**合成的数据库**上验证
（照抄 ``cloud/store.py`` 的真实写入格式，不编字段）：

1. ``theories`` 读 ``discovery/theories.json``，而 ``discovery/certificates.py``
   把那个文件**硬编码写成 ``[]``**；真数据在 ``mechanism`` 表里。
2. ``matches`` 在 ``replay_service`` 里**从未被赋值**（grep 零命中）。
   比赛结果确实写进了 ``match`` 表（``store.create_match``），但从没落成
   ``tournament_results.json``——``engine._tournament_results`` 初始化成 ``{}``
   之后从没被赋值就交给了 ``certificates.write_json``。

真实 demo 运行这两张表都是 0 行（实测），所以真实数据上验不了，只能合成。
engine 侧 ``Mechanism.role`` 的六种取值（``claim`` / ``llm_rival`` / ``confound``
/ ``artifact`` / ``censor`` / ``other``）正是 TODO 6.3「主张 / 对手机制 / 正反论点
/ 数据裁决」四块分区的依据，本文件直接按 role 断言分区结果。
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from faultevolve.webapi.app import create_app
from faultevolve.webapi.replay_service import _experiment_id, _safe_summary


@contextmanager
def _db(run_dir: Path) -> Iterator[sqlite3.Connection]:
    """A writable connection that really closes.

    同 ``test_replay_tree_edges``：``with sqlite3.connect(...)`` 只结束事务，
    文件句柄仍开着，Windows 上后续测试删不掉 ``fe.db``。
    """
    conn = sqlite3.connect(run_dir / "fe.db")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _summary(run_dir: Path) -> dict:
    return json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))


def _discovery_of(settings, run_id: str) -> dict:
    return TestClient(create_app(settings)).get(f"/api/runs/{run_id}/discovery").json()


def _add_mechanisms(
    conn: sqlite3.Connection, experiment_id: str, family_id: str, rows: list[dict]
) -> None:
    """``store.create_mechanism`` 的列序，逐字照抄。"""
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO mechanism"
            " (id, experiment_id, claim_id, family_id, role, status,"
            "  patch_count, payload_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                experiment_id,
                row.get("claim_id", ""),
                family_id,
                row.get("role", ""),
                row.get("status", "proposed"),
                int(row.get("patch_count", 0)),
                json.dumps(row, ensure_ascii=False),
                "2026-10-02T00:00:00+00:00",
            ),
        )


def _add_match(
    conn: sqlite3.Connection,
    experiment_id: str,
    family_id: str,
    round_idx: int,
    payload: dict,
) -> None:
    """``store.create_match`` 的列序，逐字照抄。"""
    conn.execute(
        "INSERT INTO match"
        " (experiment_id, family_id, round, mech_a, mech_b, slice_id,"
        "  payload_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            experiment_id,
            family_id,
            round_idx,
            payload.get("mech_a", ""),
            payload.get("mech_b", ""),
            payload.get("slice_id", ""),
            json.dumps(payload),
            "2026-10-02T00:00:00+00:00",
        ),
    )


_ROLES = ("claim", "llm_rival", "confound", "artifact", "censor", "other")


def _mechanism_row(mech_id: str, role: str, status: str = "proposed") -> dict:
    """One ``Mechanism`` payload; ``id``/``role``/``status`` are the UI's keys."""
    return {
        "id": mech_id,
        "claim_id": "claim_0",
        "role": role,
        "status": status,
        "patch_count": 2,
        "summary": f"{role} 机制",
    }


# --------------------------------------------------------------------------
# baseline: 真实运行
# --------------------------------------------------------------------------


def test_real_run_reports_the_tables_as_available_but_empty(
    client: TestClient, run_id: str
) -> None:
    """Baseline: the shipped run has both tables, zero rows.

    ``state=available`` with an empty list is the honest reading -- the tables
    exist (discovery was configured) and nothing was established. The UI must
    be able to say "the tournament ran and produced nothing" instead of
    guessing from ``enabled``/``state`` alone.
    """
    body = _discovery_of(client.app.state.settings, run_id)
    # Compared against the constant so a version bump does not silently turn
    # this into a test of a stale literal.
    from faultevolve.webapi.contracts import CONTRACT_VERSION

    assert body["contract_version"] == CONTRACT_VERSION
    assert body["mechanisms_state"] == "available"
    assert body["matches_state"] == "available"
    assert body["theories"] == []
    assert body["matches"] == []


def test_real_run_reports_no_roles_at_all(client: TestClient, run_id: str) -> None:
    """No fabricated roles: an empty list must not grow placeholder entries.

    ``theories.json`` is a literal ``[]``, so the page has to render the
    "no mechanism established" state from the length -- not from a synthesised
    default row.
    """
    body = _discovery_of(client.app.state.settings, run_id)
    assert body["theories"] == []
    assert all("role" in item for item in body["theories"])


# --------------------------------------------------------------------------
# theories <- mechanism 表
# --------------------------------------------------------------------------


def test_theories_are_read_from_the_mechanism_table(mutable_run) -> None:
    """``theories.json`` is ``[]``; the ``mechanism`` table is the real data."""
    settings, run_id, run_dir = mutable_run
    experiment_id = _summary(run_dir).get("experiment_id", "")

    with _db(run_dir) as conn:
        _add_mechanisms(
            conn,
            experiment_id,
            "fam_0",
            [_mechanism_row(f"m_{role}", role) for role in _ROLES],
        )

    body = _discovery_of(settings, run_id)
    assert len(body["theories"]) == len(_ROLES)
    assert {item["role"] for item in body["theories"]} == set(_ROLES)


def test_mechanism_role_partitions_into_claim_and_rivals(mutable_run) -> None:
    """TODO 6.3 splits by ``role``; the four regions need those keys to exist.

    主张 = ``claim``，对手机制 = ``llm_rival``，反论点 = ``confound``，
    数据裁决 = ``censor``/``artifact``/``other``。This is the split the page
    renders, so it is asserted from the API rather than from a helper.
    """
    settings, run_id, run_dir = mutable_run
    experiment_id = _summary(run_dir).get("experiment_id", "")

    with _db(run_dir) as conn:
        _add_mechanisms(
            conn,
            experiment_id,
            "fam_0",
            [
                _mechanism_row("m_claim", "claim", "established"),
                _mechanism_row("m_rival", "llm_rival", "refuted"),
                _mechanism_row("m_conf", "confound"),
            ],
        )

    body = _discovery_of(settings, run_id)
    by_role = {item["role"]: item for item in body["theories"]}
    assert set(by_role) == {"claim", "llm_rival", "confound"}
    assert by_role["claim"]["status"] == "established"
    assert by_role["llm_rival"]["status"] == "refuted"
    # payload survives alongside the mirror columns
    assert by_role["confound"]["patch_count"] == 2
    assert by_role["confound"]["summary"] == "confound 机制"
    assert by_role["confound"]["family_id"] == "fam_0"


# --------------------------------------------------------------------------
# matches <- match 表
# --------------------------------------------------------------------------


def test_matches_are_read_from_the_match_table(mutable_run) -> None:
    """The field was declared and never filled; the rows exist all along."""
    settings, run_id, run_dir = mutable_run
    experiment_id = _summary(run_dir).get("experiment_id", "")

    with _db(run_dir) as conn:
        _add_match(
            conn,
            experiment_id,
            "fam_0",
            0,
            {
                "mech_a": "m_claim",
                "mech_b": "m_rival",
                "slice_id": "slice_0",
                "supports": "m_claim",
                "e_a": 12.5,
                "e_b": -3.25,
            },
        )

    body = _discovery_of(settings, run_id)
    assert len(body["matches"]) == 1
    row = body["matches"][0]
    assert row["supports"] == "m_claim"
    assert row["mech_a"] == "m_claim"
    assert row["mech_b"] == "m_rival"
    assert row["round"] == 0
    # the mirror column survives next to the payload
    assert row["family_id"] == "fam_0"


def test_match_payload_is_merged_over_the_mirror_columns(mutable_run) -> None:
    """``payload_json`` wins, but ``family_id``/``round`` stay available.

    ``_payloads_from_table`` merges ``{**row, **decoded}`` so the tournament page
    can group by family without re-reading the database. If the payload ever
    carried its own ``round``, the payload is the engine's word on the subject.
    """
    settings, run_id, run_dir = mutable_run
    experiment_id = _summary(run_dir).get("experiment_id", "")

    with _db(run_dir) as conn:
        _add_match(
            conn,
            experiment_id,
            "fam_7",
            3,
            {"mech_a": "a", "mech_b": "b", "slice_id": "s", "decisive": True},
        )

    body = _discovery_of(settings, run_id)
    assert body["matches"][0]["family_id"] == "fam_7"
    assert body["matches"][0]["round"] == 3
    assert body["matches"][0]["decisive"] is True


# --------------------------------------------------------------------------
# 隔离与三态
# --------------------------------------------------------------------------


def test_rows_from_another_experiment_are_filtered_out(mutable_run) -> None:
    """A bundle may hold several runs; rows must not leak across them."""
    settings, run_id, run_dir = mutable_run
    experiment_id = _summary(run_dir).get("experiment_id", "")

    with _db(run_dir) as conn:
        _add_match(
            conn, experiment_id, "fam_0", 0, {"mech_a": "mine", "mech_b": "mine"}
        )
        _add_match(
            conn,
            "some_other_experiment",
            "fam_0",
            0,
            {"mech_a": "theirs", "mech_b": "theirs"},
        )

    body = _discovery_of(settings, run_id)
    assert [row["mech_a"] for row in body["matches"]] == ["mine"]


def test_matches_without_an_experiment_column_are_kept(mutable_run) -> None:
    """No column to compare against means "do not filter", not "drop everything"."""
    settings, run_id, run_dir = mutable_run

    with _db(run_dir) as conn:
        conn.execute(
            "INSERT INTO match (family_id, round, mech_a, mech_b, slice_id,"
            " payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "fam_0",
                0,
                "a",
                "b",
                "s",
                json.dumps({"mech_a": "a", "mech_b": "b"}),
                "2026-10-02T00:00:00+00:00",
            ),
        )

    body = _discovery_of(settings, run_id)
    assert len(body["matches"]) == 1


def test_state_is_missing_only_when_the_table_is_absent(mutable_run) -> None:
    """Zero rows is ``available``; a dropped table is ``missing``.

    Two different sentences for the UI: "the tournament produced nothing" vs
    "this bundle has no tournament data at all".
    """
    settings, run_id, run_dir = mutable_run
    experiment_id = _summary(run_dir).get("experiment_id", "")

    with _db(run_dir) as conn:
        _add_mechanisms(conn, experiment_id, "fam_0", [_mechanism_row("m", "claim")])
        _add_match(conn, experiment_id, "fam_0", 0, {"mech_a": "a", "mech_b": "b"})
        conn.execute("DELETE FROM mechanism")
        conn.execute("DELETE FROM match")

    body = _discovery_of(settings, run_id)
    assert body["theories"] == [] and body["matches"] == []
    assert body["mechanisms_state"] == "available"
    assert body["matches_state"] == "available"

    with _db(run_dir) as conn:
        conn.execute("DROP TABLE mechanism")

    body = _discovery_of(settings, run_id)
    assert body["mechanisms_state"] == "missing"
    assert body["theories"] == []
    assert body["matches_state"] == "available"


def test_undecodable_payload_rows_are_skipped_not_fatal(mutable_run) -> None:
    """One broken ``payload_json`` must not take the whole page down."""
    settings, run_id, run_dir = mutable_run
    experiment_id = _summary(run_dir).get("experiment_id", "")

    with _db(run_dir) as conn:
        _add_mechanisms(conn, experiment_id, "fam_0", [_mechanism_row("m", "claim")])
        conn.execute(
            "INSERT INTO mechanism (id, experiment_id, claim_id, family_id, role,"
            " status, patch_count, payload_json, created_at)"
            " VALUES ('broken', '', '', 'fam_0', 'claim', 'proposed', 0, ?, ?)",
            ("{not json", "2026-10-02T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO mechanism (id, experiment_id, claim_id, family_id, role,"
            " status, patch_count, payload_json, created_at)"
            " VALUES ('empty', '', '', 'fam_0', 'claim', 'proposed', 0, '', ?)",
            ("2026-10-02T00:00:00+00:00",),
        )
        conn.execute(
            "INSERT INTO mechanism (id, experiment_id, claim_id, family_id, role,"
            " status, patch_count, payload_json, created_at)"
            " VALUES ('alist', '', '', 'fam_0', 'claim', 'proposed', 0, ?, ?)",
            ("[1, 2]", "2026-10-02T00:00:00+00:00"),
        )

    body = _discovery_of(settings, run_id)
    assert [item["id"] for item in body["theories"]] == ["m"]


def test_experiment_id_helper_is_total() -> None:
    """``_experiment_id`` never raises and never returns whitespace."""
    assert _experiment_id({}) == ""
    assert _experiment_id({"experiment_id": None}) == ""
    assert _experiment_id({"experiment_id": 7510}) == "7510"
    assert _experiment_id({"experiment_id": "  7510f100 "}) == "7510f100"
    # a malformed value must not become the string "None" and filter everything out
    assert _experiment_id({"experiment_id": {"a": 1}}) == ""
    assert _experiment_id({"experiment_id": ["x"]}) == ""


def test_summary_helper_tolerates_a_missing_run_summary(mutable_run) -> None:
    """A bundle without ``run_summary.json`` must not break the state probe."""
    settings, run_id, run_dir = mutable_run
    # rename, never unlink: a safety guard kills processes that unlink inside
    # user directories, and a missing file is all this test needs.
    os.replace(run_dir / "run_summary.json", run_dir / "run_summary.json.bak")

    body = _discovery_of(settings, run_id)
    assert _experiment_id(_safe_summary(_artifacts(settings, run_id))) == ""
    assert body["matches"] == []
    assert body["matches_state"] == "available"


def _artifacts(settings, run_id: str):
    from faultevolve.webapi import replay_service as rs

    return rs.artifacts_for(settings, run_id)


@pytest.mark.parametrize("role", _ROLES)
def test_every_documented_role_survives_the_round_trip(
    mutable_run, role: str
) -> None:
    """``Mechanism.role`` has six documented values; none may be swallowed."""
    settings, run_id, run_dir = mutable_run
    experiment_id = _summary(run_dir).get("experiment_id", "")

    with _db(run_dir) as conn:
        _add_mechanisms(conn, experiment_id, "fam_0", [_mechanism_row("m", role)])

    body = _discovery_of(settings, run_id)
    assert [item["role"] for item in body["theories"]] == [role]


# --------------------------------------------------------------------------
# claims <- claim 表（TODO 6.2 需要的散文：condition / feature / outcome / ...）
# --------------------------------------------------------------------------


def _claim_row(claim_id: str, **overrides) -> dict:
    """A ``Claim`` payload; the keys TODO 6.2 renders."""
    row = {
        "id": claim_id,
        "experiment_id": "",
        "origin_node_id": "43d93d40",
        "source": "insight",
        "title": "冷启动对早期收敛有正向作用",
        "condition": "iterations < 5",
        "feature_code": "warm_start_ratio",
        "outcome": "score",
        "direction": "+",
        "scope": "hdd_mvp / public split",
        "falsifier": "若 iterations<5 时 effect 的 95% CI 跨 0 则否证",
        "status": "proposed",
        "grade": None,
    }
    row.update(overrides)
    return row


def _add_claims(
    conn: sqlite3.Connection, experiment_id: str, rows: list[dict]
) -> None:
    """``store.create_claim`` 的列序，逐字照抄。"""
    for row in rows:
        conn.execute(
            "INSERT OR REPLACE INTO claim"
            " (id, experiment_id, origin_node_id, source, round,"
            "  payload_json, prereg_hash, status, grade, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row["id"],
                experiment_id,
                row.get("origin_node_id", ""),
                row.get("source", ""),
                0,
                json.dumps(row, ensure_ascii=False),
                row.get("prereg_hash", ""),
                row.get("status", "proposed"),
                row.get("grade") or "",
                "2026-10-02T00:00:00+00:00",
            ),
        )


def test_real_run_reports_claims_available_but_empty(
    client: TestClient, run_id: str
) -> None:
    """Baseline: the table exists, nothing was proposed in the shipped run."""
    body = _discovery_of(client.app.state.settings, run_id)
    assert body["claims_state"] == "available"
    assert body["claims"] == []


def test_claims_carry_the_prose_todo_6_2_renders(mutable_run) -> None:
    """The five prose fields TODO 6.2 lists are only in this table.

    ``phenomena.json`` holds ``{claim_id, grade, payload}`` and the payload is a
    ``ClaimTestResult`` (effect/CI/p/e) -- no condition, feature, outcome, scope
    or falsifier anywhere in the artifacts. Without this field the page would
    have a title column it could never fill.
    """
    settings, run_id, run_dir = mutable_run
    experiment_id = _summary(run_dir).get("experiment_id", "")

    with _db(run_dir) as conn:
        _add_claims(conn, experiment_id, [_claim_row("C-7510f100-0001")])

    body = _discovery_of(settings, run_id)
    assert len(body["claims"]) == 1
    claim = body["claims"][0]
    for field in ("condition", "feature_code", "outcome", "scope", "falsifier"):
        assert claim[field], f"{field} 应当从 claim 表读出，而不是空"
    assert claim["direction"] == "+"
    assert claim["source"] == "insight"
    assert claim["title"] == "冷启动对早期收敛有正向作用"


def test_sandbox_failed_claim_keeps_its_status_and_error(mutable_run) -> None:
    """A sandbox failure replaces the payload with ``{"error": ...}``.

    ``pipeline.py`` calls ``update_claim(..., payload_json=json.dumps({"error":
    sb.error}))`` -- the prose is *destroyed* for those rows. The API must still
    report the failure truthfully: status ``sandbox_failed`` plus the error, and
    no invented title. This is exactly what TODO 6.2's "sandbox error" needs.
    """
    settings, run_id, run_dir = mutable_run
    experiment_id = _summary(run_dir).get("experiment_id", "")

    with _db(run_dir) as conn:
        # what the engine really leaves behind: mirror columns keep the claim id
        # and status, payload_json is the bare error object.
        conn.execute(
            "INSERT OR REPLACE INTO claim"
            " (id, experiment_id, origin_node_id, source, round,"
            "  payload_json, prereg_hash, status, grade, created_at)"
            " VALUES (?, ?, '', 'insight', 0, ?, '', 'sandbox_failed', '', ?)",
            (
                "C-7510f100-0002",
                experiment_id,
                json.dumps({"error": "TimeoutError: 沙箱执行超时 30s"}),
                "2026-10-02T00:00:00+00:00",
            ),
        )

    body = _discovery_of(settings, run_id)
    failed = [c for c in body["claims"] if c.get("status") == "sandbox_failed"]
    assert len(failed) == 1
    assert "沙箱执行超时" in failed[0]["error"]
    # 散文确实没了 —— 不能编一个 title 出来
    assert "title" not in failed[0]


def test_claims_from_another_experiment_are_filtered_out(mutable_run) -> None:
    """Same isolation rule as matches/mechanisms."""
    settings, run_id, run_dir = mutable_run
    experiment_id = _summary(run_dir).get("experiment_id", "")

    with _db(run_dir) as conn:
        _add_claims(conn, experiment_id, [_claim_row("C-mine")])
        _add_claims(conn, "some_other_experiment", [_claim_row("C-theirs")])

    body = _discovery_of(settings, run_id)
    assert [c["id"] for c in body["claims"]] == ["C-mine"]


def test_claims_state_is_missing_when_the_table_is_dropped(mutable_run) -> None:
    settings, run_id, run_dir = mutable_run
    with _db(run_dir) as conn:
        conn.execute("DROP TABLE claim")
    body = _discovery_of(settings, run_id)
    assert body["claims_state"] == "missing"
    assert body["claims"] == []

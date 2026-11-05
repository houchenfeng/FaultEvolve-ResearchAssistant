"""「故意失败候选」fixture 的契约级守卫（TODO §12.4 E2E-04 的前置）。

这份 fixture 由 ``scripts/make_failure_fixture.py`` 合成，原因是 mock 通路和
已入库的 demo 运行都产不出失败候选（demo 里那个 intent 写着"故意用错 LightGBM
参数触发修复"的节点，实测 ``status=done``，拿它验错误恢复等于没验）。

下面每条断言对应 E2E-04 要在浏览器里看的一样东西，但跑在 API 层：浏览器用例
挂了的时候，这组测试能立刻区分"fixture 坏了"和"前端坏了"。

字段放的位置全部照抄引擎，不照抄前端的期望：

* ``cloud/tree.py:459`` —— 修复节点的 ``parent_id`` 是**失败节点的父节点**，
  ``depth`` 与失败节点相同，自己带 ``repair_parent_id``。所以 repair 边和
  parent 边是两条不同的边，不会重叠。
* ``engine.py:2009`` / ``tree.py:235`` —— ``repair_count`` / ``repair_attempted``
  写在**失败节点**上。
* ``engine.py:2006`` —— ``repair_exhausted`` 写在**修复链的根**（也就是最初的
  那个失败节点）上。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

#: 与 ``scripts/make_failure_fixture.py`` 里的常量一致。
FAILURE_RUN_ID = "hdd_mvp_faildemo_4b81c0d2"
EXPERIMENT_ID = "4b81c0d2"

ROOT = "c0ffee01"
FAILED_A = "fa11ed01"       # 沙箱参数错，被修好
REPAIR_A = "f1xed001"
FAILED_B = "fa11ed02"       # 超时，三次修复均失败
REPAIR_B = "f1xed002"


def _tree(client: TestClient) -> dict:
    response = client.get(f"/api/runs/{FAILURE_RUN_ID}/tree")
    assert response.status_code == 200
    return response.json()


def _by_id(tree: dict) -> dict[str, dict]:
    return {node["id"]: node for node in tree["nodes"]}


def test_failure_run_is_discovered_and_complete(client: TestClient) -> None:
    """它和 demo 运行一样被发现，且 ``data_state`` 是 stable 的 complete。"""
    rows = client.get("/api/runs").json()
    row = next(item for item in rows if item["run_id"] == FAILURE_RUN_ID)
    assert row["data_state"] == "complete"

    detail = client.get(f"/api/runs/{FAILURE_RUN_ID}").json()
    assert detail["data_state"] == "complete"
    assert detail["run_id"] == FAILURE_RUN_ID


def test_two_candidates_are_invalid(client: TestClient) -> None:
    """E2E-04 步骤 1：树上确实有失败候选，不是靠前端自己造出来的状态。"""
    nodes = _by_id(_tree(client))
    assert nodes[FAILED_A]["status"] == "invalid"
    assert nodes[FAILED_B]["status"] == "invalid"
    # 修好了一个，第二个连修复节点自己也失败了。
    assert nodes[REPAIR_A]["status"] == "done"
    assert nodes[REPAIR_B]["status"] == "invalid"


def test_failure_reason_is_carried(client: TestClient) -> None:
    """E2E-04 步骤 2：错误分类 + 评测里的 error_info 两处都有内容。"""
    nodes = _by_id(_tree(client))
    assert nodes[FAILED_A]["error_class"] == "sandbox_error"
    assert nodes[FAILED_B]["error_class"] == "timeout"

    for node_id in (FAILED_A, FAILED_B, REPAIR_B):
        detail = client.get(f"/api/runs/{FAILURE_RUN_ID}/nodes/{node_id}").json()
        assert detail["evaluation"] is not None, f"{node_id} 没有评测记录"
        assert detail["evaluation"]["error_info"], f"{node_id} 没有失败原因"


def test_repair_association_is_a_distinct_edge(client: TestClient) -> None:
    """E2E-04 步骤 3：repair 关联是一条 repair 边，不跟 parent 边重合。

    引擎给修复节点的 ``parent_id`` 是失败节点的父节点，所以这两类边的
    ``source`` 不同 —— 重合就意味着某一边的语义写错了。
    """
    tree = _tree(client)
    kinds = {(edge["source"], edge["target"], edge["kind"]) for edge in tree["edges"]}
    assert (FAILED_A, REPAIR_A, "repair") in kinds
    assert (FAILED_B, REPAIR_B, "repair") in kinds
    assert (ROOT, REPAIR_A, "parent") in kinds
    assert (ROOT, REPAIR_B, "parent") in kinds
    # 失败节点自己不指向修复节点：因果关系只由 repair_parent_id 表达。
    assert not any(
        edge["source"] in (FAILED_A, FAILED_B) and edge["kind"] == "parent"
        for edge in tree["edges"]
    )


def test_repair_bookkeeping_sits_on_the_failed_node(client: TestClient) -> None:
    """``repair_count`` / ``repair_exhausted`` 在失败节点上（引擎就是这么写的）。

    这条测试同时是给前端的提醒：``NodeDrawer`` 与 ``reflection.ts`` 目前从
    **修复节点**读这两个字段，按引擎的落点永远读不到值。fixture 不迁就前端，
    字段按引擎放；要让 UI 显示"重试 N 次 / 已耗尽"，得改前端的读取位置。
    """
    nodes = _by_id(_tree(client))
    assert nodes[FAILED_A]["repair_count"] == 1
    assert nodes[FAILED_A]["repair_exhausted"] is False
    assert nodes[FAILED_B]["repair_count"] == 3
    assert nodes[FAILED_B]["repair_exhausted"] is True
    assert nodes[REPAIR_A]["repair_parent_id"] == FAILED_A
    assert nodes[REPAIR_B]["repair_parent_id"] == FAILED_B


def test_events_and_tree_tell_the_same_story(client: TestClient) -> None:
    """事件流与 jsonl 数量一致（不一致时服务会报 ContractWarning）。"""
    tree = _tree(client)
    assert tree["warnings"] == []

    page = client.get(f"/api/runs/{FAILURE_RUN_ID}/events?limit=100").json()
    kinds = [event["type"] for event in page["events"]]
    assert "smoke_failed" in kinds
    assert "repair_success" in kinds
    assert "repair_failed" in kinds
    assert kinds[-1] == "run_finished"

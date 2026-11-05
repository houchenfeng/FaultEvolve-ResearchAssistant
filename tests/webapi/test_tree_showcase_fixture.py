"""「展示树」fixture 的契约级守卫（TODO §12.5）。

这份 fixture 由 ``scripts/make_tree_showcase_fixture.py`` 合成，原因是已入库的
demo 运行只有 6 个节点、全在 depth 0/1、既没交叉也没修复 —— 阶段 7 做的分层带、
边例图例、显著性对比、最优路径**一个都渲染不出来**。视觉回归的树/节点详情两屏
因此改拍这份（E2E 里它是普通运行，不进 ``demo_run_ids``，见
``scripts/e2e_serve.py`` 的注释）。

下面每条断言对应视觉回归要在浏览器里看到的一样东西，但跑在 API 层：浏览器用例
挂了的时候，这组测试能立刻区分"fixture 坏了"和"前端坏了"。

字段放的位置全部照抄引擎（与 ``test_failure_fixture.py`` 同一口径）：

* ``cloud/tree.py:459`` —— 修复节点的 ``parent_id`` 是**失败节点的父节点**，
  ``depth`` 与失败节点相同，自己带 ``repair_parent_id``。
* 显著性四档由后端 ``within_noise_band`` 给出（``|delta| <= |noise|`` 即带内），
  ``is_best`` 来自 ``run_summary.best_node_id``。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

#: 与 ``scripts/make_web_showcase_fixture.py`` 里的常量一致（含树形态 + 知识发现）。
TREEDEMO_RUN_ID = "hdd_mvp_showcase_c89e2a01"
BEST = "n18a3b4dd"
CROSSOVER = "n11d3e4f5"
CROSSOVER_SECOND_PARENT = "n6a9b0c1"
REPAIR = "n16a9b0db"
REPAIRED = "n15d9e0fa"


def _tree(client: TestClient) -> dict:
    response = client.get(f"/api/runs/{TREEDEMO_RUN_ID}/tree")
    assert response.status_code == 200
    return response.json()


def _by_id(tree: dict) -> dict[str, dict]:
    return {node["id"]: node for node in tree["nodes"]}


def test_treedemo_run_is_discovered_and_complete(client: TestClient) -> None:
    """它作为普通运行被发现（不进 demo_run_ids），且 ``data_state`` 稳定。"""
    rows = client.get("/api/runs").json()
    row = next(item for item in rows if item["run_id"] == TREEDEMO_RUN_ID)
    assert row["data_state"] == "complete"

    detail = client.get(f"/api/runs/{TREEDEMO_RUN_ID}").json()
    assert detail["data_state"] == "complete"
    assert detail["run_id"] == TREEDEMO_RUN_ID


def test_tree_has_six_depth_bands(client: TestClient) -> None:
    """分层带按 depth 画：depth 只有 0/1 时分带必然塌成两条。"""
    nodes = _by_id(_tree(client))
    assert len(nodes) == 21
    assert sorted({node["depth"] for node in nodes.values()}) == [0, 1, 2, 3, 4, 5]
    # depth 与 parent 自洽（repair 节点同 depth，见 tree.py:459）。
    for node in nodes.values():
        if node["parent_id"] is not None:
            assert node["depth"] == nodes[node["parent_id"]]["depth"] + 1


def test_best_path_is_a_real_chain(client: TestClient) -> None:
    """最优路径 6 跳：demo 那份只有 1 跳，画出来就是一根短线。"""
    tree = _tree(client)
    assert tree["best_node_id"] == BEST
    assert len(tree["best_path"]) == 6
    assert tree["best_path"][-1] == BEST
    assert sum(1 for node in tree["nodes"] if node["is_best"]) == 1


def test_crossover_node_carries_second_parent(client: TestClient) -> None:
    """交叉节点只在 ``second_parent_ids`` 里带第二父 —— 边例图例靠它。"""
    nodes = _by_id(_tree(client))
    assert nodes[CROSSOVER]["second_parent_ids"] == [CROSSOVER_SECOND_PARENT]
    assert sum(1 for node in nodes.values() if node["second_parent_ids"]) == 1


def test_repair_node_follows_engine_convention(client: TestClient) -> None:
    """修复节点是 repair 边 + parent 边两条不同的边，不是重叠的一条。"""
    nodes = _by_id(_tree(client))
    repairer, failed = nodes[REPAIR], nodes[REPAIRED]
    assert repairer["operator"] == "repair"
    assert repairer["repair_parent_id"] == REPAIRED
    # 引擎口径：parent 指向失败节点的父节点，depth 相同。
    assert repairer["parent_id"] == failed["parent_id"]
    assert repairer["depth"] == failed["depth"]


def test_all_four_significance_tiers_are_populated(client: TestClient) -> None:
    """四档每档都有节点，否则"分档视觉可辨"在图上无从验证。"""
    tree = _tree(client)
    tiers = {"best": 0, "progress": 0, "noise": 0, "unknown": 0}
    for node in tree["nodes"]:
        if node["is_best"]:
            tiers["best"] += 1
        elif node["within_noise_band"] is None:
            tiers["unknown"] += 1
        elif node["within_noise_band"]:
            tiers["noise"] += 1
        else:
            tiers["progress"] += 1
    assert all(count > 0 for count in tiers.values()), tiers

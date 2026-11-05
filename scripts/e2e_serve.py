#!/usr/bin/env python
"""E2E 专用的 Web API 启动器（TODO §12.4）。

为什么不直接用 ``fe web serve``：那条路径从 ``FE_WEB_*`` 环境变量读配置，
测试结果就会取决于跑测试的人手上正好有什么环境变量，同一份代码在不同机器上
跑出不同结果。E2E 要的是一份**固定、隔离、可复现**的配置：

* 运行目录是 fixture 的一份**副本**，放在临时目录里（回放不碰仓库，启动新运行
  也不会在 tests/fixtures 下留垃圾）；
* run registry 每次启动都是新的临时文件（用例之间不串状态）；
* 打开进程控制（E2E-02 / E2E-03 要真的启动运行）；
* 端口可指定，好让 Playwright 起自己那份后端，而不是蹭开发者手上那个。

用法::

    python scripts/e2e_serve.py --port 8011
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

#: 仓库内的只读 fixture：一个完整运行 + 一个 toy 任务。
_FIXTURE_RUNS = _REPO / "tests" / "fixtures" / "runs"
_FIXTURE_TASKS = _REPO / "tests" / "fixtures"

#: 历史单树展示运行（21 节点 / 6 层 / 含交叉与修复链 / 四档显著性齐全）。
#:
#: 目录名里的 ``showcase`` 是历史遗留：它曾经驱动一套专用展示页，那套页面
#: 已按 D6.5 删除，现在它只是一份**普通的旧单岛运行**，由通用页面回放。
#: id 不改名，因为 fixture 目录、PROVENANCE 与若干 Python 测试都指着它。
#:
#: 为什么 E2E 必须留着它：树形态的断言（分层带、边图例、显著性四档）需要
#: 一棵够深的树；三岛那份每岛只有 7 个节点、层数不足以撑起这些画面。
LEGACY_SINGLE_TREE_RUN_ID = "hdd_mvp_showcase_c89e2a01"

#: 三岛运行（21 节点 = 3 岛 × 7，含摘要交换与跨岛嫁接边）。
#:
#: 由真实引擎在真实 evaluator 上生成（仅语言模型为 mock），S6/D6.4 的
#: 「三岛概览 / 岛树 / 交换详情」三个画面拍的就是它。
ISLANDS_RUN_ID = "hdd_mvp_islands_15l4nd01"

#: 薄型回放样本，部分 webapi 单测仍指向它。
DEMO_RUN_ID = "hdd_mvp_demo_7510f100"

#: 故意**缺 evaluator.py** 的任务，E2E-02 用它验「缺件不能继续」。
#:
#: 放在 scratch 里而不是 ``tests/fixtures/`` 下面：后者是若干 Python 测试
#: 共用的任务根，往里加一个目录会改变它们列出来的任务集合，那些断言会跟着飘。
INCOMPLETE_TASK_ID = "toy_task_no_eval"

#: 合成运行：discovery 全是空表，用来拍「空状态」与验恢复。
FAILURE_RUN_ID = "hdd_mvp_faildemo_4b81c0d2"


def build_settings(scratch: Path):
    """构造一份与环境变量无关的 WebSettings。"""
    from faultevolve.webapi.settings import WebSettings

    # 把 fixture 运行**复制**到 scratch，runs_root 与 artifacts_root 都指向它。
    #
    # 两个 root 必须同一个目录：分开试过，runs_root=fixture + artifacts_root=scratch，
    # 结果新启动的运行落在 scratch，而回放 API 只认 runs_root ⇒ `/api/runs/{新id}`
    # 直接 500，E2E-03 根本查不到自己刚启动的运行。
    # 只搬**指定的那一个** fixture 运行，不是整个目录。
    #
    # 曾经整目录复制，结果把 `tests/fixtures/runs/` 里一个手工调试留下的垃圾
    # 运行也带进了 E2E，列表里平白多一项，任何"只有 N 个运行"的断言都会飘。
    # 指名复制也有代价：将来 fixture 加了新运行要在这里同步——但比起静默
    # 混入无关数据，这个代价更划算。
    runs_root = scratch / "runs"
    for run_id in (LEGACY_SINGLE_TREE_RUN_ID, ISLANDS_RUN_ID, DEMO_RUN_ID, FAILURE_RUN_ID):
        shutil.copytree(_FIXTURE_RUNS / run_id, runs_root / run_id)

    # 缺件任务：从 toy_task 抄一份，但**不**抄 evaluator.py。
    # 复制而不是手造内容，是为了让它在别的维度上（init.py 能解析、
    # problem.md 存在）都合格 —— 这样"不能继续"只可能来自缺 evaluator。
    tasks_root = scratch / "tasks"
    incomplete = tasks_root / INCOMPLETE_TASK_ID
    incomplete.mkdir(parents=True)
    for name in ("init.py", "problem.md", "prompt.md"):
        shutil.copyfile(_FIXTURE_TASKS / "toy_task" / name, incomplete / name)

    return WebSettings(
        runs_root=runs_root,
        artifacts_root=runs_root,
        # task_roots 是**父目录**，服务会扫它下面一层找任务目录。
        #
        # 带上 benchmark/ 是为了拿到一个**就绪**的任务：fixture 里的
        # toy_task 缺 data 目录，就绪检查不过，录入页的入口按钮是禁用的，
        # E2E 根本进不去表单。benchmark/hdd_mvp 是完整的（evaluator / init /
        # data 齐），且 E2E 全程只读。
        task_roots=[_FIXTURE_TASKS, _REPO / "benchmark", tasks_root],
        allowed_path_roots=[
            _FIXTURE_RUNS, _FIXTURE_TASKS, _REPO / "benchmark", tasks_root,
        ],
        run_registry=scratch / "runs_registry.json",
        # 不设这个，服务器配置列表会报错，新建运行页的整张表单都不会渲染
        # （ServerProfileForm 在 isError 时只画一个错误面板），E2E 里表现为
        # "补充说明"输入框根本不存在。文件不存在时服务当成空列表，所以直接
        # 指一个还没创建的文件即可。
        server_profile_store=scratch / "server_profiles.json",
        enable_process_control=True,
        # 显式置空，与产品服务共享同一个默认值（settings.py 里就是 []）。
        # 总览不再读这个字段（D6.5）：运行从哪来由来源索引决定。放在这里
        # 是为了让「空 demo_run_ids 下 E2E 全绿」成为一条持续验证的事实，
        # 而不是一个没人跑过的配置。
        demo_run_ids=[],
        # E2E 要看到实时变化，轮询给快一点，别让用例干等默认 1s。
        poll_interval_ms=250,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    # 每次启动一个全新的 scratch 目录：上一轮 E2E 留下的运行记录 / 服务器配置
    # 不该影响这一轮。
    scratch = Path(tempfile.mkdtemp(prefix="fe_e2e_"))

    settings = build_settings(scratch)

    from faultevolve.webapi.app import create_app
    from faultevolve.webapi.run_control import recover_on_startup

    try:
        recover_on_startup(settings)
    except Exception as exc:  # pragma: no cover - E2E 环境相关
        print(f"warning: registry recovery failed ({type(exc).__name__}), continuing")

    import uvicorn

    print(
        f"E2E Web API on {args.host}:{args.port} "
        f"runs_root={settings.runs_root} scratch={scratch}",
        flush=True,
    )
    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

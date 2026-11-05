# 工程步骤到统一科研流程的映射

本 Skill 以当前仓库的实现和实际硬盘实验为依据。旧设计文档包含规划项；不能将规划当作已实现能力。仓库根目录下列路径是实现定位，迁移安装 Skill 后仍需定位 FaultEvolve 仓库。

2026-10-17 更新：HDD 的 `fe run`、配置启用的 `fe research run`/Web 已通过 `workflow.py` 串联完整训练体检、训练副本处理、写出后复检、代码演化、分层调优与结果报告。`tasks/data_workflow.py` 保存处理依据，Web `/workflow` 接口投影聚合数据及路线/试验；下面涉及原始独立执行器的说明保留为组件定位和其他任务适配参考。

| 科研步骤 | 当前实现/材料 | 统一 Skill 的职责 |
|---|---|---|
| 数据理解与质量 | `cli.py:data_checkup`、`tasks/data_checkup.py`、适配器 `discovery_frames` | 宿主核对输入与视图范围、处理阻断/待决策项；不支持该接口的任务显式编写只读检查 |
| 可复现数据处理 | 原任务准备脚本、候选预处理、项目独立转换脚本 | 宿主按授权设计并执行，保存配置、影响行数和前后检查；体检命令本身不清洗 |
| 文献整理 | `benchmark/hdd_mvp/knowledge/{sources.yaml,expert.md,cards.jsonl}`，现有 51 张策划卡 | 宿主核实来源、按新问题检索/阅读并生成卡片；现有 build_cards 脚本是硬盘策划库生成器，不是通用论文爬虫 |
| 知识进入搜索 | `src/faultevolve/knowledge/{loader.py,retriever.py}`、`cloud/engine.py` | 配置 knowledge 路径、关键词与算子，核对实际卡片使用事件；阅读文献本身不等于已注入 |
| 任务和方法结构 | `tasks/protocol.py`、`tasks/registry.py` 与任务四件套 | 宿主实现/复用基线、评估器、适配器与参数接口，并验证评分可信性 |
| 多路线搜索 | `cloud/islands.py`、`config.py:IslandSpec/IslandsConfig` | 宿主从假设自动生成配置；引擎执行岛内搜索及交流，当前岛屿评估串行 |
| 算法进化与恢复 | `cloud/engine.py`、`research.py` | 引擎运行；宿主监测、诊断、决定跨实验路线调整 |
| 引擎内结构化 HPO | `cloud/engine_autotune.py`、`optimization/hpo_engine.py` | 目前是 HDD logreg/lightgbm 模板，dev 搜索后晋级完整评估；不对任意演化程序自动抽取参数 |
| 已演化路线的层级 HPO | `research_campaign.py:choose_routes/hierarchical_search`，`autoresearch-hierarchical-search-cn/scripts/` | 原 Campaign 接线针对 HDD；其他领域由宿主实现任务参数渲染与评估桥接，复用通用搜索核心 |
| 目标验收与交付 | `common/research.py`、`research.py` | 引擎产出单 run 证据；宿主合并文献和跨 run/HPO 证据，沉淀统一研究规范 |
| 方案效果可视化 | `web/src/features/results/{SolutionComparison.tsx,solution-comparison.ts}`、真实节点与摘要 API | 展示初始与运行最优；宿主另核对联合可行候选和外部 HPO 结果，补齐项目图表及来源 |
| 方法与证据打包 | `research.py`、`research_campaign.py` 的结果导出、当前 Skill 全目录 | 引擎 ZIP 为单次记录；宿主补充数据/文献/图表及证据索引，生成项目级包 |

## 参考 Skill 的来源与使用方式

用户指定参考：`/mnt/nas/public/users/jiangxiwu/FaultEvolve-huawei/formal_20261015_194457_qwen38max0902_live/skill/fe-research-agent`，本次读取其 `SKILL.md`、`references/protocol.md` 与 `latest-result.md`。采用其“入口规范 + 协议参考 + 已完成结果附件”的结构；工作流主文件保持通用，运行结果留在独立交付副本。

当前统一入口在此基础上增加前置数据与文献、方法结构、项目累计预算、效果展示和证据索引。可追溯附件必须来自当前项目，不把参考运行的分数复制成新项目成果。伐谋数据分析和结果可视化的方法来源见相应参考文件。

## 实际硬盘实验

证据位于 NAS 的 `formal_20261015_194457_qwen38max0902_live/results/report.json` 和 `hyperparameters/summary.json`：

- 运行先使用已有知识包和三岛配置；后续代码进化最终完成 15 轮，最佳 val ROS 为 41.061911178823756。
- 从演化路线提取可识别数值参数，进行了 24 次层级参数评估；最终 val ROS 为 41.77970426921221，来源 `hierarchical_hpo`。
- 最优参数候选 `d905cbcf65451e4ce5db`，路线 `island_a_cb924db6`：learning_rate=0.12、num_leaves=32、min_child_samples=60。
- 已记账 LLM Token 共 998464；代码阶段停止于轮次上限，HPO 停止于 trial 预算。
- 用户曾将原 150 轮预算调整为 15 并恢复。这是人工介入，不能写成无人干预完成。
- 该结果没有私有测试、真实跨器件迁移或自动检索文献的完整证据。

可复用的方法顺序是“知识与问题工件 → 基线 → 互补岛屿代码进化 → 固定路线参数搜索 → 实评比较 → 经验归档”。统一 Skill 将前置整理和跨阶段决策交给宿主 AI 自主执行，不把历史人工配置描述为已经完全自动化。

[历史 Campaign 协议](hdd-campaign.md) 保留早期运行协议，其中 150 轮是历史初始配置；新任务预算以当前用户要求及冻结项目契约为准。

# 通用 Skills 设计文档

> 文档版本：v1.0  
> 最后更新：2026-09-28

## 1. 什么是 Skill

Skill 是一份可以被 AI Agent 直接执行的"操作规范"，用 `SKILL.md` 描述，附带脚本和参考资料。它是从运行中提炼的、可迁移到新设备或新数据集的知识结晶。

## 2. Skill 契约格式

遵循研途启航（Navivisor-webui）的 SKILL.md 规范：

```yaml
---
name: <skill-id>
description: <一句话：什么时候用>
---

# Skill 名称

## 触发条件
什么任务 / 什么信号下调用

## 输入
- 必需文件、数据接口、配置项（含预算）
- 数据格式要求

## 步骤
1. 步骤一：调用的工具或脚本、成功判据
2. 步骤二：...
3. ...

## 输出
- 产物清单与格式（JSON / Markdown / 程序文件）

## 护栏
- 禁止操作（如不得读取留出集、不得回传原始数据、报告分只来自真实评估器）

## 适用范围
- 在哪些设备 / 数据上验证过
- 已知失效条件

## 血统
- 由哪些运行（experiment_id）、哪些知识卡蒸馏而来
```

## 3. 通用 Skills 清单

| Skill ID | 名称 | 触发条件 | 状态 |
|----------|------|---------|------|
| `fe-evolve-manager` | 故障预测自动调优 | 新设备或新数据集需要预测器 | 基础版已实现 |
| `fe-knowledge-discovery` | 知识发现与证伪 | 需要解释"为什么"或产出结论 | 规划 |
| `fe-data-checkup` | 数据体检 / 沉默故障分析 | 接入新数据时的第一步 | 规划 |
| `fe-knowledge-injection` | 文献知识卡构建 | 新领域冷启动 | 开发中 (PR #3) |
| `fe-report-generation` | 实验报告生成 | 运行结束 | 规划 |

## 4. 各 Skill 详细设计

### 4.1 故障预测自动调优 (`fe-evolve-manager`)

```yaml
---
name: fe-evolve-manager
description: 在新设备或新数据集上自动演化故障预测程序
---
```

#### 触发条件
- 用户请求"在这份数据上构建预测器"
- 用户提供了新的任务目录（含 `evaluator.py`、`init.py`、`problem.md`）

#### 输入

| 输入 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `task_dir` | 目录路径 | 是 | 包含 evaluator.py、init.py、problem.md |
| `data_dir` | 目录路径 | 是 | 训练/验证/测试数据 |
| `target_score` | float | 是 | 目标 ROS 分数 |
| `max_iterations` | int | 否 | 最大迭代次数，默认 50 |
| `noise_delta` | float | 否 | 噪声带，默认从 f1_boot_std 估计 |
| `knowledge_cards` | 文件路径 | 否 | cards.jsonl |
| `deployment_mode` | enum | 否 | hybrid / local |

#### 步骤

1. **环境检查**
   - 工具：`check_environment.py`
   - 判据：Python 版本、依赖安装、数据文件存在
   - 失败处理：输出缺失项清单，暂停等待用户修复

2. **基线评估**
   - 工具：`evaluator.py` 评估 `init.py`
   - 判据：获得初始 ROS 分数和 f1_boot_std
   - 输出：baseline_score, noise_estimate

3. **噪声带估计**
   - 计算：δ = κ × f1_boot_std，κ 默认 1.5，下限 0.5
   - 输出：noise_delta

4. **启动演化循环**
   - 工具：`fe evolve local <task_dir>` 或通过 SSH
   - 配置：target_score, max_iterations, noise_delta
   - 监控：实时输出到 events.jsonl

5. **修复处理**
   - 运行时错误按"异常类型 @ 库"分类
   - 最多 2 次修复尝试
   - 重复错误写入分支记忆

6. **达标停止**
   - 判据：当前最优分 ≥ target_score 且超过 δ
   - 或达到 max_iterations

7. **输出整理**
   - 最优程序：`programs/best.py`
   - 运行摘要：`run_summary.json`
   - 演化树：`tree.json`
   - 事件日志：`events.jsonl`

#### 输出

| 输出 | 格式 | 说明 |
|------|------|------|
| `best_program.py` | Python | 最优预测程序 |
| `run_summary.json` | JSON | 包含 best_score, iterations, tokens, time |
| `tree.json` | JSON | 完整演化树 |
| `events.jsonl` | JSONL | 事件流 |
| `programs/` | 目录 | 所有节点程序 |

#### 护栏

- **禁止**读取测试集标签（`test_labels`、`holdout`）
- **禁止**使用 `glob`、`listdir`、`subprocess` 访问任务目录外的文件
- **禁止**手动设置报告分数，必须来自真实评估器
- 超时硬限制：单次评估 900 秒

#### 适用范围

- ✅ Backblaze HDD 数据（已验证）
- ⏳ SmartMem 内存数据（计划）
- ⚠️ Backblaze SSD（故障记录不足，仅探索）

#### 血统

- 基于 FaultEvolve 主仓库 PR #1、PR #2 蒸馏
- 参考知识卡：全部 51 张

---

### 4.2 知识发现与证伪 (`fe-knowledge-discovery`)

```yaml
---
name: fe-knowledge-discovery
description: 从演化结果中提取可证伪的三层知识
---
```

#### 触发条件
- 演化运行完成，需要解释"为什么有效"
- 用户请求产出可发表的结论

#### 输入

| 输入 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `run_id` | string | 是 | 演化运行 ID |
| `top_k` | int | 否 | 分析的 Top-K 程序数，默认 5 |
| `confirmation_slice` | 数据切片 | 是 | 按盘留出的确认数据 |
| `held_out_slice` | 数据切片 | 否 | 远期留出（仅理论层） |

#### 步骤

1. **提取 Top-K 程序**
   - 从演化树中选取分数最高的 K 个节点

2. **论断翻译**
   - 工具：`translate_claim`（Qwen）
   - 输入：特征代码 + 聚合统计
   - 输出：Claim JSON（条件、变量、效应、范围）

3. **新颖性判断**
   - 语义新颖：Qwen 盲推 + Jev 逐卡蕴含判断
   - 功能新颖：在 F(K0) 基础之上是否仍有增量

4. **预注册**
   - 生成预测矩阵和检验参数
   - 计算 sha256 哈希
   - 记录提交时间戳

5. **对手机制生成**
   - 工具：`propose_rivals`（Qwen）
   - 每条机制至少配一个非因果对手
   - 必配：M_censor（运维删失）

6. **判别检验编译**
   - 工具：`derive_tests`
   - 只保留两机制预测不同的检验
   - Jev 做相关性检查

7. **本地执行检验**
   - 在确认切片上执行
   - 设计智能体只能看表结构
   - 计算 p 值并转 e 值

8. **判级与证书生成**
   - 累计 E = ∏eᵢ
   - E ≥ 1/α 时判定
   - 多机制用 e-BH 控制 FDR
   - 生成否证证书

#### 输出

| 输出 | 格式 | 说明 |
|------|------|------|
| `phenomena.json` | JSON | 现象卡列表 |
| `mechanisms.json` | JSON | 机制卡列表 |
| `theories.json` | JSON | 理论卡列表（如有） |
| `certificates.json` | JSON | 否证证书 |
| `tournament_results.json` | JSON | 锦标赛比赛结果 |
| `preregistration.json` | JSON | 预注册记录（含哈希） |

#### 护栏

- 设计智能体**只能看表结构**，不能看确认切片的实际数据
- 每个切片的每项检验只对同一比赛族使用一次
- 远期留出**只打开一次**
- 功效不足判为"未定"，不判"否证"

#### 适用范围

- ✅ Backblaze HDD（位置类检验需 2023Q3 以后数据）
- ⏳ SmartMem 内存（计划）

---

### 4.3 数据体检 (`fe-data-checkup`)

```yaml
---
name: fe-data-checkup
description: 接入新数据时的首轮检查
---
```

#### 触发条件
- 接入新的设备日志数据
- 用户请求了解数据质量

#### 输入

| 输入 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `data_path` | 目录或文件 | 是 | 数据位置 |
| `label_column` | string | 是 | 故障标签列名 |
| `id_column` | string | 是 | 设备 ID 列名 |
| `date_column` | string | 否 | 日期列名 |

#### 步骤

1. **字段覆盖率检查**
   - 统计每列的非空率
   - 识别全空或近空列

2. **标签语义分析**
   - 故障率统计
   - 时间分布
   - 是否存在删失规则

3. **沉默故障分析**
   - 定义 S0 子集（关键属性全为 0）
   - 计算 S0 占比
   - 按厂商/型号分层统计

4. **位置/环境字段检查**
   - 识别可用作 ICP 环境的列
   - 检查覆盖率随时间变化

5. **统计功效估计**
   - 各子集的正样本数
   - 最小可检测效应估计

#### 输出

| 输出 | 格式 | 说明 |
|------|------|------|
| `data_facts.md` | Markdown | 人类可读的数据事实表 |
| `data_facts.json` | JSON | 机器可读格式 |
| `silent_subset_stats.csv` | CSV | 沉默子集统计 |
| `field_coverage.csv` | CSV | 字段覆盖率 |

#### 护栏

- 输出**只包含聚合量**
- 小于 k 的单元格计数需裁剪
- 不输出序列号等可识别信息

---

### 4.4 文献知识卡构建 (`fe-knowledge-injection`)

```yaml
---
name: fe-knowledge-injection
description: 从文献构建可注入演化的知识卡
---
```

#### 触发条件
- 新领域冷启动
- 需要扩充知识库

#### 输入

| 输入 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `search_keywords` | string[] | 是 | 检索关键词 |
| `seed_papers` | string[] | 否 | 种子论文 DOI |
| `domain` | string | 是 | 领域标识 |

#### 步骤

1. **文献检索**
   - 使用 OpenAlex 或 Scopus API
   - 按关键词和种子论文扩展

2. **核对来源**
   - 验证 DOI 有效性
   - 获取全文或摘要

3. **写卡**
   - 为每篇关键论文生成卡片
   - 字段：id, title, category, claim, rationale, applicability, risk, source_ids, tags, impl_hint, priority

4. **校验**
   - 检查字段完整性
   - 去重
   - 生成 sources.yaml

#### 输出

| 输出 | 格式 | 说明 |
|------|------|------|
| `cards.jsonl` | JSONL | 知识卡集合 |
| `sources.yaml` | YAML | 来源元数据 |
| `expert.md` | Markdown | 专家方向文档 |

#### 护栏

- 只收录实际打开过的来源
- 未核实的内容需标注
- 不编造 DOI 或引用数

---

### 4.5 实验报告生成 (`fe-report-generation`)

```yaml
---
name: fe-report-generation
description: 从运行结果自动生成三栏知识增量报告
---
```

#### 触发条件
- 演化运行完成
- 知识发现流程完成

#### 输入

| 输入 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `run_id` | string | 是 | 演化运行 ID |
| `knowledge_id` | string | 是 | 知识发现运行 ID |
| `format` | enum | 否 | markdown / word |

#### 步骤

1. **从 manifest 读取数据**
   - 严禁手动填入数字
   - 所有数字必须来自检验结果

2. **渲染三栏**
   - 现象层：效应量、CI、分层森林图
   - 机理层：因果图、Elo、否证证书
   - 原理层：预测、命中结果

3. **添加对照结果**
   - 阴性对照假发现数
   - 植入信号找回率

4. **添加成本统计**
   - token 用量
   - 墙钟时间

5. **导出**
   - Markdown 或 Word 格式

#### 输出

| 输出 | 格式 | 说明 |
|------|------|------|
| `knowledge_report.md` | Markdown | 知识增量报告 |
| `knowledge_report.docx` | Word | （可选）Word 版本 |

#### 护栏

- 数字**只能从 manifest 读取**
- 禁止手动填写或修改数字

---

## 5. HDD 和内存两个数据集如何复用同一套 Skills

### 5.1 复用原则

同一套 Skills 的复用通过**概念层映射 + 数据适配器 + 评分配置**实现：

| 复用层 | HDD | 内存 (SmartMem) | 说明 |
|--------|-----|-----------------|------|
| **Skill 流程** | 完全相同 | 完全相同 | 步骤、判据、护栏不变 |
| **概念映射** | SMART 属性 | mcelog 字段 | 人工确认 |
| **数据适配器** | `hdd_adapter.py` | `memory_adapter.py` | 不同读取逻辑 |
| **评分配置** | ROS (F1+AUPRC+R@FAR) | F1 | 不同评估指标 |
| **知识卡** | 51 张 HDD 卡 | 新建内存卡 | 部分概念可迁移 |

### 5.2 概念映射示例

| 概念 | HDD | 内存 |
|------|-----|------|
| 累计错误计数 | SMART 5/187/197/198 raw | CE 次数 |
| 增量/增长率 | counter_d14 | ce_rate |
| 首次非零 | first_nonzero_days | first_ce_days |
| 位置/环境 | datacenter/vault/pod | region/CPU/channel |
| 厂商异质性 | model / vendor | server_vendor / DIMM 料号 |

### 5.3 迁移流程

```
1. 数据体检 (fe-data-checkup)
   └─ 确认字段覆盖、标签语义、沉默子集定义

2. 概念映射 (人工)
   └─ 建立 HDD 概念 → 内存字段的对应表
   └─ 写入 preregistration

3. 数据适配器 (新建)
   └─ 实现 memory_adapter.py
   └─ 提供与 hdd_adapter 相同的接口

4. 评分配置 (调整)
   └─ 修改 evaluator.py 使用 F1 而非 ROS
   └─ 调整时间窗口、预测提前量

5. 知识卡迁移 (部分)
   └─ 概念层卡片可直接使用
   └─ 设备特有卡片需重新构建

6. 运行演化 (fe-evolve-manager)
   └─ 相同的 Skill，不同的配置

7. 知识发现 (fe-knowledge-discovery)
   └─ 相同的流程，设备特有的检验
```

### 5.4 迁移效果评估

| 指标 | 定义 |
|------|------|
| 冷启动增益 | (空白组达标评估次数 − 迁移组达标评估次数) / 空白组 |
| 负迁移检测 | 迁移组比空白组更差时，标记该知识卡在新领域"不适用" |
| 事前预测命中率 | 预注册预测在内存数据上被证实的比例 |

---

## 6. Skills 前端展示

### 6.1 Skills 列表页

显示所有已注册的 Skills：
- 名称、描述、状态（已实现/开发中/规划）
- 最近使用时间
- 使用次数

### 6.2 Skill 详情页

展示 SKILL.md 内容，并可视化：
- 输入输出参数表
- 步骤流程图
- 血统追溯（来自哪些运行）

### 6.3 跨设备复用展示

专门的面板展示同一 Skill 在不同数据集上的应用：

```
┌─────────────────────────────────────────────────────────────┐
│ Skill: fe-evolve-manager (故障预测自动调优)                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────┐         ┌───────────────┐               │
│  │ Backblaze HDD │ ──────→ │ SmartMem 内存  │               │
│  │               │  迁移    │               │               │
│  │ ✅ 已完成     │         │ ⏳ 计划中      │               │
│  │ 最优: 34.96   │         │               │               │
│  └───────────────┘         └───────────────┘               │
│                                                             │
│  迁移配置差异:                                               │
│  • 数据适配器: hdd_adapter → memory_adapter                  │
│  • 评分: ROS → F1                                           │
│  • 概念映射: [查看详情]                                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. 待定设计

| 待定项 | 说明 |
|--------|------|
| Skill 版本管理 | 是否需要支持多版本并存？ |
| Skill 参数 UI | 是否在前端提供可视化参数配置？ |
| Skill 执行追踪 | 如何展示 Skill 执行进度和中间状态？ |

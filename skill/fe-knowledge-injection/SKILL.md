---
name: fe-knowledge-injection
description: FaultEvolve ERA 风格知识注入技能：从文献中提取知识卡片并在进化过程中注入
---

# FaultEvolve 知识注入技能

本技能说明如何为 FaultEvolve 构建和使用领域知识卡片，实现 ERA（Evolutionary Retrieval-Augmented）风格的知识注入。

## 何时使用本技能

- 为新任务（如 SSD 故障预测、网络设备故障预测）创建知识包
- 向现有任务添加新的领域知识卡片
- 验证现有知识卡片的 schema 正确性
- 理解知识注入系统的工作原理

## 输入

### 任务目录结构

```
benchmark/<task>/
├── evaluator.py          # 评估脚本（受保护，不要修改）
├── init.py               # 初始解决方案（受保护，不要修改）
├── problem.md            # 问题描述
├── prompt.md             # LLM 系统提示
├── evolve.yaml           # 进化配置
├── data/                 # 数据目录（受保护）
│   ├── train_*.csv
│   ├── val_*.csv
│   └── holdout_*.csv     # 禁止访问
└── knowledge/            # 知识包目录（可创建）
    ├── cards.jsonl       # 知识卡片
    ├── sources.yaml      # 文献来源
    ├── expert.md         # 专家经验
    └── README.md         # 说明文档
```

### 环境变量

```bash
# .env 文件格式
DASHSCOPE_API_KEY=sk-xxx          # 必需：DashScope API 密钥
MIYANG_API_KEY=xxx                # 可选：Jev 判断服务密钥
FE_RUNS_DIR=/path/to/runs         # 可选：运行输出目录
FE_ARTIFACTS_DIR=/path/to/arts    # 可选：大文件制品目录

# 数据路径
# 使用 benchmark/<task>/data/ 或设置 HDD_BENCH_DATA_ROOT 环境变量
```

## 执行命令

### 1. 创建新知识包

```bash
# 创建知识目录
mkdir -p benchmark/<task>/knowledge

# 从模板生成卡片（卡片是手工策划的）
python skill/fe-knowledge-injection/scripts/build_cards.py \
  --sources skill/fe-knowledge-injection/references/sources.yaml \
  --expert skill/fe-knowledge-injection/references/expert.md \
  --out benchmark/<task>/knowledge/cards.jsonl

# 复制参考文件
cp skill/fe-knowledge-injection/references/sources.yaml benchmark/<task>/knowledge/
cp skill/fe-knowledge-injection/references/expert.md benchmark/<task>/knowledge/
```

### 2. 验证现有卡片

```bash
python skill/fe-knowledge-injection/scripts/build_cards.py \
  --validate-only benchmark/<task>/knowledge/cards.jsonl

# 退出码: 0 = 验证通过, 1 = 有错误
```

### 3. 添加新卡片

卡片是手工策划的。要添加新卡片：

1. 编辑 `scripts/build_cards.py`，添加新的 `card()` 调用：

```python
card(
    "FE99",                                    # 唯一 ID
    "New feature technique",                   # 标题
    "feature_engineering",                     # 类别
    "核心声明：这个方法能带来什么效果",         # claim
    "原理说明",                                # rationale
    "适用条件",                                # applicability
    "Medium",                                  # expected_effect
    "潜在风险",                                # risk
    ["source1", "source2"],                    # source_ids
    ["tag1", "tag2"],                          # tags
    "具体实现建议",                            # impl_hint
    2                                          # priority (1=最高)
)
```

2. 重新运行构建命令生成更新的 `cards.jsonl`

### 4. 配置进化使用知识

在 `benchmark/<task>/evolve.yaml` 中添加：

```yaml
knowledge:
  enabled: true           # 是否启用知识注入（默认 true）
  dir: knowledge          # 相对于任务目录
  k: 4                    # 每次检索返回的卡片数
  max_per_category: 2     # 每类别最多卡片数
```

### 5. 禁用知识注入

如果需要与 PR #2 路径对比（无知识注入），设置：

```yaml
knowledge:
  enabled: false          # 禁用知识注入
```

禁用后：
- `knowledge_tokens: 0`
- prompts 与 PR #2 路径相同
- `cards_offered` 和 `cards_adopted` 都为 0

### 5. 运行 mock 进化验证

```bash
cd /workspace
python3 -c "
from pathlib import Path
from faultevolve.cloud.engine import run_local_evolution
import json

result = run_local_evolution(
    task_dir=Path('benchmark/hdd_mvp'),
    mock=True,
    max_iterations=5,
)

summary = json.loads((Path(result['output_dir']) / 'run_summary.json').read_text())
print(f'cards_offered: {summary.get(\"cards_offered\", 0)}')
print(f'cards_adopted: {summary.get(\"cards_adopted\", 0)}')
"
```

## 成功检查

运行以下命令验证知识注入工作正常：

```bash
# 1. 验证卡片 schema
python skill/fe-knowledge-injection/scripts/build_cards.py \
  --validate-only benchmark/hdd_mvp/knowledge/cards.jsonl
# 预期: "Validation PASSED: N cards OK"

# 2. 检查卡片数量
wc -l benchmark/hdd_mvp/knowledge/cards.jsonl
# 预期: >= 40 张卡片

# 3. 运行 mock 进化并检查指标
python3 -c "
from pathlib import Path
from faultevolve.cloud.engine import run_local_evolution
import json

result = run_local_evolution(
    task_dir=Path('benchmark/hdd_mvp'),
    mock=True,
    max_iterations=3,
)

summary = json.loads((Path(result['output_dir']) / 'run_summary.json').read_text())
assert summary.get('cards_offered', 0) > 0, 'ERROR: cards_offered should be > 0'
print('SUCCESS: Knowledge injection working')
print(f'  cards_offered: {summary[\"cards_offered\"]}')
print(f'  knowledge_tokens: {summary.get(\"knowledge_tokens\", 0)}')
"
```

## 发现卡命名空间 `D-*`

- 运行期晋升卡写入 `<runs_dir>/knowledge/discovered_cards.jsonl`，**不**写入仓库 `cards.jsonl`
- 加载顺序：`knowledge_dir/cards.jsonl` → `extra_card_paths`（含同 run 的发现卡路径）
- id 与文献卡冲突时，后加载文件中的重复 id 被拒绝（`load_all_cards` 返回 error）
- 字段：`evidence: run`；血统字段 `grade`、`prereg_hash`、`confirms`/`revises` 由 loader 忽略但保留在 jsonl
- 人工固化进仓库需单独 PR 审查
- **机制卡** `D-<exp>-M<nnn>`：`priority=1`、`grade=established`、`source_ids` 含 `mechanism:<id>`；与 KD1 发现卡共用 `discovered_cards.jsonl`，自动进入检索与 `card_stats`；**不**写入 `cards.jsonl`

**成功检查**：`load_all_cards(knowledge_dir, [discovered_path])` 无 error，文献卡仍为 51 张（HDD MVP）。

## 故障处理

### `cards_offered: 0`

1. 检查 `evolve.yaml` 是否包含 `knowledge.dir` 配置
2. 验证知识目录存在：`ls benchmark/<task>/knowledge/cards.jsonl`
3. 验证卡片有效：`python scripts/build_cards.py --validate-only ...`

### 验证失败

```bash
# 查看具体错误
python skill/fe-knowledge-injection/scripts/build_cards.py \
  --validate-only benchmark/<task>/knowledge/cards.jsonl 2>&1

# 常见问题：
# - 缺少必填字段（id, title, category, claim, source_ids, tags）
# - category 不在有效列表中
# - priority 不是 1-5 的整数
# - 重复的卡片 ID
```

### 卡片未被采纳

检查 LLM 输出是否包含 `<adopted_cards>` 标签。MockLLM 会自动生成此标签。

## 知识卡片 Schema

```json
{
  "id": "FE01",                    // 唯一标识符（必填）
  "title": "Window deltas",        // 标题（必填）
  "category": "feature_engineering", // 类别（必填，见下方列表）
  "claim": "核心声明",             // 核心声明（必填）
  "rationale": "原理说明",         // 原理（可选）
  "applicability": "适用条件",     // 适用性（可选）
  "expected_effect": "Large",      // 预期效果（可选）
  "risk": "潜在风险",              // 风险（可选）
  "source_ids": ["paper1"],        // 引用来源（必填，可为空列表）
  "tags": ["smart_5", "trend"],    // 标签（必填，用于检索匹配）
  "impl_hint": "实现建议",         // 实现提示（可选）
  "priority": 1,                   // 优先级 1-5（可选，默认 3）
  "evidence": "paper"              // 证据类型（可选）
}
```

### 有效类别

- `feature_engineering`：特征工程方法
- `model`：模型选择和配置
- `evaluation`：评估和验证方法
- `pitfalls`：常见陷阱和避免方法
- `thresholding`：阈值选择策略
- `labeling`：标签处理和数据增强
- `imbalance`：类别不平衡处理
- `transfer`：迁移学习和域适应
- `ensembling`：集成学习方法

## 检索算法

检索得分计算公式：

```
score = 0.3 * priority_score
      + 0.3 * tag_match_score  
      + 0.25 * bayesian_mean_score
      + 0.15 * exploration_bonus
```

排除规则：
- 当前分支已证伪的卡片
- 祖先节点已采纳的卡片

多样性约束：
- 每个类别最多返回 `max_per_category` 张卡片

## 反馈更新

当节点评估完成后：

1. 从 LLM 输出解析 `<adopted_cards>ID1,ID2</adopted_cards>`
2. 计算分数变化 `delta = child_score - parent_score`
3. 更新 `card_stats` 表统计
4. 如果假设被证伪，将采纳的卡片标记为当前分支的"已证伪"

## 卡片与错例画像关联

- `operators.fn_keywords: true` 时，引擎把父节点 `metric.analysis.fn_groups` 的前 `fn_keyword_groups` 组关键词写入检索上下文 **`profile_keywords`**（不并入 `keywords`，避免改变 adapter 空关键词时的回退路径）
- `operator == inject` 且 bandit 选中时：只保留 1 张卡片，prompt 标题为「必须采纳」，`<adopted_cards>` 预填该卡 ID；若 LLM 未声明，引擎在评估前自动补齐 `adopted_cards`（与 `child.card_ids` 一致）

## 注意事项

- 卡片内容应基于可验证的文献或基准测试结果
- 避免在卡片中包含可能导致过拟合的具体参数值
- 确保 `impl_hint` 遵守任务的硬约束（如禁用的关键词）
- arXiv/Semantic Scholar 自动检索功能尚未实现，卡片需手工策划

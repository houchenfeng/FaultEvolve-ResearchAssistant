# 文献证据到可执行假设

## 检索与筛选

根据问题、数据类型、主要瓶颈和约束组合查询：领域/器件 + 预测任务 + 方法；再按错例和约束补查，例如低误告约束下召回、时间漂移、样本不平衡、轻量模型。记录查询、日期、检索工具、纳入/排除理由。优先原始论文、作者材料、官方数据与评估说明；核对标题、作者、年份、DOI/URL、版本以及实际读到的范围。

可用浏览工具时实际检索并访问来源，不能凭模型记忆生成引用。已有本地文献可直接读取；未获取全文只写摘要支持的结论。无网络时继续整理可访问材料，将未核实引用列为待验证，不填虚构 DOI、实验结果或页码。用户使用 Zotero 时才按环境中可用的 Zotero 能力访问其库，不默认要求该工具。

产出 `literature/search-log.jsonl`、`sources.yaml`、`references.bib` 和 `review.md`。后两者分别服务引用和综合比较；没有论文类来源时不强制伪造 BibTeX。来源记录至少含 `source_id,title,authors,year,url,accessed_at,read_scope,evidence_locator,status`，其中 evidence_locator 指章节、页码或明确段落位置。

综述围绕“问题、数据与划分、方法、关键假设、成本、局限、对本任务的可迁移动作”，不只罗列论文摘要。对相互冲突的结果保留条件差异；高引用量不替代适用性。

## 建立假设和知识卡片

每个研究假设记录：

- `hypothesis_id`、`source_ids`：来自哪些已核实来源，或标为原创/专家假设。
- 机制、输入条件、预期改变的指标、潜在负作用。
- 最小可执行改动、所需对照、什么结果会推翻假设。
- 初始研究路线/岛屿、估计成本及当前证据等级。

写成任务 `knowledge/cards.jsonl`，复用当前 loader 的格式：

```json
{"id":"H01","title":"训练窗口趋势特征","category":"feature_engineering","claim":"在指定数据条件下检验趋势是否改善排序质量","source_ids":["已核实的来源ID"],"tags":["temporal","trend"],"rationale":"来源支持的机制及尚需验证的部分","applicability":"观测窗口及数据质量条件","risk":"短历史噪声与时间泄漏","impl_hint":"仅在 cutoff 以前提取差分，配对比较有/无趋势特征","priority":3,"evidence":"paper"}
```

上面是格式示意，不能原样作为核实后的文献卡。必需字段为 `id,title,category,claim,source_ids,tags`；类别取 `feature_engineering/model/evaluation/pitfalls/thresholding/labeling/imbalance/transfer/ensembling`。保留原始证据位置在来源文件中，卡片以概括和可实施建议为主，避免复制长篇原文。论文的数值结果不能作为当前数据集的性能承诺。

使用仓库真实 loader 检查，并由宿主核对 source_ids 能解析、ID 无重复、引文与主张匹配：

```python
from pathlib import Path
from faultevolve.knowledge.loader import load_all_cards
cards, errors = load_all_cards(Path("<任务目录>/knowledge"))
assert not errors, errors
assert cards, "知识库为空"
```

配置 `knowledge.enabled: true`、`knowledge.dir` 指向冻结知识目录、`knowledge.k` 和 `max_per_category` 控制上下文。`dir` 相对 task_dir 解析，也支持绝对路径；冻结时记录来源和内容哈希，不在恢复期间替换其内容。

## 用结果反向更新文献理解

检查实际 `knowledge_injected` 事件及 offered/adopted 统计，把候选、卡片与本地指标变化关联。卡片未注入先检查路径和检索匹配；已注入但无收益时结合实现、数据条件和对照判断，不能由一次失败断言论文错误。

连续同类失败、所有路线停滞或出现未解释的错例时定向补查文献，并形成新假设。改变冻结知识包需创建关联新 run；实验经验使用 `evidence: run` 并引用真实节点/评估，不冒充论文证据。既有卡片预算和检索统计属于引擎；宿主浏览与阅读的耗时/Token 单独登记，缺少计量则记未知。

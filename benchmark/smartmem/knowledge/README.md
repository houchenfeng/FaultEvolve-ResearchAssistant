# SmartMem 知识包

SmartMem（DRAM 可纠错错误流预测不可纠错故障）任务的知识数据目录。
这里放的是**领域数据**，不是代码：通用加载器 `src/faultevolve/knowledge/loader.py`
原样复用，本目录只负责卡片、出处、专家说明与打包校验脚本的入口。

## 目录内容

| 文件 | 作用 | 由谁读 |
|---|---|---|
| `cards.jsonl` | 23 张知识卡，一行一张 | 引擎（检索后注入 prompt） |
| `sources.yaml` | 11 条文献/页面/运行记录，卡片 `source_ids` 的外键 | 复核者 |
| `expert.md` | 证据从哪来、哪些判断还不算知识、开放问题 | 组内成员与评委 |
| `README.md` | 本文件：约定、校验命令、当前缺口 | 第一次接触这个包的人 |
| `../knowledge_check.py` | 打包校验（不在本目录，因为它是要被 import 的模块） | 测试与人工复核 |

## 卡片约定

- `id` 必须是 `SM-<类别缩写>-<序号>`，与 HDD 线的 `FE*`/`M*`/`T*` 和发现卡 `D-*` 隔离。
- 必填语义字段：`claim / rationale / applicability / expected_effect / risk / impl_hint /
  source_ids / tags`。缺任意一条都不算一张可用的卡：没有 `applicability` 就不知道什么时候别用，
  没有 `risk` 就不知道它什么时候会伤害分数。
- `evidence` 只允许 `user_run / official / paper / expert / benchmark / llm_hypothesis`。
  没有出处的猜测只能标 `llm_hypothesis`，不许伪装成文献结论。
- 标签是检索接口：`CardRetriever` 靠 `tags` 与上下文的关键词交集打分，
  所以标签用工程动词与列名（`temporal`、`window`、`burst`、`parity`、`dq`、`censoring`…），
  不写只有作者看得懂的缩写。

## 校验

```text
python -m benchmark.smartmem.knowledge_check          # 有问题逐行打印，退出码 1
python -m pytest tests/test_smartmem_knowledge.py -q  # 规则本身是否还活着
```

第二条是关键：每条校验规则都有一个"故意破坏它"的测试，删掉规则就会红。

## 明确不具备的能力（读之前先知道）

1. **这个包不评分。** 本地评测器（`benchmark/smartmem/evaluator.py`，2026-10-04 起）只给**暂定口径**
   的分数：判分窗与"一台机器只计一次、命中必须落窗"按官方**页面原文**实现为默认，但官方**评分源码**
   尚未拿到，所以口径仍是暂定，**本目录没有任何卡片声称在本数据集上验证过指标**。
   卡片给出的"预期影响"是文献里的口径，不是我们的实测。
2. **旧尝试的数字不可直接比较。** 唯一被允许引用的历史数字来自另一套协议，
   对应卡片 `SM-PF-001` 与 `SM-EV-002` 写明为什么不能拿它宣称提升。
3. **时间边界与时区口径未经确认。** 涉及告警时刻减法的卡片（lead、horizon、删失）
   目前是 `official` 出处 + 待确认适用条件，见 `expert.md` 第 5 节。
4. **官方榜单已关闭**，无法用提交校准绝对分数；一切分数只以本地 evaluator 为准，而它输出的每个数字
   都带 `metric_spec_status: provisional`，换个判分细则就不是同一个数（同一份 oracle 提交在
   `sn-in-window` 下 1.0、在 `each-alarm` 下 0.082）- 官方评分源码没到手之前，
   任何"提升到多少分"的表述都不成立。

## 怎么加卡

1. 先在 `sources.yaml` 登记出处（必须是真实读到过的东西，带 URL、读取方式与日期）；
2. 再写卡，`source_ids` 指过去；
3. 跑一次校验命令；
4. 只有当某个做法在**本仓协议**下被测过，才允许把 `evidence` 从 `paper` 升到 `user_run`，
   并在 `expected_effect` 里写清是哪把尺子。

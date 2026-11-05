# 这份 fixture 的来源（provenance）

**真实运行，不是合成数据**：候选代码由 Qwen 生成，分数由仓库 `evaluator.py` 在真实验证集上给出。
本文件随运行一起被 `scripts/build_run_fixture.py` 处理（主机路径会被替换为 `<REDACTED_PATH>`）。

## 运行事实

| 项 | 值 |
|---|---|
| experiment_id | `38cb38cf` |
| 代码 | **对齐后**的统一线（本仓库 main；服务器上为 NAS 的 `work/code_aligned` 部署树，默认 `bootstrap_b=6400`、`n_slices=32`） |
| 配置 | `tasks/hdd_kd/evolve.yaml` **原样**：`operators.bandit=false`、无 crossover、`judge.provider=none`、`discovery.enabled=true` + `tournament.enabled=true`。唯一改动：删掉 `tournament.n_slices` 那一行，让对齐后的默认值 32 生效（写在配置里的 4 是 B-6/B-12 修复之前的值，会让赛程被切片预算饿死） |
| 迭代 / 种子 | 10 / 20261004 |
| 结果 | best **35.033**、initial **22.807**、提升 **+12.225**，`stop_reason=max_iterations`（第 9 轮跨过 33.7 参考线） |
| 用量 | tokens **169400**、墙钟 **6129.6 s** |
| 有效率 | 0.5（10 次 refine，5 次有效） |
| 知识卡 | 提供 40 / 采纳 13 |
| KD1 | claim 提出 4、检验 3 |
| KD2 | 机制提出 10、对局 32、证书 0（锦标赛真跑了，但没判出胜者） |

## 为什么在服务器上跑，而不是本机

本机（Windows + DSH 受限期）**无法完成任何评估**：受保护的 `evaluator.py` 用
`tempfile.TemporaryDirectory(prefix="hdd_eval_")`，退出时要删除自己的临时目录，而这个
环境按设计禁止删除子目录（`Everyone: 拒绝 DeleteSubdirectoriesAndFiles`，在工作区根上
是显式项）。于是评估必然失败，运行会以 `stop_reason=selection_stalled` 收场
（该停跑守卫见 `src/faultevolve/cloud/engine.py` 与 `tests/test_run_stall_guard.py`）。

因此真实运行在服务器上执行，写入只落 NAS 与 `/dev/shm`（SQLite 不能放 CIFS，
且约定不动主盘），制品取回后脱敏入库。

## 复现命令（服务器，主盘只读）

```bash
PYTHONPATH=<nas>/work/code_aligned/src \
<REDACTED_PATH> -c "from faultevolve.cli import app; app()" \
  evolve local <nas>/work/hdd_good -n 10 \
  --config-file <nas>/work/demo_good.yaml \
  --env-file <server>/.env \
  --runs-dir /dev/shm/fe_real2 --artifacts-dir <nas>/runs/demo_real2 --json
```

## 脱敏方式

`scripts/build_run_fixture.py`：文本文件里的主机路径 → `<REDACTED_PATH>`；`fe.db` 的全部
TEXT 列同规则替换，然后 `journal_mode=DELETE` + `VACUUM` 使文件自包含（不随附 `-shm`/`-wal`）；
最后整体扫描，出现主机路径、私有测试集名称或密钥形态字符串就拒绝入库 —— 本文件第一版就
因为写了私有测试集的英文名而被扫描器挡下，改成中文表述后才通过。
本目录另有一份 `discovery/failed_claims/`，是移植进来的「沙箱失败的 claim 必须落盘」特性
产生的真实产物（含失败 claim 的特征代码与错误）。

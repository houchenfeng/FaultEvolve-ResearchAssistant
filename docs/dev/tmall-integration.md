# 天猫黑客松算法与前端整合

## 来源与范围

- 目标仓库：`houchenfeng/FaultEvolve-ResearchAssistant`，基线 `5020b229e3235b48c5a5a765cc8890ef0a509ef2`。
- 算法来源：`houchenfeng/FaultEvolve-huawei` 的 `codex/three-island-real-runs`，版本 `5ee57ba89b24866ed014e3bf6eb8ff16bba2e123`。
- 以源码快照整合算法、数据适配、统一工作流、API 1.15.0、前端及相应测试、文档、实验聚合证据；不导入来源仓库的提交历史。
- 保留初赛 README 历史材料、视频、展示回放与评估基线。没有修改 HDD 的 evaluator、init、problem、prompt 或数据文件。

## 前端变化

1. 任务创建页新增多岛协作和分层参数调优开关，复用服务端配置校验；修改配置后旧校验状态失效。
2. 工作台接入各岛搜索树、预算、策略交换和工作流状态；结果页接入分层搜索结果与方案对比，兼容旧单树回放。
3. `/overview/showcase` 为独立比赛展示页：四组归档实验、四种指标切换、三岛分工与演化步骤交互、全屏、证据下载及手机布局。
4. 归档实验与机制示意明确分开；不会把机制示意呈现为实时运行轨迹。
5. 工作流文件锁支持 Windows 与 POSIX。

## 启动展示（Windows PowerShell）

需要 Python 3.12、Node.js 22+ 和 pnpm 9.15.9。

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[web,dev]"
.venv\Scripts\python.exe scripts/showcase_serve.py --port 8011
```

另开终端：

```powershell
cd web
pnpm.cmd install --frozen-lockfile
$env:VITE_API_PROXY_TARGET = 'http://127.0.0.1:8011'
pnpm.cmd dev --host 127.0.0.1 --port 4318
```

访问 `http://127.0.0.1:4318/overview/showcase`。展示后端将初赛回放复制到临时目录；静态展示无需模型密钥。真实演化需另行配置模型服务、任务数据和运行预算。Linux/macOS 使用 `.venv/bin/python`，环境变量用对应 shell 语法。

## 实验展示口径

| 方案 | ROS | F1 | AUPRC | 归档耗时 |
| --- | ---: | ---: | ---: | ---: |
| 初始逻辑回归 | 22.81 | 24.94% | 19.55% | 1.86 s |
| 初赛历史最佳 | 38.14 | 39.33% | 36.12% | 7.67 s |
| 三岛 ML | 40.72 | 42.44% | 37.15% | 6.11 s |
| TCN + 树模型 | 42.53 | 43.76% | 40.27% | 25.80 s |

来源：`experiments/hdd_dl/evidence/verified_search_20261021/`。共 48 个候选，以上为不同阶段方案的归档对照，不是同一轮实时曲线或多岛消融。最佳方案增加了运行耗时；验证集参与搜索，尚未独立复验。没有在本次整合中重跑付费 LLM 或 GPU 实验。

使用 `node scripts/export_showcase.mjs` 重新生成网页证据；`node scripts/export_showcase.mjs --check` 检查一致性。前端 JSON 仅含聚合指标和出处。

## 验证方式

- `cd web; pnpm.cmd build`：类型检查和生产构建。
- `pnpm.cmd test -- --maxWorkers=2`：前端单元测试。
- 启动上述两项服务后，在 `web` 目录执行 `node scripts/verify-showcase.mjs`：验证桌面/手机布局、指标切换、机制交互、下载、历史回放与浏览器错误，并更新截图。
- 根目录执行 `.venv\Scripts\python.exe -m pytest tests/ -q`：后端完整测试。Windows 建议设置 `$env:PYTHONUTF8='1'`；符号链接安全测试需要对应系统权限。
- 本次后端重点验证多岛契约、隔离与交换、预设合并、回放、工作流 API 和文件锁。完整套件包含耗时实验，具体执行结果见提交说明，不把局部回归等同于完整通过。

生产构建仍有单包超过 500 kB 的提示；不影响本次构建和演示，可在后续按路由拆包。

### 本次执行记录

前端原完整回归 765 通过、3 跳过；新增展示页与算法配置交互 4 项通过，配置相关回归 60 项通过，生产构建通过。浏览器桌面与手机交互、证据下载、初赛回放和 API 契约一致性通过。

后端扩展回归 180 通过、1 跳过、2 失败：两项失败均涉及 Linux CPU affinity（Windows 无 `sched_getaffinity`，以及 `n_jobs=-1` 的 CPU 数量约束）。Windows 当前只设置线程环境与本进程原生线程池，不能保证候选子进程按 Linux 的 CPU affinity 方式限核；需要严格 CPU 配额的真实实验请在 Linux 运行。符号链接权限测试在本机跳过，Linux 上仍执行。完整 2168 项套件未全部执行完成，不宣称完整通过。

初赛的 `benchmark/*/evolve.yaml` 预算仍保留；前端使用新版服务端预设，专项实验参数见 `examples/` 与 `experiments/`。导入材料的差异检查仍包含历史 fixture 空白字符及文档内 SEARCH/REPLACE 格式示例，并非未解决的合并冲突。

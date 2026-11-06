# 交接：本地-云端混合模式演示（平板机房孪生 + 本地 GPU 评估器）

- 分支：`feat/edge-hybrid-demo`（基于 `5020b22`，与 `feat/evobot-demo` 互相独立）
- 代码提交：`2c2322c feat(edge): local-cloud hybrid demo with tablet data-hall twin`
- 本文档：同分支的下一个提交
- 日期：2026-11-07

## 1. 这是什么

把进化工作台从"纯云端"扩展为"本地-云端混合"演示，回答一个问题：**数据不出域，云端进化出的算法在本地真实数据上是否明显更好。**

| 部分 | 运行位置 | 真实 / 回放 |
| --- | --- | --- |
| 机房 3D 孪生，300 块 HDD，推送 SMART 遥测 | 安卓平板（APK）或浏览器 | 遥测数据取自公开 val 切分的真实盘，按种子重排时间 |
| 本地评估器：进化前 `init.py` vs 进化后 `4016914b`，官方 `evaluator.py` + GPU 配对 bootstrap | 笔记本 | **真实计算** |
| 云端进化轨迹 22.81 → 40.72 | 服务器运行 `hdd_mvp_formal2b_20261009` | **回放**（读取已落盘的 tree.json，不调用 LLM） |
| 回传给云端的数据包 | 笔记本 → 云端 | 白名单闸门真实执行，只放行标量分数 |

## 2. 已验证的结果（2026-11-07，RTX 3060 笔记本）

**平板数据流（截止日第 14 天打分，第 15–21 天观察真实故障）：**

| | 进化前 init.py | 进化后 4016914b |
| --- | --- | --- |
| 10 块真实故障中提前预警 | 2 | 6 |
| 误报 | 2 | 2 |
| 截止日打分耗时（两个模型合计） | 0.57 s | |

**完整验证集（官方 evaluator.py，30754 块盘）：**

| 指标 | 进化前 | 进化后 |
| --- | --- | --- |
| ROS 综合分 | 22.81 | 39.38 |
| 召回率 | 33.6% | 53.2% |
| 精确率 | 19.8% | 31.7% |
| Recall@FAR≤1% | 27.4% | 47.6% |
| 误报率 | 0.34% | 0.29% |

- GPU 配对 bootstrap：20000 次重采样耗时 0.74 s；ΔF1 95% CI [0.110, 0.188]；P(进化后更好) = 100%。
- 服务器上同一程序得分 40.72，本地 39.38。差异来自 Windows 上 LightGBM 4.6 与服务器环境不同，不是数据泄漏。
- 云端回放：3 个岛（performance / miss_alert / efficiency），95 个候选，10.8M tokens，46 h。最佳路径为 `aee213c1`(22.81) → `5450dd24`(36.16) → `a096a7fa`(38.87) → `4016914b`(40.72)。

## 3. 数据流

```
平板 (edge-tablet, Three.js)
  │ WebSocket ws://<笔记本IP>:8011/api/edge/ws
  │  hello(盘位清单+字段) → telemetry(day 1..14) → failure(day 15..21) → end
  ▼
笔记本 FastAPI (faultevolve.edge.hub.EdgeHub)
  ├─ 第 14 天：models.ModelService 在本机训练/缓存两个模型 → 打分 → alarms 回推平板
  ├─ POST /api/edge/evaluate：evaluator.py 跑两个程序 + gpu.paired_bootstrap
  └─ boundary.gate()：白名单字段放行，其余（序列号、SMART 行、逐盘分数、标签、权重）拦截并记录
  ▼
工作台 /runs/$runId/hybrid（轮询 /api/edge/*，展示设备、热力图、对比、GPU、云端回放、出域审计）
```

## 4. 代码地图

**后端 `src/faultevolve/edge/`**

| 文件 | 职责 |
| --- | --- |
| `paths.py` | 所有路径常量；数据根目录可用 `HDD_BENCH_DATA_ROOT` 覆盖，模型缓存目录可用 `FE_EDGE_CACHE` 覆盖（默认 `.fe/edge`） |
| `models.py` | `BaselineModel`（复刻 init.py：截止日快照 + 逻辑回归）、`EvolvedModel`（复刻 4016914b：14 天窗口特征 + 3 折 × 2 配置 LightGBM 集成 + CI 下界阈值）、`ModelService`（后台线程训练，按程序 sha256 缓存 pickle） |
| `hub.py` | `EdgeHub` 单例 `HUB`：WebSocket 协议、打分、故障统计、事件日志、内置模拟器、完整评估线程 |
| `gpu.py` | `gpu_status()`（nvidia-smi），`paired_bootstrap()`（torch Poisson bootstrap，无 CUDA 时退回 CPU） |
| `boundary.py` | `WHITELIST` 与 `gate()`：只放行白名单内的标量 |
| `cloud.py` | 读取 `showcase/edge/hdd_mvp_formal2b_20261009/` 生成回放时间线和最佳路径 |
| `../_winruntime.py` | Windows 下优先加载系统版 MSVC 运行库（见第 7 节），由 `faultevolve/__init__.py` 调用 |
| `../webapi/routes/edge.py` | HTTP / WebSocket 路由；`edge-tablet/dist` 存在时挂载为 `/edge-tablet` |

**接口**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/edge/state` | 全量状态快照（设备、数据流、盘位网格、故障、对比、上传包、事件、局域网地址） |
| GET | `/api/edge/gpu` | GPU 实时读数 |
| GET | `/api/edge/cloud` | 云端回放 |
| GET | `/api/edge/evaluation` | 完整评估结果 |
| POST | `/api/edge/evaluate` | 启动完整评估（约 20 s） |
| POST | `/api/edge/models/prepare` | 预热两个模型（首次约 17 s，之后读缓存） |
| POST | `/api/edge/simulate?day_seconds=1` | 不用平板，在后端内部模拟一次完整回放 |
| WS | `/api/edge/ws` | 平板上行：`hello / telemetry / failure / end`；下行：`welcome / ack / alarms / need_hello / error / summary` |

**平板 `edge-tablet/`（Vite + TypeScript + Three.js + Capacitor 7）**

| 文件 | 职责 |
| --- | --- |
| `src/scene.ts` | `DataHall`：10 个机柜半圆排布、面向中心的"本地评估域"节点；InstancedMesh 盘位/LED、Bloom、数据包飞线、故障抽出 + 红光 + 镜头聚焦、空闲时镜头轻摆 |
| `src/hud.ts` | 时钟、链路状态与地址设置、统计、上行柱状图、事件流、硬盘卡片、结束总结 |
| `src/main.ts` | 回放控制（每天 1.5 s）、断线重连后补发握手和已过天数、`?autostart=1` |
| `src/link.ts` | WebSocket 自动重连。地址优先级：`?server=` → localStorage → 同源 → 构建期 `VITE_EDGE_SERVER` |
| `public/replay.json` | 由 `scripts/edge_build_replay.py` 生成（种子 2026；300 块盘，其中 10 块真实故障盘） |
| `android/` | Capacitor 生成的工程。已改：横屏、沉浸式全屏、常亮、允许明文 ws、阿里云 Maven 镜像、腾讯云 Gradle 镜像 |

**工作台 `web/`**

- `src/routes/RunHybridPage.tsx` 与 `src/features/hybrid/*`：混合面板。`/api/edge/*` 不在 OpenAPI 契约快照里，因此 `edge-api.ts` 手写类型并直接用 fetch。
- `src/app/router.tsx` 新增 `hybrid` 子路由；`RunLayout.tsx` 新增"本地-云端混合"标签。
- `src/features/intake/DeploymentModeCards.tsx`：混合模式卡片改为可点击，跳转到 `/runs/hdd_mvp_showcase_c89e2a01/hybrid`。

## 5. 运行演示

```powershell
# 1) 仅首次，用管理员 PowerShell 放行端口
New-NetFirewallRule -DisplayName FaultEvolveEdge -Direction Inbound -Protocol TCP -LocalPort 8011 -Action Allow

# 2) 一键启动后端（0.0.0.0:8011）+ 工作台（5180），并打印平板应填的地址
powershell -ExecutionPolicy Bypass -File scripts\edge_demo.ps1
```

1. 平板与笔记本连同一 Wi-Fi，安装 `edge-tablet\release\FaultEvolve-EdgeTwin-debug.apk`，或在平板浏览器打开 `http://<笔记本IP>:8011/edge-tablet/`。
2. 右上角显示"已接入本地评估域"后，点"开始回放"。
3. 笔记本打开 `http://127.0.0.1:5180/runs/hdd_mvp_showcase_c89e2a01/hybrid`，点"运行本地完整评估"。
4. 没有平板时：在面板点"本机模拟回放"，或 `POST /api/edge/simulate`。

APK 预置的默认地址是 `10.61.9.235:8011`（构建时的校园网 IP），IP 变了在平板"设置"里修改即可，不必重新打包。

## 6. 构建

**平板网页 / APK**

```powershell
cd edge-tablet
pnpm install
$env:VITE_EDGE_SERVER = "<笔记本IP>:8011"   # 可选，作为 APK 的默认地址
pnpm build
pnpm exec cap sync android

# Android 构建工具不接受中文路径，先把目录映射到纯英文盘符
subst X: "G:\自进化agent\FaultEvolve-ResearchAssistant\edge-tablet"
cd X:\android
$env:JAVA_HOME = "E:\devtools\jdk21"
$env:ANDROID_HOME = "E:\devtools\android-sdk"
$env:GRADLE_USER_HOME = "E:\devtools\gradle-home"
.\gradlew.bat assembleDebug
# 产物 X:\android\app\build\outputs\apk\debug\app-debug.apk → 复制到 edge-tablet\release\
subst X: /D
```

- `*.apk`、`dist/`、`node_modules/`、Android `build/` 都在 `edge-tablet/.gitignore` 中，APK 不入库。
- 目前是 debug 签名，正式分发需另配 release 签名。

**重新生成 replay.json**：`.venv\Scripts\python.exe scripts\edge_build_replay.py`。只读取公开 val 切分和 `eval_only/val_labels.csv`，不读取 holdout。

## 7. 环境要点

| 项 | 状态 / 做法 |
| --- | --- |
| Python | 仓库内 `.venv`（基于 Anaconda 3.12）。全局 Anaconda 有 NumPy 2 与 numexpr/bottleneck 冲突，不要直接用 |
| LightGBM | Windows 必须 `<4.7`（4.7.0 会访问冲突崩溃）；当前 4.6.0，numpy 2.5.3、pandas 3.0.6 与服务器一致 |
| PyTorch | 2.9.1+cu126，wheel 来自阿里云镜像（`E:\devtools\wheels\`）。官方源在本网络下几乎下载不动 |
| MSVC 运行库 | Anaconda 自带 14.29 版，会导致 torch 的 `c10.dll` 报 WinError 1114。`faultevolve/_winruntime.py` 在包入口预加载 System32 版本解决；该预加载必须早于 numpy/pandas 导入 |
| WebSocket | uvicorn 需要 `websockets`，缺少时平板会一直显示"正在连接" |
| 依赖声明 | `pyproject.toml` 新增可选组 `edge`：websockets、torch，以及 Windows 上的 `lightgbm<4.7` |
| 中文日志 | 启动后端前设 `PYTHONUTF8=1`（`edge_demo.ps1` 已设置），否则 evaluator 子进程输出会有 GBK 解码错误 |
| Android 工具链 | JDK 21 在 `E:\devtools\jdk21`，SDK 在 `E:\devtools\android-sdk`（platform 35、build-tools 35.0.0，取自腾讯云镜像） |
| 代理 | Clash TUN（198.18.x）会接管流量；`lan_addresses()` 已排除 198.18/19 网段 |

## 8. 数据边界与仓库规则

- 白名单（`boundary.WHITELIST`）：candidate_id、validity、combined_score、f1_p10、auprc、recall_at_far、precision、recall、false_alarm_rate、run_time_s、noise_band、delta_vs_parent、p_improve、disks_monitored、failures_observed、caught、false_alarms。其余字段一律拦截，并在审计面板中标出字段名和大小。
- 没有修改 `benchmark/hdd_mvp/{evaluator.py, init.py, problem.md, prompt.md}` 和 `benchmark/hdd_mvp/data/`；没有读取 holdout。
- 分数只来自本地 evaluator；云端部分是对已落盘运行的回放，不产生新分数。
- 提交前做过密钥扫描，代码中没有密钥、跳板机口令或服务器地址。

## 9. 已知问题与待办

1. **工作区状态**：主工作区当前在 `feat/evobot-demo`，同时留有本演示文件的未提交副本（内容与 `2c2322c` 一致），以及另一个会话未完成的 `web/src/features/evodemo/*` 修改。后者目前让整个前端白屏（`TournamentScreen.tsx` 导入 `DEBATE_CAST`，`demo-script.ts` 没有导出），与本分支无关。切到本分支前，需先删除这些未提交副本，否则 git 会因"未跟踪文件将被覆盖"拒绝切换。
2. **没有自动化测试**：hub 协议、白名单闸门、bootstrap 都只做了端到端手工验证。建议优先补 `boundary.gate` 和 `EdgeHub.process` 的单元测试。
3. **前端契约**：`scripts/export_web_contracts.py` / `check_web_contracts.py` 在仓库中不存在，OpenAPI 快照和生成的客户端没有包含 `/api/edge/*`。
4. **模型训练依赖本机数据**：首次打分要在本机训练约 17 s（缓存于 `.fe/edge`），需要 `benchmark/hdd_mvp/data/public` 与 `eval_only` 存在。
5. **APK 仅 debug 签名**，默认地址写死为构建时的 IP。
6. **单设备**：`EdgeHub` 同一时间只按一个数据流处理；第二台平板发 `hello` 会重置当前数据流。
7. **杂项**：`~/.ssh/config` 里服务器 IP 仍是旧的 10.61.48.10（现为 10.61.48.59）；`G:\自进化agent\tmp\fe_ssh.py` 和 `tmp\install_android.ps1` 是临时脚本，可删除。

## 10. 远端自进化（跳板机 SSH，演示 / 真实运行）

在原有"回放云端轨迹"之外，新增真实的远端闭环：服务器负责选择父代、调用 LLM 生成候选；笔记本只负责评估，评估数据来自平板场景；两端之间只传代码和白名单分数。

```
笔记本 faultevolve.edge.remote ──SSH(跳板机)──▶ 服务器 scripts/edge_remote_evolver.py（setsid nohup 常驻）
   ▲  拉 candidates/<cid>.py                         │ 选父代 → Qwen / Codex 生成 → 写候选
   │  本地评估：平板场景(test 切分) + 完整 val + GPU bootstrap
   └─ 写 results/<cid>.json（boundary.gate 之后的白名单标量）──▶ 读分数 → 更新种群 → 下一代
```

| 模式 | 服务器做什么 | LLM |
| --- | --- | --- |
| 演示 `demo` | 种子 `init.py`，依次回放 `rule_baseline.py`、`4016914b.py` | 不调用 |
| 真实 `real` + `qwen` | 种子 `init.py` + `4016914b.py`，每代以最佳（25% 概率次优）为父代调用 DashScope，流式读取 | `qwen3.8-max-0902`（`FE_QWEN_MODEL`） |
| 真实 `real` + `codex` | 同上，但提示词写入 `llm_requests/`，由笔记本本地 `codex exec`（ChatGPT 登录）回答到 `llm_responses/` | 本机 Codex |

**配置**：仓库根目录 `.env`（已在 `.gitignore`，模板见 `.env.example`）：`FE_SSH_JUMP`、`FE_SSH_JUMP_PASSWORD`、`FE_SSH_TARGET`、`FE_SSH_TARGET_PASSWORD`、`FE_REMOTE_ROOT`（会话目录，NAS 上即可）、`FE_REMOTE_PYTHON`、`DASHSCOPE_API_KEY`、`FE_QWEN_MODEL`、`FE_LLM_PROVIDER`。Qwen key 只写到服务器本机 `~/.fe_edge/<会话>.env`（权限 600），不落 NAS。

**接口**

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/edge/llm` | Qwen key / 模型、Codex 是否安装与登录 |
| POST | `/api/edge/remote/probe` | 经跳板机探测服务器：延迟、GPU、Python、DashScope 可达性、主机指纹 |
| POST | `/api/edge/remote/start` | `{"mode":"demo"|"real","provider":"qwen"|"codex","generations":N}` |
| GET | `/api/edge/remote` | 会话状态、远端种群/最佳、每个候选的本地评估（平板命中、GPU 峰值、bootstrap）、两端事件 |
| POST | `/api/edge/remote/stop` | 写 `STOP`，远端在当前步骤后退出 |

**本地评估（`edge/local_eval.py`）**：平板实时数据流结束后（`phase=done`）用它，否则用平板同款 `replay.json`。场景被落成 `test` 切分，任何遵守 CLI 契约的候选程序都能直接打分；完整 val 按 `evaluator.py` 的同一套规则计算 ROS；GPU 配对 bootstrap 默认 10 万次重采样，并用 nvidia-smi 采样记录评估期间的 GPU 峰值利用率与显存。

**工作台**：`/runs/hdd_mvp_showcase_c89e2a01/hybrid` 顶部"远端自进化（跳板机 SSH）"面板：模式切换、提供方选择、代数、启动/停止、探测、候选表与两端事件流。

**Codex 本地登录**：`npm i -g @openai/codex` → `codex login`；`/api/edge/llm` 显示已登录后，面板里即可选 Codex。测试时可用 `FE_CODEX_CMD` 指向替身命令。

**注意**：SSH 目前用密码 + `known_hosts=None`（探测接口返回两端主机指纹供核对），正式环境应改为密钥并固定 known_hosts。本机 8011 被旧版演示服务占用时，用 `scripts\edge_demo.ps1 -ApiPort 8012`，平板"设置"里同步改端口。

## 11. 验收清单

- [ ] `scripts\edge_demo.ps1` 能启动，`GET /api/edge/state` 返回 200
- [ ] 平板连上后显示"已接入本地评估域"，回放结束总结为进化前 2/10、进化后 6/10
- [ ] 面板"运行本地完整评估"显示 ROS 22.81 → 39.38，GPU 一栏显示显卡名称
- [ ] 出域审计中 `serial_numbers` / `smart_rows` / `per_disk_scores` / `per_disk_predictions` 被标为拦截
- [ ] 云端回放显示 22.81 → 40.72，并标注"回放"

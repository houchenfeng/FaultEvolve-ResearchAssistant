# FaultEvolve 真实运行手册：平板 ↔ 本机 GPU ↔ 远端自进化

本文是"混合云实测"真实运行的完整步骤与实测记录。三端分工：

| 端 | 角色 | 数据 |
|---|---|---|
| 安卓平板（机房数字孪生 APK） | 推送每日 SMART 遥测，接收并显示告警 | 遥测上行、告警下行 |
| 笔记本（本地评估域） | 暂存平板场景，在本机运行候选程序，GPU 配对 bootstrap，白名单出域 | 原始数据与标签永不出本机 |
| GPU 服务器（经跳板机 SSH） | 运行 `scripts/edge_remote_evolver.py`，调用 Qwen / Codex 逐代生成候选 | 只收到 ROS、捕获数、误报数、失败类型等标量 |

---

## 1. 准备

### 1.1 本机环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[web,edge]"
pip install torch --index-url https://download.pytorch.org/whl/cu126   # GPU 评估
cd web; pnpm install --frozen-lockfile; cd ..
```

确认 GPU 可用：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

### 1.2 `.env`（不提交 Git）

```dotenv
DASHSCOPE_API_KEY=sk-...                 # Qwen 密钥
FE_LLM_PROVIDER=qwen                     # 或 codex
FE_QWEN_MODEL=qwen3.8-max-0902
# FE_QWEN_THINKING=0                     # 默认关闭思考模式；开启后单候选 >10 分钟
FE_SSH_JUMP=lt@<跳板机域名>:<端口>
FE_SSH_JUMP_PASSWORD=...
FE_SSH_TARGET=hcf@127.0.0.1:<隧道端口>    # 从跳板机看到的服务器地址
FE_SSH_TARGET_PASSWORD=...
FE_REMOTE_ROOT=/home/hcf/nas_public/hcf_data/faultevolve/work/edge_hybrid
FE_REMOTE_PYTHON=/home/hcf/miniconda3/envs/faultevolve/bin/python
```

服务器只需要 Python 3.10+ 标准库（进化器无第三方依赖）；Qwen 密钥在启动会话时写到服务器 `~/.fe_edge/<session>.env`（权限 600），会话结束可删除，不写入 NAS。

使用 Codex：本机 `npm i -g @openai/codex && codex login`，页面中 Codex 按钮变为可选；候选生成在本机 Codex 完成后经 SSH 写回服务器。

### 1.3 平板

1. 构建并安装 APK（地址填笔记本局域网 IP）：

   ```powershell
   cd edge-tablet; pnpm install
   $env:VITE_EDGE_SERVER="<笔记本IP>:8012"; pnpm build; npx cap sync android
   cd android; .\gradlew assembleDebug
   adb install -r app\build\outputs\apk\debug\app-debug.apk
   ```

2. 首次以管理员放行端口：

   ```powershell
   New-NetFirewallRule -DisplayName FaultEvolveEdge -Direction Inbound -Protocol TCP -LocalPort 8012 -Action Allow
   ```

3. 没有局域网时可走 USB：`adb reverse tcp:8012 tcp:8012`，APK 地址填 `127.0.0.1:8012`。

---

## 2. 启动

```powershell
# 终端 1：后端（含 /api/edge、平板 WebSocket、远端会话）
$env:PYTHONUTF8='1'; .\.venv\Scripts\python.exe scripts/showcase_serve.py --host 0.0.0.0 --port 8012

# 终端 2：前端
cd web; $env:VITE_API_PROXY_TARGET="http://127.0.0.1:8012"; pnpm dev --host 0.0.0.0 --port 5180
```

或一键：`powershell -ExecutionPolicy Bypass -File scripts\edge_demo.ps1 -ApiPort 8012`。

浏览器打开 <http://127.0.0.1:5180/>，在"确认"页选"混合云 · 真实运行"后确认；或直接打开 <http://127.0.0.1:5180/?stage=hybrid> 进入进化工作台的混合云模式。进化树每长出一个节点，弹出的"本地评估域"子窗口就同步展示它在平板场景上的本机评估。平板在线时每个节点都会走一轮平板交互：本机请求 → 平板上报 14 天 SMART 窗口 → 本机 GPU 评估 → 预警下发平板、平板 ACK → 白名单分数回传服务器（协议见 `src/faultevolve/edge/hub.py` 文件头）。平板 APK 需为本版本重新安装。

---

## 3. 运行步骤

### 3.1 检查三端

```powershell
Invoke-RestMethod http://127.0.0.1:8012/api/edge/state | Select -Expand device      # 平板 online=true
Invoke-RestMethod http://127.0.0.1:8012/api/edge/gpu                                 # 本机 GPU
Invoke-RestMethod http://127.0.0.1:8012/api/edge/llm                                 # key_present / codex 登录
Invoke-RestMethod -Method Post http://127.0.0.1:8012/api/edge/remote/probe           # ok=true，含服务器 GPU、Python
```

页面顶部三个 EvoBot 右下角的圆点分别对应平板在线、本机 GPU 可用、远端会话运行。

### 3.2 平板推送场景（评估数据来源）

在平板上点"开始回放 / 再来一次"。平板按天推送 300 块盘的 SMART 遥测（14 天历史 + 7 天观察），笔记本在截止日（第 14 天）给出进化前 / 进化后两组告警并下发，平板在 3D 机房里标出预警与真实故障。场景结束（`stream.phase = done`）后，本机评估就使用这份平板实际推送的数据。

没有平板时，页面"无平板时回放"按钮使用同一份 `replay.json` 代替。

### 3.3 启动远端自进化

页面"远端自进化"卡片：选择**真实运行** → 提供方 **Qwen**（或已登录的 Codex）→ 代数（建议 2–3）→ **启动远端进化**。等价 API：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8012/api/edge/remote/start -ContentType 'application/json' `
  -Body '{"mode":"real","provider":"qwen","generations":3}'
Invoke-RestMethod http://127.0.0.1:8012/api/edge/remote          # 轮询状态
Invoke-RestMethod -Method Post http://127.0.0.1:8012/api/edge/remote/stop
```

一次会话内部流程：

1. 本机经跳板机连接服务器，在 `FE_REMOTE_ROOT/<session>/` 部署进化器、配置、任务 prompt 与种子程序（`init`、`4016914b`），以 `setsid nohup` 脱离会话运行。
2. 服务器选父代（最优，25% 概率次优），把分数反馈与近期失败写进 prompt，流式调用 Qwen（思考关闭，单候选约 40–130 s），提取代码写到 `candidates/<cid>.py`。
3. 本机每秒轮询，下载新候选，在平板场景上运行，计算 ROS 与场景捕获 / 误报，并在 GPU 上做 10 万次配对 bootstrap；过 `boundary.gate` 后只把白名单标量写回 `results/<cid>.json`。
4. 服务器读取结果更新种群，进入下一代；全部代数完成或收到 `STOP` 后退出。

### 3.4 验收

| 验收点 | 看哪里 | 通过标准 |
|---|---|---|
| 本机 GPU 占用 | 页面"本机评估域 · GPU"进度条；候选卡片"GPU 峰值"；`nvidia-smi -l 1` | 评估期间有明显占用（候选评估峰值 100%） |
| 平板双向通信 | 平板右上"已接入本地评估域"、左下"上行遥测"柱状图、告警标记；`/api/edge/state` 的 `frames/bytes` | 遥测上行帧数增长，平板出现告警 |
| 服务器远端自进化 | 顶部服务器卡片"第 N/M 代"、服务器 GPU；三端事件中"服务器"条目；远端 `evolver.log` | 新候选逐个出现并被评估，状态最终 `done` |
| 数据边界 | 右侧"数据边界"卡片；`/api/edge/state` 的 `uploads[].blocked` | 拦截逐盘预测、标签、模型权重、评估器源码 |

---

## 4. 实测记录

### 4.0 2026-11-07 06:26（真实 Qwen 会话 `s20261107-062614`，三端全通）

隧道恢复后重测：平板实时推送场景（14 帧、4,101 行，捕获 2/10 → 6/10），服务器 2× RTX 4090 D 运行进化器，`qwen3.8-max-0902` 2 代，共 27,407 tokens，约 11 分钟，状态 `done`。

| 候选 | 父代 | 平板场景 | 本机 GPU 峰值 | 评估耗时 | ROS |
|---|---|---|---|---|---|
| init（种子） | — | 捕获 2/10 · 误报 2 | 99% | 15 s | 22.81 |
| 4016914b（种子） | — | 捕获 6/10 · 误报 2 | 99% | 33 s | 39.38 |
| 5bb6f85a | 4016914b | 捕获 5/10 · 误报 2 | 99% | 152 s | 39.62 |
| **52055201** | 5bb6f85a | 捕获 5/10 · 误报 2 | 99% | 79 s | **41.78** |

远端自进化在两代内把最优 ROS 从 39.38 推到 **41.78**（+2.40）。5bb6f85a 的改动是用加权 bootstrap 的 F1 第 10 百分位直接选阈值，替换原先的 delta 法下界；服务器只收到 ROS、f1_p10、auprc、捕获数等白名单标量。

### 4.1 2026-11-07 06:06（隧道断开期间）

| 项目 | 结果 |
|---|---|
| 平板连接 | `Android 平板 · 机房孪生` @ 172.16.8.109，WebSocket 在线 |
| 平板场景 | 14 帧上行、4,101 行遥测、300 块盘、552.6 KB；截止日评分 0.31 s |
| 平板场景结果 | 10 块真实故障：进化前捕获 2（误报 2）→ 进化后捕获 6（误报 2） |
| 本机完整验证集 | ROS 22.81 → **39.38**；F1 0.249 → 0.397；AUPRC 0.195 → 0.377；R@FAR 0.274 → 0.476 |
| GPU bootstrap | RTX 3050 Laptop，2 万次 × 30,754 盘，1.27 s（15,805 次/s），P(F1 提升) = 1.0 |
| 出域 | 只放行 candidate_id、ROS、f1_p10、auprc、recall_at_far 等标量；拦截 per_disk_predictions、val_labels、model_weights、evaluator_source |
| 远端探测 | **失败**：`ChannelOpenError: Connection refused`。诊断：跳板机可登录，但跳板机上隧道端口没有监听，跳板机也无法直连服务器内网地址，即服务器到跳板机的反向隧道已断开 |

### 4.2 2026-11-07 04:16（真实 Qwen 会话 `s20261107-041649`）

服务器 2× RTX 4090 D，Python 3.12，模型 `qwen3.8-max-0902`，3 代，约 4 万 tokens，评估数据为平板实时推送场景：

| 候选 | 父代 | 平板场景 | 本机 GPU 峰值 | 评估耗时 | ROS |
|---|---|---|---|---|---|
| init（种子） | — | 捕获 2/10 · 误报 2 | 100% | 15 s | 22.81 |
| 4016914b（种子） | — | 捕获 6/10 · 误报 2 | 100% | 35 s | **39.38** |
| fe0da519 | 4016914b | 运行失败（TypeError），失败类型回传服务器 | — | — | — |
| 67fe904c | 4016914b | 捕获 10/10 · 误报 174 | 100% | 122 s | 21.93 |
| 37ab8b5d | 4016914b | 捕获 6/10 · 误报 3 | 100% | 570 s | 31.93 |

会话正常结束（`done`），最优仍为 4016914b。演示回放会话 `s20261107-032448` 同样跑通（rule_baseline 12.94 → 4016914b 39.38）。

---

## 5. 排障

| 现象 | 原因与处理 |
|---|---|
| `probe` 返回 `ChannelOpenError: Connection refused` | 跳板机可达，但到服务器的隧道端口没开。在服务器上重启反向隧道 / frpc，使跳板机上 `ss -ltn` 能看到该端口，再 `probe` |
| `probe` 超时或认证失败 | 检查 `FE_SSH_JUMP*` / `FE_SSH_TARGET*`；首次连接会在结果里返回主机指纹供核对 |
| 页面"本地评估域接口不可用" | 后端不是 `showcase_serve.py` 或端口不一致；检查 `VITE_API_PROXY_TARGET` |
| 平板显示未连接 | 同一局域网？防火墙放行 8012？APK 构建时 `VITE_EDGE_SERVER` 是否为笔记本 IP？或改用 `adb reverse` |
| 候选很久不出现 | Qwen 思考模式开着（`FE_QWEN_THINKING=1`）会很慢；查看远端 `<session>/evolver.log` 与 `status.json` |
| 远端进化器退出 | 页面会显示 `evolver.log` 尾部；常见为远端 Python 路径错误 |
| 需要中止 | 页面"停止"或 `POST /api/edge/remote/stop`（写 `STOP`，当前步骤后退出） |

---

## 6. Demo 模式怎么跑（不需要服务器和密钥）

1. 按第 2 节启动后端与前端。
2. 打开 <http://127.0.0.1:5180/>，即 EvoBot 路演前端（6 幕）：
   - **1 对话**：点"HDD 三岛进化"或"最新论文组合出新算法"，再点"开始进化"；也可点历史任务直接看结果。
   - **2 确认**：核对服务器、评估器、模型、初始解与预算，点"确认，开始进化"。
   - **3 进化工作台**：自动播放真实实验回放，可暂停 / 重播 / 1×–4× 倍速。
   - **4 知识发现**：多 Agent 机制辩论与统计裁决。
   - **5 结果讲解**：EvoBot 讲解员五步讲解，可点步骤跳转。
   - **混合云模式**（确认页选"混合云 · 演示回放"，或工作台右上角切换）：服务器按顺序回放真实候选（不调用 LLM），本机仍对每个节点做真实 GPU 评估，子窗口与进化树同步；需要能连上服务器。完全离线时用"回放真实实验"。
3. 经典工作台在 <http://127.0.0.1:5180/overview>。

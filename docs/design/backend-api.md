# 后端 API 设计文档

> 文档版本：v1.1  
> 最后更新：2026-09-28  
> **本版本根据 FaultEvolve 主仓库 main@b59c39e 源码修订，数据结构已核实**

## 1. 概述

后端提供 REST API 和 WebSocket 事件接口，支持两种数据源模式：
- **回放模式**：读取已有的 `events.jsonl`、`tree.json`、`run_summary.json`、`fe.db` 文件
- **实时模式**：轮询运行中的 `fe.db`（WAL 模式增量写入），推送事件到前端

### 1.1 输出文件写入时机（关键）

| 输出 | 写入时机 | 说明 |
|------|---------|------|
| `fe.db` | **运行中增量写入** | SQLite WAL 模式，每个事件/节点立即持久化 |
| `run_summary.json` | 运行结束后一次性写出 | 包含完整运行统计 |
| `tree.json` | 运行结束后一次性写出 | 演化树最终快照 |
| `events.jsonl` | 运行结束后一次性写出 | 事件流完整导出 |
| `programs/*.py` | 运行结束后一次性写出 | 所有节点程序 |
| `logs/*.log` | 运行结束后一次性写出 | 运行日志 |

**实时模式采用 fe.db 轮询**：由于 `events.jsonl` 等文件只在运行结束后写出，实时监控必须轮询 `fe.db` 的 `event` 表，通过 `id` 字段做增量读取

## 2. REST API

### 2.1 演化运行管理

#### 列出所有运行

```http
GET /api/evolution/runs
```

响应：
```json
{
  "runs": [
    {
      "runId": "run-20260928-001",
      "status": "completed",
      "mode": "replay",
      "startedAt": "2026-09-28T10:00:00Z",
      "completedAt": "2026-09-28T12:30:00Z",
      "bestScore": 34.96,
      "totalNodes": 156,
      "totalEvaluations": 45
    }
  ]
}
```

#### 获取运行详情

```http
GET /api/evolution/runs/:runId
```

响应：
```json
{
  "runId": "run-20260928-001",
  "status": "completed",
  "mode": "replay",
  "config": {
    "taskDir": "/path/to/task",
    "targetScore": 32.0,
    "maxIterations": 50,
    "model": "qwen3-coder-plus",
    "reflectionModel": "qwen3-max"
  },
  "metrics": {
    "bestScore": 34.96,
    "validationScore": 33.70,
    "testScore": 33.58,
    "totalNodes": 156,
    "successfulNodes": 89,
    "repairAttempts": 23,
    "repairSuccesses": 18,
    "totalTokens": 245000,
    "wallClockSeconds": 9000
  },
  "startedAt": "2026-09-28T10:00:00Z",
  "completedAt": "2026-09-28T12:30:00Z"
}
```

#### 启动新运行（实时模式）

```http
POST /api/evolution/runs
Content-Type: application/json

{
  "taskDir": "/path/to/task",
  "targetScore": 32.0,
  "maxIterations": 50,
  "deploymentMode": "hybrid",
  "sshConfig": {
    "host": "192.168.1.100",
    "port": 22,
    "username": "user",
    "privateKeyPath": "/path/to/key"
  }
}
```

#### 停止运行

```http
POST /api/evolution/runs/:runId/stop
```

### 2.2 演化树

#### 获取完整树

```http
GET /api/evolution/runs/:runId/tree
```

响应（基于 FaultEvolve `tree.py` Tree.to_export() 方法，9 字段 + edges 数组）：
```json
{
  "nodes": [
    {
      "id": 0,
      "branch_id": 0,
      "depth": 0,
      "operator": "init",
      "score": 22.81,
      "status": "evaluated",
      "hypothesis_status": null,
      "intent": "初始化基线程序",
      "visit_count": 45
    },
    {
      "id": 1,
      "branch_id": 0,
      "depth": 1,
      "operator": "refine",
      "score": 28.35,
      "status": "evaluated",
      "hypothesis_status": null,
      "intent": "改进窗口特征计算",
      "visit_count": 23
    }
  ],
  "edges": [
    {"from": 0, "to": 1}
  ]
}
```

#### 获取节点详情

```http
GET /api/evolution/runs/:runId/nodes/:nodeId
```

响应（基于 `schemas.py` Node 模型和 `fe.db` node 表）：
```json
{
  "id": 42,
  "branch_id": 3,
  "depth": 5,
  "operator": "refine",
  "score": 34.96,
  "status": "evaluated",
  "hypothesis_status": null,
  "intent": "改进窗口特征计算",
  "visit_count": 12,
  "program": "# 节点代码...",
  "parentProgram": "# 父节点代码...",
  "diff": "--- parent\n+++ current\n@@ -10,5 +10,8 @@\n...",
  "adopted_cards": ["FE01", "FE03", "FE06"],
  "refuted_cards": []
}
```

### 2.3 事件流

#### 获取事件列表

```http
GET /api/evolution/runs/:runId/events?limit=100&offset=0
```

响应（基于 `fe.db` event 表和 `schemas.py` Event 模型，11 种事件类型）：
```json
{
  "events": [
    {
      "id": 1,
      "experiment_id": "exp-20260928-001",
      "type": "init_evaluated",
      "payload": {
        "node_id": 0,
        "score": 22.81
      },
      "ts": "2026-09-28T10:00:00.000Z"
    },
    {
      "id": 2,
      "experiment_id": "exp-20260928-001",
      "type": "repair_success",
      "payload": {
        "node_id": 1,
        "attempt": 2,
        "error_type": "SyntaxError"
      },
      "ts": "2026-09-28T10:05:30.000Z"
    },
    {
      "id": 3,
      "experiment_id": "exp-20260928-001",
      "type": "reflection_design",
      "payload": {
        "node_id": 1,
        "insight": "增量特征比快照特征效果显著提升",
        "z_score": 2.8
      },
      "ts": "2026-09-28T10:07:00.000Z"
    }
  ],
  "total": 342,
  "hasMore": true
}
```

#### 11 种事件类型（完整列表）

| 事件类型 | 说明 | payload 主要字段 |
|---------|------|-----------------|
| `init_evaluated` | 初始节点评估完成 | `node_id`, `score` |
| `selection_failed` | UCT 选择失败 | `reason` |
| `invalid_generation` | 生成的代码无效 | `node_id`, `error_type`, `error_msg` |
| `repair_failed` | 修复尝试失败 | `node_id`, `attempt`, `error_type` |
| `repair_success` | 修复成功 | `node_id`, `attempt`, `error_type` |
| `reflection_design` | 设计层反思 | `node_id`, `insight`, `z_score` |
| `hypothesis_refuted` | 假设被否证 | `node_id`, `hypothesis`, `evidence` |
| `insight_extracted` | 提取洞见 | `node_id`, `insight_text`, `propagated_to` |
| `reflection_implementation` | 实现层反思 | `node_id`, `content` |
| `iteration_complete` | 一轮迭代完成 | `iteration`, `best_score`, `nodes_count` |
| `run_finished` | 运行结束 | `reason`, `final_score`, `total_nodes` |

> **PR #3 扩展**：事件 payload 新增 `adopted_cards` 和 `refuted_cards` 数组字段
```

### 2.4 分数历史

#### ROS 评分公式（来自 `evaluator.py` lines 15-24）

```python
ROS = 100 * (0.5 * F1_p10 + 0.3 * AUPRC + 0.2 * R@FAR) * time_factor
```

| 指标 | 权重 | 说明 |
|------|------|------|
| F1_p10 | 0.5 | Precision=10% 时的 F1 分数 |
| AUPRC | 0.3 | Precision-Recall 曲线下面积 |
| R@FAR | 0.2 | FAR=0.1% 时的 Recall |
| time_factor | × | 时间惩罚因子（超时降权） |

#### 获取分数曲线数据

```http
GET /api/evolution/runs/:runId/scores
```

响应：
```json
{
  "scores": [
    {
      "node_id": 0,
      "iteration": 0,
      "ts": "2026-09-28T10:00:00.000Z",
      "score": 22.81,
      "is_best": false
    },
    {
      "node_id": 5,
      "iteration": 5,
      "ts": "2026-09-28T10:15:00.000Z",
      "score": 30.25,
      "is_best": true
    }
  ],
  "best_score": 34.96,
  "best_node_id": 42
}
```

### 2.5 知识卡

#### 获取文献知识卡列表

```http
GET /api/knowledge/cards?category=feature_engineering&limit=20
```

响应：
```json
{
  "cards": [
    {
      "id": "FE01",
      "title": "Window deltas of critical error counters",
      "category": "feature_engineering",
      "claim": "Adding per-disk deltas over the 14-day window...",
      "rationale": "Backblaze notes these counters...",
      "applicability": "All vendors; 187/188 mostly Seagate",
      "expectedEffect": "Large: typically the single biggest gain",
      "risk": "Disks with fewer than 4 rows give noisy deltas",
      "sourceIds": ["backblaze2016", "botezatu2016", "zhu2013"],
      "tags": ["smart_5", "smart_187", "trend", "delta"],
      "priority": 1,
      "evidence": "paper"
    }
  ],
  "total": 51,
  "categories": ["feature_engineering", "model", "evaluation", ...]
}
```

### 2.6 三层知识

#### 获取现象卡

```http
GET /api/knowledge/phenomena?runId=run-20260928-001
```

响应：
```json
{
  "phenomena": [
    {
      "phenomenonId": "phen-001",
      "claim": {
        "condition": "SMART 5/187/197/198 全为 0",
        "variable": "smart_5_d14",
        "effect": "positive",
        "magnitude": 0.23,
        "confidenceInterval": [0.18, 0.28],
        "applicability": "所有厂商"
      },
      "grade": "confirmed",
      "noveltyEvidence": {
        "semanticNovelty": true,
        "functionalNovelty": true,
        "relatedCards": ["FE01"]
      },
      "bloodline": {
        "nodeId": "node-42",
        "cardIds": ["FE01", "FE03"],
        "sourceIds": ["backblaze2016"]
      }
    }
  ]
}
```

#### 获取机制卡

```http
GET /api/knowledge/mechanisms?runId=run-20260928-001
```

响应：
```json
{
  "mechanisms": [
    {
      "mechanismId": "mech-001",
      "causalGraph": {
        "nodes": ["smart_5", "wear", "failure"],
        "edges": [
          {"from": "wear", "to": "smart_5", "sign": "+", "lag": "days"},
          {"from": "wear", "to": "failure", "sign": "+"}
        ]
      },
      "rivals": [
        {
          "mechanismId": "mech-censor",
          "name": "运维删失",
          "description": "Backblaze 在 187>0 时安排更换"
        }
      ],
      "tests": [
        {
          "testId": "test-001",
          "type": "temporal_precedence",
          "eValue": 5.3,
          "result": "passed"
        }
      ],
      "elo": 1250,
      "grade": "corroborated"
    }
  ]
}
```

#### 获取锦标赛数据

```http
GET /api/knowledge/tournament?runId=run-20260928-001
```

响应：
```json
{
  "matches": [
    {
      "matchId": "match-001",
      "mechanism1": "mech-001",
      "mechanism2": "mech-censor",
      "test": {
        "type": "temporal_precedence",
        "parameters": {...},
        "preregistrationHash": "sha256:abc123..."
      },
      "result": {
        "winner": "mech-001",
        "eValue": 5.3,
        "eloDelta": [+35, -35]
      },
      "timestamp": "2026-09-28T11:00:00Z"
    }
  ],
  "rankings": [
    {"mechanismId": "mech-001", "name": "主机制", "elo": 1250},
    {"mechanismId": "mech-censor", "name": "删失", "elo": 1180}
  ]
}
```

### 2.7 Skills

#### 获取 Skills 列表

```http
GET /api/skills
```

响应：
```json
{
  "skills": [
    {
      "skillId": "fe-evolve-manager",
      "name": "故障预测自动调优",
      "description": "环境检查、启动/恢复本地演化...",
      "trigger": "新设备或新数据集需要预测器",
      "status": "implemented",
      "usageCount": 5,
      "lastUsed": "2026-09-28T10:00:00Z"
    }
  ]
}
```

#### 获取 Skill 复用情况

```http
GET /api/skills/:skillId/usage
```

响应：
```json
{
  "skillId": "fe-evolve-manager",
  "datasets": [
    {
      "name": "Backblaze HDD",
      "runId": "run-20260928-001",
      "result": "success",
      "bestScore": 34.96
    },
    {
      "name": "SmartMem 内存",
      "runId": null,
      "result": "planned",
      "configDiff": ["数据适配器", "评分配置"]
    }
  ]
}
```

### 2.8 报告

#### 生成报告

```http
POST /api/reports/generate
Content-Type: application/json

{
  "runId": "run-20260928-001",
  "format": "markdown",
  "sections": ["phenomena", "mechanisms", "theories", "controls"]
}
```

响应：
```json
{
  "reportId": "report-001",
  "content": "# 知识增量报告\n\n## 现象层\n...",
  "summary": {
    "phenomenaCount": 5,
    "confirmedCount": 3,
    "discoveredCount": 1,
    "refutedCount": 1,
    "negativeControlFalsePositives": 0,
    "plantedSignalRecoveryRate": 1.0
  }
}
```

### 2.9 设置与 CLI

#### CLI 命令（来自 `cli.py` evolve_local，lines 298-366）

```bash
fe evolve local <task_dir> [OPTIONS]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `<task_dir>` | 任务目录（必须包含 data/, baseline.py 等） | 必填 |
| `--mock` | 使用 mock LLM（不调用真实 API） | false |
| `-n, --max-iterations N` | 最大迭代次数 | 50 |
| `--resume ID` | 从已有实验 ID 恢复 | null |
| `--json` | JSON 格式输出 | false |
| `--runs-dir PATH` | 运行输出目录 | `./runs` |
| `--artifacts-dir PATH` | 制品目录 | `./artifacts` |

#### LLMConfig（来自 `config.py` lines 79-86）

```json
{
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "api_key": "${DASHSCOPE_API_KEY}",
  "generate_model": "qwen3-coder-plus",
  "reason_model": "qwen3-max",
  "temperature": 0.7,
  "max_tokens": 4096
}
```

> DashScope 兼容 OpenAI SDK 接口，`base_url` 使用 `/compatible-mode/v1` 路径。

#### 获取配置

```http
GET /api/settings
```

#### 更新配置

```http
PUT /api/settings
Content-Type: application/json

{
  "deploymentMode": "hybrid",
  "llmConfig": {
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "generate_model": "qwen3-coder-plus",
    "reason_model": "qwen3-max"
  },
  "runsDir": "/path/to/runs"
}
```

## 3. WebSocket 事件

### 3.1 连接

```javascript
const socket = io('/evolution', {
  query: { runId: 'run-20260928-001' }
});
```

### 3.2 事件类型（11 种，与 fe.db event 表一致）

> 事件格式统一为 `{id, experiment_id, type, payload, ts}`

```typescript
// 基础事件接口
interface FaultEvolveEvent {
  id: number;
  experiment_id: string;
  type: EventType;
  payload: Record<string, unknown>;
  ts: string;  // UTC ISO 8601
}

type EventType =
  | 'init_evaluated'
  | 'selection_failed'
  | 'invalid_generation'
  | 'repair_failed'
  | 'repair_success'
  | 'reflection_design'
  | 'hypothesis_refuted'
  | 'insight_extracted'
  | 'reflection_implementation'
  | 'iteration_complete'
  | 'run_finished';
```

#### init_evaluated - 初始节点评估完成

```typescript
interface InitEvaluatedEvent extends FaultEvolveEvent {
  type: 'init_evaluated';
  payload: {
    node_id: number;
    score: number;
  };
}
```

#### repair_success / repair_failed - 修复结果

```typescript
interface RepairEvent extends FaultEvolveEvent {
  type: 'repair_success' | 'repair_failed';
  payload: {
    node_id: number;
    attempt: number;
    error_type: string;
  };
}
```

#### reflection_design / reflection_implementation - 反思

```typescript
interface ReflectionEvent extends FaultEvolveEvent {
  type: 'reflection_design' | 'reflection_implementation';
  payload: {
    node_id: number;
    insight?: string;
    z_score?: number;
    content?: string;
  };
}
```

#### hypothesis_refuted - 假设否证

```typescript
interface HypothesisRefutedEvent extends FaultEvolveEvent {
  type: 'hypothesis_refuted';
  payload: {
    node_id: number;
    hypothesis: string;
    evidence: string;
  };
}
```

#### insight_extracted - 洞见提取

```typescript
interface InsightExtractedEvent extends FaultEvolveEvent {
  type: 'insight_extracted';
  payload: {
    node_id: number;
    insight_text: string;
    propagated_to: number[];  // node IDs
  };
}
```

#### iteration_complete - 迭代完成

```typescript
interface IterationCompleteEvent extends FaultEvolveEvent {
  type: 'iteration_complete';
  payload: {
    iteration: number;
    best_score: number;
    nodes_count: number;
  };
}
```

#### run_finished - 运行结束

```typescript
interface RunFinishedEvent extends FaultEvolveEvent {
  type: 'run_finished';
  payload: {
    reason: 'target_reached' | 'max_iterations' | 'error' | 'user_stopped';
    final_score: number;
    total_nodes: number;
  };
}
```

#### PR #3 扩展字段

```typescript
// 事件 payload 可包含知识卡追踪字段
interface CardTrackingPayload {
  adopted_cards?: string[];  // 本次采纳的卡片 ID
  refuted_cards?: string[];  // 本次否证的卡片 ID
}
```
```

### 3.3 订阅控制

```typescript
// 订阅特定运行
socket.emit('subscribe', { runId: 'run-20260928-001' });

// 取消订阅
socket.emit('unsubscribe', { runId: 'run-20260928-001' });
```

## 4. 回放与实时适配层

### 4.1 数据源抽象

```typescript
interface EvolutionDataSource {
  getTree(): Promise<TreeData>;
  getEvents(options: { limit?: number; afterId?: number }): Promise<EventData[]>;
  getNode(nodeId: number): Promise<NodeData>;
  getSummary(): Promise<RunSummary | null>;
  
  // 实时模式
  subscribe?(callback: (event: FaultEvolveEvent) => void): void;
  unsubscribe?(): void;
}
```

### 4.2 回放模式：读取运行后文件

```typescript
class ReplayDataSource implements EvolutionDataSource {
  constructor(
    private runDir: string  // 包含 tree.json, events.jsonl, run_summary.json, fe.db
  ) {}
  
  async getTree(): Promise<TreeData> {
    const content = await fs.readFile(
      path.join(this.runDir, 'tree.json'), 'utf-8'
    );
    return JSON.parse(content);  // {nodes: [...], edges: [...]}
  }
  
  async getEvents(options: { limit?: number; afterId?: number }) {
    const lines = await fs.readFile(
      path.join(this.runDir, 'events.jsonl'), 'utf-8'
    );
    let events = lines.split('\n')
      .filter(Boolean)
      .map(line => JSON.parse(line));
    
    if (options.afterId !== undefined) {
      events = events.filter(e => e.id > options.afterId);
    }
    if (options.limit) {
      events = events.slice(0, options.limit);
    }
    return events;
  }
  
  async getSummary(): Promise<RunSummary> {
    const content = await fs.readFile(
      path.join(this.runDir, 'run_summary.json'), 'utf-8'
    );
    return JSON.parse(content);
  }
}
```

### 4.3 实时模式：轮询 fe.db（关键）

> **重要**：`events.jsonl`、`tree.json`、`run_summary.json` 只在运行结束后写出。
> 实时监控必须轮询 `fe.db` 的 `event` 表。

```typescript
class RealtimeDataSource implements EvolutionDataSource {
  private db: Database;
  private lastEventId = 0;
  private pollInterval: NodeJS.Timer | null = null;
  
  constructor(
    private feDbPath: string,  // fe.db 路径（WAL 模式，运行中可安全读取）
    private pollIntervalMs = 500
  ) {
    // 以只读模式打开 WAL 数据库
    this.db = new Database(feDbPath, { readonly: true });
  }
  
  subscribe(callback: (event: FaultEvolveEvent) => void) {
    this.pollInterval = setInterval(() => {
      const newEvents = this.db.prepare(`
        SELECT id, experiment_id, type, payload, ts
        FROM event
        WHERE id > ?
        ORDER BY id ASC
        LIMIT 100
      `).all(this.lastEventId);
      
      for (const row of newEvents) {
        const event: FaultEvolveEvent = {
          id: row.id,
          experiment_id: row.experiment_id,
          type: row.type,
          payload: JSON.parse(row.payload),
          ts: row.ts
        };
        callback(event);
        this.lastEventId = row.id;
      }
    }, this.pollIntervalMs);
  }
  
  unsubscribe() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }
  
  async getTree(): Promise<TreeData> {
    // 实时模式下从 node 表构建树
    const nodes = this.db.prepare(`
      SELECT id, branch_id, depth, operator, score, status,
             hypothesis_status, intent, visit_count
      FROM node
      WHERE experiment_id = ?
      ORDER BY id ASC
    `).all(this.experimentId);
    
    const edges = this.db.prepare(`
      SELECT id as to_id, parent_id as from_id
      FROM node
      WHERE experiment_id = ? AND parent_id IS NOT NULL
    `).all(this.experimentId);
    
    return {
      nodes: nodes.map(n => ({
        id: n.id,
        branch_id: n.branch_id,
        depth: n.depth,
        operator: n.operator,
        score: n.score,
        status: n.status,
        hypothesis_status: n.hypothesis_status,
        intent: n.intent,
        visit_count: n.visit_count
      })),
      edges: edges.map(e => ({ from: e.from_id, to: e.to_id }))
    };
  }
}
```
```

### 4.2 真实数据 Schema（已核实 main@b59c39e）

> 以下 schema 来自 FaultEvolve 主仓库 `store.py` 和 `schemas.py`，已核实。

#### events.jsonl 行格式

每行是一个 JSON 对象，字段如下：

```json
{
  "id": 1,
  "experiment_id": "exp-20260928-001",
  "type": "reflection_design",
  "payload": {
    "node_id": 1,
    "insight": "增量特征比快照特征效果显著提升",
    "z_score": 2.8
  },
  "ts": "2026-09-28T10:07:00.000Z"
}
```

- `id`: 事件序号（INTEGER，自增）
- `experiment_id`: 所属实验 ID（TEXT）
- `type`: 11 种事件类型之一（见上文表格）
- `payload`: JSON 对象，不同事件类型有不同字段
- `ts`: UTC ISO 8601 时间戳

#### tree.json 格式

```json
{
  "nodes": [
    {
      "id": 0,
      "branch_id": 0,
      "depth": 0,
      "operator": "init",
      "score": 22.81,
      "status": "evaluated",
      "hypothesis_status": null,
      "intent": "初始化基线程序",
      "visit_count": 45
    }
  ],
  "edges": [
    {"from": 0, "to": 1},
    {"from": 0, "to": 2}
  ]
}
```

节点 9 字段说明（来自 `tree.py` Tree.to_export()）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 节点 ID |
| `branch_id` | int | 分支 ID |
| `depth` | int | 树深度 |
| `operator` | str | 算子类型：init / refine / repair / inject / discover |
| `score` | float \| null | ROS 分数，未评估为 null |
| `status` | str | evaluated / pending / failed |
| `hypothesis_status` | str \| null | confirmed / refuted / null |
| `intent` | str | 生成意图描述 |
| `visit_count` | int | UCT 访问次数 |

#### run_summary.json 格式

```json
{
  "experiment_id": "exp-20260928-001",
  "best_score": 34.96,
  "best_node_id": 42,
  "total_nodes": 156,
  "total_iterations": 50,
  "total_tokens": 245000,
  "total_cost_usd": 1.25,
  "wall_clock_seconds": 9000,
  "metrics": {
    "valid_rate": 0.85,
    "repair_success_rate": 0.78,
    "avg_score_improvement": 0.15
  },
  "config": {
    "task_dir": "/path/to/task",
    "target_score": 32.0,
    "max_iterations": 50,
    "generate_model": "qwen3-coder-plus",
    "reason_model": "qwen3-max"
  }
}
```

#### fe.db 表结构（5 表 + WAL 模式）

```sql
-- 来自 store.py，SQLite WAL 模式（line 131）
PRAGMA journal_mode=WAL;

-- 实验表
CREATE TABLE experiment (
  id TEXT PRIMARY KEY,
  task_dir TEXT NOT NULL,
  config TEXT NOT NULL,  -- JSON: LLMConfig + RunConfig
  created_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT DEFAULT 'running'  -- running / completed / failed
);

-- 节点表
CREATE TABLE node (
  id INTEGER PRIMARY KEY,
  experiment_id TEXT NOT NULL REFERENCES experiment(id),
  branch_id INTEGER NOT NULL,
  parent_id INTEGER REFERENCES node(id),
  depth INTEGER NOT NULL,
  operator TEXT NOT NULL,  -- init / refine / repair / inject / discover
  intent TEXT,
  program TEXT NOT NULL,
  score REAL,
  status TEXT NOT NULL,  -- pending / evaluated / failed
  hypothesis_status TEXT,  -- confirmed / refuted / null
  visit_count INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  evaluated_at TEXT
);

-- 洞见表
CREATE TABLE insight (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiment(id),
  node_id INTEGER NOT NULL REFERENCES node(id),
  layer TEXT NOT NULL,  -- implementation / design / hypothesis
  content TEXT NOT NULL,
  z_score REAL,
  propagated_to TEXT,  -- JSON array of node IDs
  created_at TEXT NOT NULL
);

-- LLM 调用记录表
CREATE TABLE llm_call (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiment(id),
  node_id INTEGER REFERENCES node(id),
  model TEXT NOT NULL,
  purpose TEXT NOT NULL,  -- generate / reflect / repair
  prompt_tokens INTEGER NOT NULL,
  completion_tokens INTEGER NOT NULL,
  latency_ms INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

-- 事件表（实时流核心）
CREATE TABLE event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiment(id),
  type TEXT NOT NULL,  -- 11 种事件类型
  payload TEXT NOT NULL,  -- JSON
  ts TEXT NOT NULL  -- UTC ISO 8601
);
```

#### PR #3 新增表（知识卡追踪）

```sql
-- 卡片统计表
CREATE TABLE card_stats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiment(id),
  card_id TEXT NOT NULL,
  adopt_count INTEGER DEFAULT 0,
  refute_count INTEGER DEFAULT 0,
  last_used_at TEXT
);

-- 分支否证卡表
CREATE TABLE branch_refuted_cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  experiment_id TEXT NOT NULL REFERENCES experiment(id),
  branch_id INTEGER NOT NULL,
  card_id TEXT NOT NULL,
  refuted_at_node INTEGER NOT NULL REFERENCES node(id),
  reason TEXT
);

-- 节点采纳卡表
CREATE TABLE node_adopted_cards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id INTEGER NOT NULL REFERENCES node(id),
  card_id TEXT NOT NULL,
  adopted_at TEXT NOT NULL
);
```

## 5. 错误处理

### 5.1 错误响应格式

```json
{
  "error": {
    "code": "RUN_NOT_FOUND",
    "message": "Evolution run not found: run-xxx",
    "details": {}
  }
}
```

### 5.2 错误码

| 错误码 | HTTP 状态 | 说明 |
|--------|----------|------|
| `RUN_NOT_FOUND` | 404 | 运行不存在 |
| `NODE_NOT_FOUND` | 404 | 节点不存在 |
| `FILE_NOT_FOUND` | 404 | 数据文件不存在 |
| `INVALID_CONFIG` | 400 | 配置无效 |
| `ENGINE_ERROR` | 500 | 引擎错误 |
| `SSH_CONNECTION_FAILED` | 500 | SSH 连接失败 |

## 6. 已核实与待核内容

### 6.1 已核实（main@b59c39e）

| 内容 | 来源文件 | 状态 |
|------|---------|------|
| events.jsonl 行格式 | `schemas.py` Event 模型 | ✅ 已核实 |
| 11 种事件类型 | `schemas.py`, SCHEMA_NOTES §1 | ✅ 已核实 |
| tree.json 9 字段 + edges | `tree.py` Tree.to_export() lines 351-378 | ✅ 已核实 |
| fe.db 5 表结构 | `store.py` DDL | ✅ 已核实 |
| fe.db WAL 模式 | `store.py` line 131 | ✅ 已核实 |
| run_summary.json 格式 | `schemas.py` RunSummary lines 197-218 | ✅ 已核实 |
| ROS 公式 | `evaluator.py` lines 15-24 | ✅ 已核实 |
| CLI 参数 | `cli.py` evolve_local lines 298-366 | ✅ 已核实 |
| LLMConfig 字段 | `config.py` lines 79-86 | ✅ 已核实 |
| 写入时机（fe.db 增量 vs 其他文件运行后写出） | SCHEMA_NOTES | ✅ 已核实 |

### 6.2 PR #3 扩展（head 673084d，待合入）

| 内容 | 来源 | 状态 |
|------|------|------|
| card_stats / branch_refuted_cards / node_adopted_cards 表 | PR #3 store_DDL_excerpt.sql | ✅ 已核实 |
| 事件 payload 新增 adopted_cards / refuted_cards | PR #3 | ✅ 已核实 |

### 6.3 仍待核

| 内容 | 原因 | 说明 |
|------|------|------|
| 三层知识（现象/机理/原理）完整数据格式 | 主仓库尚未实现发现流水线 | API 设计基于项目说明书，待后续核实 |
| 数据裁决锦标赛输出格式 | 同上 | 待后续核实 |

### 6.4 已知缺陷

| 缺陷 | 位置 | 影响 | 状态 |
|------|------|------|------|
| `repair_count` NameError | `engine.py` lines 450, 459 | `_attempt_repair` 方法引用未定义变量，修复路径会抛异常 | **主线待修复** |

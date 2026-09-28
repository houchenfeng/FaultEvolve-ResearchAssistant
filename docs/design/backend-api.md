# 后端 API 设计文档

> 文档版本：v1.0  
> 最后更新：2026-09-28

## 1. 概述

后端提供 REST API 和 WebSocket 事件接口，支持两种数据源模式：
- **回放模式**：读取已有的 `events.jsonl`、`tree.json`、`fe.db` 文件
- **实时模式**：与运行中的 FaultEvolve 引擎通信，tail 事件文件并推送

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

响应（基于 FaultEvolve 的 tree.json 格式，待核）：
```json
{
  "root": {
    "nodeId": "node-0",
    "programPath": "programs/node_0.py",
    "score": 22.81,
    "scoreDetails": {
      "ros": 22.81,
      "f1_p10": 0.42,
      "auprc": 0.35,
      "r_at_far": 0.15,
      "f1_boot_std": 0.03
    },
    "operator": "init",
    "status": "evaluated",
    "visitCount": 45,
    "createdAt": "2026-09-28T10:00:00Z",
    "children": [
      {
        "nodeId": "node-1",
        "parentId": "node-0",
        "programPath": "programs/node_1.py",
        "score": 28.35,
        "operator": "refine",
        "status": "evaluated",
        "adoptedCards": ["FE01", "FE03"],
        "children": []
      }
    ]
  },
  "bestNodeId": "node-42",
  "bestScore": 34.96
}
```

#### 获取节点详情

```http
GET /api/evolution/runs/:runId/nodes/:nodeId
```

响应：
```json
{
  "nodeId": "node-42",
  "parentId": "node-15",
  "programPath": "programs/node_42.py",
  "program": "# 节点代码...",
  "parentProgram": "# 父节点代码...",
  "diff": "--- parent\n+++ current\n@@ -10,5 +10,8 @@\n...",
  "score": 34.96,
  "scoreDetails": {
    "ros": 34.96,
    "f1_p10": 0.52,
    "auprc": 0.48,
    "r_at_far": 0.28,
    "f1_boot_std": 0.025
  },
  "operator": "refine",
  "operatorPrompt": "改进窗口特征计算...",
  "status": "evaluated",
  "adoptedCards": ["FE01", "FE03", "FE06"],
  "reflection": {
    "layer": "design",
    "content": "本次改进主要是...",
    "insights": [
      {
        "text": "增量特征比快照特征效果显著提升",
        "zScore": 2.8,
        "propagatedTo": ["node-45", "node-48"]
      }
    ]
  },
  "refutedHypotheses": [],
  "createdAt": "2026-09-28T11:30:00Z",
  "evaluatedAt": "2026-09-28T11:32:00Z",
  "evaluationSeconds": 125
}
```

### 2.3 事件流

#### 获取事件列表

```http
GET /api/evolution/runs/:runId/events?limit=100&offset=0
```

响应（基于 events.jsonl 格式，待核）：
```json
{
  "events": [
    {
      "eventId": "evt-001",
      "type": "node_created",
      "timestamp": "2026-09-28T10:05:00Z",
      "data": {
        "nodeId": "node-1",
        "parentId": "node-0",
        "operator": "refine"
      }
    },
    {
      "eventId": "evt-002",
      "type": "node_evaluated",
      "timestamp": "2026-09-28T10:07:00Z",
      "data": {
        "nodeId": "node-1",
        "score": 28.35,
        "scoreDetails": {...},
        "evaluationSeconds": 118
      }
    },
    {
      "eventId": "evt-003",
      "type": "reflection",
      "timestamp": "2026-09-28T10:07:30Z",
      "data": {
        "nodeId": "node-1",
        "layer": "design",
        "content": "..."
      }
    }
  ],
  "total": 342,
  "hasMore": true
}
```

### 2.4 分数历史

#### 获取分数曲线数据

```http
GET /api/evolution/runs/:runId/scores
```

响应：
```json
{
  "scores": [
    {
      "nodeId": "node-0",
      "iteration": 0,
      "timestamp": "2026-09-28T10:00:00Z",
      "score": 22.81,
      "isBest": false
    },
    {
      "nodeId": "node-5",
      "iteration": 5,
      "timestamp": "2026-09-28T10:15:00Z",
      "score": 30.25,
      "isBest": true
    }
  ],
  "bestScore": 34.96,
  "bestNodeId": "node-42"
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

### 2.9 设置

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
  "qwenConfig": {
    "endpoint": "https://dashscope.aliyuncs.com/api/v1",
    "model": "qwen3-coder-plus",
    "reflectionModel": "qwen3-max"
  },
  "dataPath": "/path/to/data"
}
```

## 3. WebSocket 事件

### 3.1 连接

```javascript
const socket = io('/evolution', {
  query: { runId: 'run-20260928-001' }
});
```

### 3.2 事件类型

#### 节点创建

```typescript
interface NodeCreatedEvent {
  type: 'node_created';
  timestamp: string;
  data: {
    nodeId: string;
    parentId: string;
    operator: 'init' | 'refine' | 'repair' | 'inject' | 'discover';
    adoptedCards?: string[];
  };
}
```

#### 节点评估完成

```typescript
interface NodeEvaluatedEvent {
  type: 'node_evaluated';
  timestamp: string;
  data: {
    nodeId: string;
    score: number;
    scoreDetails: {
      ros: number;
      f1_p10: number;
      auprc: number;
      r_at_far: number;
      f1_boot_std: number;
    };
    isBest: boolean;
    evaluationSeconds: number;
  };
}
```

#### 评估失败

```typescript
interface EvaluationFailedEvent {
  type: 'evaluation_failed';
  timestamp: string;
  data: {
    nodeId: string;
    errorType: string;
    errorMessage: string;
    willRepair: boolean;
  };
}
```

#### 修复尝试

```typescript
interface RepairAttemptEvent {
  type: 'repair_attempt';
  timestamp: string;
  data: {
    nodeId: string;
    attemptNumber: number;
    errorType: string;
  };
}
```

#### 反思

```typescript
interface ReflectionEvent {
  type: 'reflection';
  timestamp: string;
  data: {
    nodeId: string;
    layer: 'implementation' | 'design' | 'hypothesis' | 'mechanism';
    content: string;
    insights?: Array<{
      text: string;
      zScore: number;
    }>;
    refutedHypothesis?: string;
  };
}
```

#### 知识发现

```typescript
interface KnowledgeDiscoveredEvent {
  type: 'knowledge_discovered';
  timestamp: string;
  data: {
    layer: 'phenomenon' | 'mechanism' | 'theory';
    id: string;
    grade: 'confirmed' | 'corrected' | 'discovered' | 'refuted';
    summary: string;
  };
}
```

#### 锦标赛比赛

```typescript
interface TournamentMatchEvent {
  type: 'tournament_match';
  timestamp: string;
  data: {
    matchId: string;
    mechanism1: string;
    mechanism2: string;
    testType: string;
    winner: string | null;
    eValue: number;
    eloBefore: [number, number];
    eloAfter: [number, number];
  };
}
```

#### 运行状态变更

```typescript
interface RunStatusEvent {
  type: 'run_status';
  timestamp: string;
  data: {
    status: 'running' | 'paused' | 'completed' | 'failed';
    message?: string;
  };
}
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
  getEvents(options: { limit?: number; offset?: number }): Promise<EventData[]>;
  getNode(nodeId: string): Promise<NodeData>;
  getScores(): Promise<ScoreData[]>;
  
  // 实时模式额外方法
  subscribe?(callback: (event: EvolutionEvent) => void): void;
  unsubscribe?(): void;
}

class ReplayDataSource implements EvolutionDataSource {
  constructor(
    private eventsFile: string,
    private treeFile: string,
    private dbFile?: string
  ) {}
  
  async getTree() {
    return JSON.parse(await fs.readFile(this.treeFile, 'utf-8'));
  }
  
  async getEvents(options) {
    const lines = await fs.readFile(this.eventsFile, 'utf-8');
    return lines.split('\n')
      .filter(Boolean)
      .map(line => JSON.parse(line))
      .slice(options.offset, options.offset + options.limit);
  }
}

class RealtimeDataSource implements EvolutionDataSource {
  constructor(
    private engineClient: EngineClient,
    private eventEmitter: EventEmitter
  ) {}
  
  subscribe(callback) {
    // tail events.jsonl 并推送
    this.tail = new Tail(this.engineClient.eventsPath);
    this.tail.on('line', (line) => {
      callback(JSON.parse(line));
    });
  }
}
```

### 4.2 事件 Schema（基于 FaultEvolve 实际输出，待核）

> 以下 schema 基于项目说明书描述推断，需与主仓库实际代码核对。

#### events.jsonl 行格式

```json
{
  "event_type": "node_created | node_evaluated | reflection | ...",
  "timestamp": "2026-09-28T10:05:00.123Z",
  "node_id": "node-1",
  "parent_id": "node-0",
  "operator": "refine",
  "score": 28.35,
  "score_details": {
    "ros": 28.35,
    "f1_p10": 0.45,
    "auprc": 0.38,
    "r_at_far": 0.18,
    "f1_boot_std": 0.028
  },
  "reflection_layer": "design",
  "reflection_content": "...",
  "adopted_cards": ["FE01", "FE03"],
  "error_type": null,
  "error_message": null
}
```

#### tree.json 格式（待核）

```json
{
  "root_id": "node-0",
  "nodes": {
    "node-0": {
      "node_id": "node-0",
      "parent_id": null,
      "children": ["node-1", "node-2"],
      "program_path": "programs/node_0.py",
      "score": 22.81,
      "operator": "init",
      "status": "evaluated",
      "visit_count": 45,
      "q_value": 0.0
    },
    "node-1": {
      "node_id": "node-1",
      "parent_id": "node-0",
      "children": ["node-5", "node-6"],
      "program_path": "programs/node_1.py",
      "score": 28.35,
      "operator": "refine",
      "status": "evaluated",
      "visit_count": 23,
      "q_value": 0.15,
      "adopted_cards": ["FE01", "FE03"]
    }
  },
  "best_node_id": "node-42",
  "best_score": 34.96,
  "total_evaluations": 45,
  "total_tokens": 245000
}
```

#### fe.db 表结构（待核）

```sql
-- 基于项目说明书推断
CREATE TABLE nodes (
  node_id TEXT PRIMARY KEY,
  parent_id TEXT,
  program_path TEXT,
  score REAL,
  ros REAL,
  f1_p10 REAL,
  auprc REAL,
  r_at_far REAL,
  f1_boot_std REAL,
  operator TEXT,
  status TEXT,
  visit_count INTEGER,
  q_value REAL,
  adopted_cards TEXT,  -- JSON array
  created_at TEXT,
  evaluated_at TEXT
);

CREATE TABLE events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT,
  timestamp TEXT,
  node_id TEXT,
  data TEXT  -- JSON
);

CREATE TABLE reflections (
  reflection_id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id TEXT,
  layer TEXT,
  content TEXT,
  insights TEXT,  -- JSON array
  created_at TEXT
);

CREATE TABLE llm_calls (
  call_id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id TEXT,
  model TEXT,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  latency_ms INTEGER,
  created_at TEXT
);

CREATE TABLE branch_memory (
  memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id TEXT,
  memory_type TEXT,  -- refuted_hypothesis | error_pattern
  content TEXT,
  created_at TEXT
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

## 6. 待核内容

| 内容 | 来源 | 状态 |
|------|------|------|
| events.jsonl 完整字段列表 | FaultEvolve 主仓库 `store.py` | 待核 |
| tree.json 完整 schema | FaultEvolve 主仓库输出 | 待核 |
| fe.db 表结构 | FaultEvolve 主仓库 `store.py` | 待核 |
| run_summary.json 格式 | FaultEvolve 主仓库输出 | 待核 |
| 知识卡注入事件格式 | PR #3 | 待核 |

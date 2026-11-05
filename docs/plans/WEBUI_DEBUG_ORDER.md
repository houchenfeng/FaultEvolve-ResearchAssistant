# WebUI 排错顺序（TODO §12.7）

出问题先按这个顺序走，不要跳步。每一层都有**具体落点和命令**，因为"我觉得是前端的问题"
在这个项目上已经被证伪过不止一次：最典型的一次是修复记账（重试次数 / 是否耗尽）在界面上
恒显示 0 / false，看上去是组件写错了，实际是**前端读错了字段的落点** —— 引擎把
`repair_count` 写在**被修的失败节点**上，而 `repair_parent_id` 的指针在修复节点身上
（`engine.py:2009` / `engine.py:2006` / `tree.py:459`）。在组件里加特判能让它"看起来好了"，
但契约还是错的，别的页面会继续错。

## 0. 先固定现场

```bash
git rev-parse --abbrev-ref HEAD && git rev-parse HEAD   # 在哪条分支、哪个提交
```

复现步骤、run ID、实验 ID、时间戳写进 issue 或聊天记录。**没有 run ID 的 bug 报告等于没有
现场**：运行目录在回放模式下是唯一的事实来源，事后往往已经被下一次运行覆盖。

## 1. 看 API 原始响应（不要先看界面）

```bash
# 本机 E2E 后端（配置固定、指向 fixture 副本）
python scripts/e2e_serve.py --port 8011
curl -s http://127.0.0.1:8011/api/runs/<run_id>/tree | python -m json.tool | head -60
```

要确认的是**后端到底给了什么**：字段在不在、是不是 `null`、类型对不对。
这一步如果就已经不对，后面全是白查。

三个反复踩的坑：

- `data_state` 才是运行详情里的稳定性字段，响应里**没有** `status`；
- 事件字段叫 `type`，不叫 `event_type`；
- `discovery/{phenomena,preregistration,controls}.json` 是 `[]`（list），不是 `{}`。

## 2. 看 DTO 转换

对照 `src/faultevolve/webapi/contracts.py` 里的 DTO 与 `web/openapi/faultevolve.openapi.json`。
后端有、前端没有，八成是**生成客户端没重新导出**：

```bash
python scripts/export_web_contracts.py
python scripts/check_web_contracts.py       # 必须 exit 0
cd web && pnpm generate:api
# 然后 git diff -- web/src/generated 不为空就说明之前是脏的
```

前端只渲染 `report.py` 的 manifest 白名单里注册过的字段（结果报告页），
新字段不注册就等于不存在 —— 这不是前端 bug，是注册漏了。

## 3. 看 Query 缓存与事件去重

- 缓存键在 `web/src/lib/query-keys.ts`。同一份数据两个键 ⇒ 两份缓存，改一处另一处是旧的。
- 实时通道统一走 SSE（`web/src/features/workbench/use-event-stream.ts`）。
  断线重连靠 `after_id` 补拉，**补拉段与已有段必须去重**，重复的事件在界面上表现为
  "同一个节点出现了两次"。
- 这一步的典型症状：手动刷新是对的，联动跳转是错的。

## 4. 看组件显示

到这一步才打开浏览器。用 `data-testid` 锚，不要靠中文文案定位（改文案就红）：

| 锚 | 位置 |
|---|---|
| `tree-canvas` / `tree-node-<id>` / `tree-band-<depth>` | 进化树 |
| `node-drawer` | 节点抽屉 |
| `event-stream` / `event-stream-scroller` / `generation-<i>` | 事件流 |
| `significance-summary` | 显著性分布条 |
| `data-demo-card` / `data-probe-result` / `data-card-state` / `data-artifact-card` | 录入与总览 |

⚠️ jsdom 没有布局引擎，`getBoundingClientRect()` 恒为 0 —— **前端测试全绿也测不出容器塌陷**。
判布局必须上真实浏览器（`pnpm test:e2e`），配方见 skill `headless-spa-smoke-via-cdp`。

## 5. 先补一条失败的测试

按 §15 的完成定义：没有失败/边界测试就不算修。测试要落在**能区分根因的那一层**：

- 数据不对 ⇒ API 层测试（`tests/webapi/`），如 `test_failure_fixture.py` /
  `test_tree_showcase_fixture.py` —— 浏览器用例挂了时能区分"fixture 坏了"还是"前端坏了"；
- 转换/判定不对 ⇒ 纯函数测试（`tree-adapter.test.ts` / `significance.test.ts`）；
- 只有渲染不对 ⇒ 组件测试。

## 6. 修最小根因

改**出错的那一层**。禁止在组件里加 `if (值 === 0) 显示别的` 之类的特判来掩盖后端契约问题 ——
那是把 bug 搬到了别处，并且让下一处继续错。

## 7. 跑相关测试，再跑完整回归

```bash
python -m pytest tests/webapi -q        # 先跑快的那一层
cd web && pnpm test && pnpm lint && pnpm build
```

## 8. 跑完整回归（合并前必做）

```bash
python -m pytest tests/ -q              # 12–22 min，后台跑
cd web && pnpm test:e2e --project=chromium
```

## 硬性禁止

1. **只在组件里加特殊判断掩盖后端契约问题。**
2. **为了"看起来对"而造数据。** 缺能力就返回 `not_supported`，UI 禁用并说明原因（§15）。
3. **跳过第 1 步直接改前端。** 90% 的"前端 bug"在这一步就被否掉了。

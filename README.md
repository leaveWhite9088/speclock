# SpecLock

> **其他 spec 工具把文档放进 repo 让 agent 可以改；SpecLock 把文档放在只读 API 后面。**

SpecLock 是业务文档的**单一事实源（Single Source of Truth）平台**，为"AI 参与开发"的团队设计：

- 文档按 **大业务 → 小业务（文档）→ 模块** 三级管理，带两级语义化版本与结构化 diff；
- 开发 AI 只能通过**只读 API**（REST + MCP）读取**已发布版本**，物理上无法修改文档；
- AI 唯一的写出口是**提案（Proposal）**通道，经人审批发布后才生效。

约束是物理的（权限隔离），不是提示词约定。

## 核心特性

- **物理只读隔离** — 写端点与读端点分属两个 router、两套凭据（`human-*` / `agent-*`），agent key 对所有写接口 100% 返回 403
- **结构化 API 文档** — 模块的 API 区是递归字段模型（`object`/`array` 可无限嵌套 `children`），编辑与 diff 的真相源是结构化数据；发布时自动生成 OpenAPI 3.x YAML 供下游消费，用户全程不需要面对 YAML
- **两级版本** — 模块按自身 diff 独立递增 semver（破坏性 → MAJOR，新增 → MINOR，其余 PATCH）；任一模块发布时所属文档自动派生文档版本（manifest = 全部模块当前版本清单）
- **字段级 diff 与破坏性判定** — 基于递归 flatten 的点号路径（如 `response:GET /x:data.items.id`）；删除必填字段 / 删除整个 API / 类型或必填标志变更为破坏性，删除可选字段不算
- **分层索引树** — agent 一次调用 `get_index` 拿到 大业务→小业务→模块 三层概要树（模块节点带一句话摘要与完成标记），选中后再按需精读，上下文占用最小
- **提案通道** — AI 发现文档有误或缺失时提交提案，收件箱一键"批准并发布"，小变更从提出到发布 ≤2 分钟
- **完成状态跟踪** — 模块级 `completed` 标记（发布新版自动重置），agent 可过滤未完成模块，只做没做完的小业务
- **全链路审计** — 发布 / 提案 / 拉取 / ack 全部落 `AuditLog`

## 工作原理

```
项目 Project
 └── 大业务 Domain        （如：运营）
      └── 文档 Document   （如：经营日报；有自己的文档级版本）
           └── 模块 Block （= 小业务，如：数据采集模块）
                ├── 业务描述（Markdown）
                ├── API 列表（结构化表单，递归字段模型）
                └── 非功能性需求（Markdown）
```

```
人（human key）                 AI（agent key）
─────────────                 ─────────────
编辑草稿 ──► 发布 ──► 已发布版本 ◄── get_index / get_block（只读，可 pin 版本）
   ▲                                    │
   └── 批准并发布 ◄── 提案（唯一写出口）──┘
```

- **版本 pin**：`GET /blocks/{id}@{version}`、`GET /documents/{id}@{version}` 读不可变快照；草稿对 agent 永远不可见
- **发布两通道**：默认先 `dryRun` 预览（版本号 / delta 摘要 / 破坏性），确认后落库，破坏性变更须显式 `confirm=true`；`fastTrack` 秒批仅限非破坏性变更
- **ack 回执**：agent 声明"已按 模块@版本 实现"，与权威完成状态 `completed` 互补

## 快速开始（Windows）

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"

# 生成 demo 数据（运营大业务下 2 文档 × 4 模块，全部发布 1.0.0）
.venv/Scripts/python.exe -m speclock.seed

# 启动服务
.venv/Scripts/python.exe -m uvicorn speclock.main:app
```

管理 UI（开发态固定 key）：

```
http://127.0.0.1:8000/ui?key=human-dev-0000000000000000000000000001
```

> **安全提示**：固定 key（`human-dev-…1` / `agent-dev-…1`）仅供本地开发。
> 生产部署必须用环境变量 `SPECLOCK_HUMAN_KEY` / `SPECLOCK_AGENT_KEY` 覆盖为随机 key。

## Agent 接入

### REST API（只读 + 提案）

```bash
KEY="agent-xxx"
curl -H "X-API-Key: $KEY" http://127.0.0.1:8000/api/v1/index             # 三层索引树（大业务→小业务→模块，一次拿全图）
curl -H "X-API-Key: $KEY" "http://127.0.0.1:8000/api/v1/index?incomplete=true"  # 只看未完成模块（可叠加 domain=）
curl -H "X-API-Key: $KEY" http://127.0.0.1:8000/api/v1/blocks/1@1.0.0    # 精读模块（版本 pin）
curl -H "X-API-Key: $KEY" http://127.0.0.1:8000/api/v1/documents/1@1.2.0 # 文档 manifest（pin 历史快照）
curl -H "X-API-Key: $KEY" "http://127.0.0.1:8000/api/v1/blocks/1/diff?from=1.0.0&to=1.1.0"
curl -X POST -H "X-API-Key: $KEY" -d '{"version":"1.1.0","task_desc":"..."}' http://127.0.0.1:8000/api/v1/blocks/1/ack
curl -X POST -H "X-API-Key: $KEY" -d '{"block_id":1,"description":"...","suggestion":"..."}' http://127.0.0.1:8000/api/v1/proposals
```

### MCP（Claude Code 等）

`.mcp.json`（或 `claude mcp add` 等价配置）：

```json
{
  "mcpServers": {
    "speclock": {
      "command": "<项目路径>/.venv/Scripts/python.exe",
      "args": ["-m", "speclock.mcp_server"],
      "env": {
        "SPECLOCK_URL": "http://127.0.0.1:8000",
        "SPECLOCK_KEY": "agent-dev-0000000000000000000000000001"
      }
    }
  }
}
```

MCP server 暴露 **7 个工具**：

| 工具 | 用途 |
|---|---|
| `get_index` | 三层索引树（导航入口；模块节点带 `completed` 完成标记） |
| `get_block` | 读取模块已发布版本，可 pin 版本号 |
| `get_document` | 文档 manifest（模块→版本清单），可 pin 历史文档版本 |
| `get_diff` | 两个已发布版本之间的结构化 + 文本 diff |
| `ack_block` | 回执：声明「已按 模块@版本 实现」 |
| `submit_proposal` | 提交变更提案——AI 唯一的写出口 |
| `get_proposal` | 轮询提案状态 |

没有任何写文档的工具；为控制 AI 上下文占用，工具数保持精简，不加新工具。
管理 UI 的「AI 接入」页（`/ui/mcp`）提供可直接复制的配置与给 agent 的完整接入说明。

## 规则摘要

- **删除语义**：已发布内容不可消失。已发布模块的删除 = 归档（agent 读 404、索引排除、历史版本保留，并立即派生文档新版本）；归档模块可在归档管理页恢复或彻底删除（purge，不可恢复）；文档 / 大业务仅当其下无已发布模块时可删
- **完成状态**：发布新版本时 `completed` 自动重置为 False，`completed_version` 保留上次完成版本；ack 是单次回执，`completed` 是权威状态，MVP 阶段两者不自动联动
- **审计**：发布（模块 + 文档）/ 提案 / 拉取 / ack 全部写 `AuditLog`，「AI 接入」页展示最近 50 条 agent 活动

## 项目结构

```
speclock/
├── main.py        # FastAPI 装配：admin + agent + ui 三个 router
├── api_admin.py   # 写路由：仅 human-* key；发布 + 文档版本派生
├── api_agent.py   # 只读路由：仅 agent-* key；不存在任何文档写端点
├── auth.py        # X-API-Key 双凭据 + 审计
├── diffing.py     # 结构化 API 校验、字段级 delta、破坏性判定、OpenAPI 生成、两级 semver
├── mcp_server.py  # stdio MCP，7 工具，经 HTTP 调本系统 REST
├── ui.py          # 管理 UI（文档树 / 编辑 / diff / 提案收件箱 / 归档 / AI 接入页）
├── seed.py        # demo 数据 + 打印两个开发 key
└── templates/ static/
tests/             # pytest：auth / 发布 / diff / 归档 / 完成状态 / UI / MCP 页等
inject_ops.py      # 真实业务数据注入脚本（.inject_data/*.json → DB，先清空再注入，幂等）
```

## 开发

```bash
.venv/Scripts/python.exe -m pytest -v          # 跑测试
SPECLOCK_DB_URL=sqlite:///test.db .venv/Scripts/python.exe -m speclock.seed   # 用临时库 seed
.venv/Scripts/python.exe inject_ops.py         # 注入真实业务文档数据（清空后重建，幂等）
```

- 生产形态应把 admin 与 agent 拆成两个服务、两套凭据分开部署；当前用代码结构（双 router + 双 auth 依赖）保证这条边界可拆分
- 数据库默认 `./speclock.db`（SQLite），可用 `SPECLOCK_DB_URL` 覆盖

## License

[MIT](LICENSE)

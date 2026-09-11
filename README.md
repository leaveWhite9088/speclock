# SpecLock

> **Other spec tools put docs in your repo where agents can edit them. SpecLock puts docs behind a read-only API.**

SpecLock 是业务文档的**唯一信源**平台：文档按块（Block）管理、按块发布、带版本与 diff；
开发 AI 只能通过只读 API（REST + MCP）读取**已发布版本**；AI 唯一的写出口是**提案（Proposal）**
通道，提案经人审批发布后才生效。约束是物理的（权限隔离），不是提示词约定。

## 快速开始（Windows）

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # 或: pip install fastapi uvicorn "sqlalchemy>=2" pydantic jinja2 pyyaml httpx pytest "mcp>=2"

# 生成 demo 数据（项目「Demo 电商系统」→ 大业务「运营」→ 文档「经营日报」→
# 块「日报主表」「异常值规则」，各发布 1.0.0），并打印两个 key：
.venv/Scripts/python.exe -m speclock.seed
#   human key (读写/UI): human-xxxxxxxx...
#   agent key (只读+提案): agent-xxxxxxxx...

# 启动服务
.venv/Scripts/python.exe -m uvicorn speclock.main:app

# 管理 UI（用 human key）
#   http://127.0.0.1:8000/ui?key=human-xxxxxxxx...

# 跑测试
.venv/Scripts/python.exe -m pytest -v
```

## Agent 侧用法（REST）

```bash
curl -H "X-API-Key: agent-xxx" http://127.0.0.1:8000/api/v1/index            # 索引先行（≤8KB）
curl -H "X-API-Key: agent-xxx" http://127.0.0.1:8000/api/v1/blocks/1@1.0.0   # 版本 pin
curl -H "X-API-Key: agent-xxx" "http://127.0.0.1:8000/api/v1/blocks/1/diff?from=1.0.0&to=1.1.0"
curl -X POST -H "X-API-Key: agent-xxx" -d '{"version":"1.1.0","task_desc":"..."}' http://127.0.0.1:8000/api/v1/blocks/1/ack
curl -X POST -H "X-API-Key: agent-xxx" -d '{"block_id":1,"description":"...","suggestion":"..."}' http://127.0.0.1:8000/api/v1/proposals
```

## Claude Code MCP 配置

`.mcp.json`（或 `claude mcp add` 等价配置）：

```json
{
  "mcpServers": {
    "speclock": {
      "command": "D:/Project2/code-260911-docsystem/speclock/.venv/Scripts/python.exe",
      "args": ["-m", "speclock.mcp_server"],
      "env": {
        "SPECLOCK_BASE_URL": "http://127.0.0.1:8000",
        "SPECLOCK_AGENT_KEY": "agent-xxxxxxxx..."
      }
    }
  }
}
```

MCP server 恰好暴露 6 个工具：`get_index` / `get_block` / `get_diff` / `ack_block` /
`submit_proposal` / `get_proposal`。没有任何写文档的工具。

## 架构与红线

```
speclock/
├── main.py        # FastAPI 装配：admin + agent + ui 三个 router
├── api_admin.py   # 写路由：仅 human-* key（agent key 一律 403）
├── api_agent.py   # 只读路由：仅 agent-* key；不存在任何文档写端点
├── auth.py        # X-API-Key 双凭据 + 审计
├── diffing.py     # OpenAPI 字段级 diff、delta 生成、破坏性判定、semver 递增
├── mcp_server.py  # stdio MCP，6 工具，经 HTTP 调本系统 REST
└── seed.py        # demo 数据 + 打印两个 key
```

- **物理只读隔离**：写端点与读端点分属两个 router、两个 auth 依赖。生产形态应把 admin
  与 agent 拆成两个服务、两套凭据分开部署；MVP 用代码结构保证这条边界可拆分。
- **版本 pin**：`GET /api/v1/blocks/{id}@{version}` 读不可变快照；草稿对 agent 永远不可见。
- **fastTrack 秒批**：发布时服务端做 OpenAPI 字段级 diff；无破坏性变更（删字段/改类型）才允许
  `fastTrack=true`；破坏性变更必须 `confirm=true`，响应返回受影响字段清单。
- **delta**：每次发布自动生成 `{added, modified, removed}` 存入 `BlockVersion.delta_json`。
- **审计**：发布 / 提案 / 拉取 / ack 全部写 `AuditLog`。

## 验收标准对照（MVP 需求文档 §2.2）

| # | 标准 | 本仓库证据 |
|---|---|---|
| S1 | agent 凭据对所有写接口 100% 被拒 | `tests/test_auth.py` 枚举全部写端点断言 403；冒烟实测 5 个写端点全 403 |
| S2 | 单任务拉取 ≤3 块，索引 ≤8KB | `GET /index` 一行摘要/块；`test_index_is_one_line_per_block_and_small` 断言 ≤8KB（demo 实测 386B） |
| S3 | 小变更提出到发布 ≤2 分钟 | 提案 → 收件箱一键「批准并发布」；无破坏性变更支持 `fastTrack` 秒批 |
| S4 | 版本可钉住、历史可重放 | `GET /blocks/{id}@{version}` pin 快照；`test_version_pin_reads_exact_snapshot`；ack 回执记录 `块@版本` |
| S5 | 端到端：建块→发布→AI 读→提案→审批→再发布→AI 读新版 | `test_full_proposal_lifecycle` + 冒烟实测（见下） |

冒烟实测记录（uvicorn + curl，demo 数据）：agent 取索引（386B, 2 块）→ pin 拉 `blocks/1@1.0.0` →
提交提案（加 `sales_dod` 字段）→ human 审批发布 → 提案状态 `published @1.1.0` → agent 读到
`1.1.0`（delta: `added: prop:DailyReportRow.sales_dod`）→ pin 回 `1.0.0` 仍读到旧快照 →
diff `1.0.0→1.1.0` 非破坏 → ack `1.1.0` 成功；fastTrack 发布破坏性变更被 409 拒绝并返回受影响
清单，`confirm=true` 后发布为 `2.0.0`；agent key 调 5 个写端点全部 403；纯草稿块对 agent 404。

## License

MIT

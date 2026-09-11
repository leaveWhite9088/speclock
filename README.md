# SpecLock

> **Other spec tools put docs in your repo where agents can edit them. SpecLock puts docs behind a read-only API.**

SpecLock 是业务文档的**唯一信源**平台：文档按模块（Block）管理、分模块发布、带两级版本与 diff；
开发 AI 只能通过只读 API（REST + MCP）读取**已发布版本**；AI 唯一的写出口是**提案（Proposal）**
通道，提案经人审批发布后才生效。约束是物理的（权限隔离），不是提示词约定。

## 核心概念

```
项目 Project
 └── 大业务 Domain        （如：运营）
      └── 文档 Document   （如：经营日报；有自己的文档级版本）
           └── 模块 Block （= 小业务，如：数据采集模块 / 异常数据展示模块 / 历史记录模块）
                ├── 业务描述（Markdown）
                ├── API 列表（结构化表单：名称 / API 名(方法+路径) / 请求体字段表 / 响应体字段表）
                └── 非功能性需求（Markdown）
```

- 模块的 API 区是**结构化列表**，字段模型是递归的：`{name, type, required,
  description, children}`——类型为 `object` / `array` 的字段可以携带 `children`
  子字段（array 的 children 描述元素结构），层级不限。字段类型枚举：
  string/number/integer/boolean/array/object。`apis_json` 是编辑与 diff 的真相源；
  发布时自动生成 OpenAPI 3.x YAML（`openapi_yaml`，递归输出嵌套 schema）供机器/下游消费。
  用户全程不需要面对 YAML。
- **diff 与破坏性判定**基于 apis_json 递归 flatten，路径用点号表达
  （如 `response:GET /x:data.items.id: number`）；子字段的增删/类型变更同样识别。
  破坏性 = 删除必填字段 / 删除整个 API / 类型或必填标志变更；删除可选字段不算破坏性。
- **两级版本**：模块按自身 diff 独立递增 semver（破坏性 → MAJOR，新增字段 → MINOR，其余 PATCH）；
  任一模块发布成功时，所属文档自动派生一个**文档版本**（manifest = 该文档全部模块当前已发布版本
  清单）。文档版本规则：任一模块 MAJOR → 文档 MAJOR；否则任一模块 MINOR（含模块首发）→ 文档 MINOR；
  否则 PATCH。发布动作只有模块级，文档版本是派生物。

## 快速开始（Windows）

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # 或: pip install fastapi uvicorn "sqlalchemy>=2" pydantic jinja2 pyyaml httpx pytest "mcp>=2"

# 生成 demo 数据（运营大业务下「经营日报」4 模块 +「售罄率报表」4 模块，
# 全部发布 1.0.0，两个文档版本各派生至 1.3.0）。本地开发使用固定 key：
#   human key (读写/UI): human-dev-0000000000000000000000000001
#   agent key (只读+提案): agent-dev-0000000000000000000000000001
# （重 seed 不换 key；生产部署必须用 SPECLOCK_HUMAN_KEY / SPECLOCK_AGENT_KEY
#  环境变量覆盖为随机 key——固定 key 仅供本地开发！）
.venv/Scripts/python.exe -m speclock.seed

# 启动服务
.venv/Scripts/python.exe -m uvicorn speclock.main:app

# 管理 UI（开发态固定 key）
#   http://127.0.0.1:8000/ui?key=human-dev-0000000000000000000000000001

# 跑测试
.venv/Scripts/python.exe -m pytest -v
```

## Agent 侧用法（REST）

```bash
curl -H "X-API-Key: agent-xxx" http://127.0.0.1:8000/api/v1/index             # 模块索引先行（≤8KB）
curl -H "X-API-Key: agent-xxx" http://127.0.0.1:8000/api/v1/documents         # 文档列表 + 文档版本
curl -H "X-API-Key: agent-xxx" http://127.0.0.1:8000/api/v1/documents/1@1.2.0 # 文档 manifest（pin）
curl -H "X-API-Key: agent-xxx" http://127.0.0.1:8000/api/v1/blocks/1@1.0.0    # 模块版本 pin
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
        "SPECLOCK_AGENT_KEY": "agent-dev-0000000000000000000000000001"
      }
    }
  }
}
```

MCP server 恰好暴露 8 个工具：`get_index` / `get_block` / `get_diff` / `ack_block` /
`submit_proposal` / `get_proposal` / `get_documents` / `get_document`。
没有任何写文档的工具。

## Web UI

- 文档树：大业务 → 文档（含文档版本徽章）→ 模块；三层都有「新建 / 重命名 / 删除」入口
  （prompt/confirm 级交互）
- **模块查看页**（只读，看已发布版本，可切换版本）：业务描述 + API **列表**（序号/名称/
  API 名/方法徽章）→ 点进单条 API **详情视图**（请求体/响应体字段树，缩进树形展示嵌套
  结构，面包屑返回）；版本历史区每个版本带「与上一版对比」一键跳 diff；全程无 YAML
- 模块编辑页：业务描述 textarea + **API 填表区**（API 条目默认折叠为一行摘要——序号/
  名称/API 名/方法徽章/字段数统计，点「展开」才显示字段树填表区；新增 API 默认展开；
  object/array 字段可「+子字段」无限层级下钻，删父级联删子；全程表单控件，无 YAML）
  + 非功能性需求 textarea + 保存草稿 / 秒批发布按钮
- 文档页：文档版本历史 + 每个版本的模块版本清单（manifest）
- diff 页（结构化优先）：顶部摘要条（版本 from→to、破坏性红/绿徽章、新增/修改/删除计数、
  change_note，默认对比上一版→当前版，可任选两版）→ 按 API 分组的 delta 表格（点号路径、
  类型、必填、说明；删除行红色删除线、新增绿色、修改橙色）→ 业务描述/非功能性需求文本
  diff（+绿/-红，可折叠区块）。不再展示整段 YAML 文本 diff
- 提案收件箱（一键批准并发布 / 拒绝）、「已完成」回执看板

> 破坏性判定细化：**删除可选字段（required=false）视为非破坏性**，可 fastTrack；删除必填
> 字段、删除整个 API、任何类型/必填标志变更仍为破坏性，必须 confirm=true。

## 删除语义（已发布内容不可消失）

| 对象 | 删除行为 |
|---|---|
| 草稿态模块 | 直接删除 |
| 已发布模块 | 删除 = 归档（agent 读 404、index 排除、下一文档版本 manifest 移除，历史版本保留可查）；`POST /blocks/{id}/restore` 可恢复 |
| 文档 / 大业务 | 仅当其下无已发布模块时允许删除，否则 409 并列出已发布模块，提示先归档 |

## Demo 数据结构

```
Demo 电商系统
 └── 运营
      ├── 经营日报（文档 @1.3.0）
      │    ├── 数据采集模块 @1.0.0        3 个 API：GET collect-status（items[] 嵌套）/ GET collect-items / POST recollect（item_ids[]）
      │    ├── 异常数据展示模块 @1.0.0    GET  /api/daily-report/anomalies
      │    ├── 历史记录模块 @1.0.0        GET  /api/daily-report/history
      │    └── 异常规则配置模块 @1.0.0    POST /api/daily-report/anomaly-rules（rule/scope 两层 object 嵌套）
      └── 售罄率报表（文档 @1.3.0）
           ├── 数据采集模块 @1.0.0        GET  /api/sellout-report/collect-status
           ├── 异常数据展示模块 @1.0.0    GET  /api/sellout-report/anomalies
           ├── 历史版本记录模块 @1.0.0    GET  /api/sellout-report/history（snapshots→stores→skus 三层 array 嵌套）
           └── 异常规则配置模块 @1.0.0    POST /api/sellout-report/anomaly-rules（condition/scope 嵌套）
```

## 架构与红线

```
speclock/
├── main.py        # FastAPI 装配：admin + agent + ui 三个 router
├── api_admin.py   # 写路由：仅 human-* key（agent key 一律 403）；发布 + 文档版本派生
├── api_agent.py   # 只读路由：仅 agent-* key；不存在任何文档写端点
├── auth.py        # X-API-Key 双凭据 + 审计
├── diffing.py     # 结构化 API 校验（递归嵌套）、字段级 delta、破坏性判定、OpenAPI 生成、两级 semver
├── mcp_server.py  # stdio MCP，8 工具，经 HTTP 调本系统 REST
└── seed.py        # demo 数据（2 文档 × 4 模块）+ 打印两个 key
```

- **物理只读隔离**：写端点与读端点分属两个 router、两个 auth 依赖。生产形态应把 admin
  与 agent 拆成两个服务、两套凭据分开部署；MVP 用代码结构保证这条边界可拆分。
- **版本 pin**：`GET /api/v1/blocks/{id}@{version}`、`GET /api/v1/documents/{id}@{version}`
  读不可变快照；草稿对 agent 永远不可见。
- **fastTrack 秒批**：发布时服务端基于 `apis_json` 做字段级 diff；无破坏性变更（删字段/改类型）
  才允许 `fastTrack=true`；破坏性变更必须 `confirm=true`，响应返回受影响字段清单。
- **delta**：每次发布自动生成 `{added, modified, removed}` 存入 `BlockVersion.delta_json`。
- **审计**：发布（模块+文档）/ 提案 / 拉取 / ack 全部写 `AuditLog`。

## 验收标准对照（MVP 需求文档 §2.2）

| # | 标准 | 本仓库证据 |
|---|---|---|
| S1 | agent 凭据对所有写接口 100% 被拒 | `tests/test_auth.py` 枚举全部写端点断言 403；冒烟实测写端点 403 |
| S2 | 单任务拉取 ≤3 块，索引 ≤8KB | `GET /index` 一行摘要/模块；`test_index_is_one_line_per_block_and_small` 断言 ≤8KB |
| S3 | 小变更提出到发布 ≤2 分钟 | 提案 → 收件箱一键「批准并发布」；无破坏性变更支持 `fastTrack` 秒批 |
| S4 | 版本可钉住、历史可重放 | 模块与文档两级 pin；`test_version_pin_reads_exact_snapshot`、文档 manifest pin 测试；ack 回执记录 `模块@版本` |
| S5 | 端到端：建块→发布→AI 读→提案→审批→再发布→AI 读新版 | `test_full_proposal_lifecycle` + 冒烟实测 |

冒烟实测记录（uvicorn + curl，demo 数据）：seed 后 2 文档 × 4 模块各 @1.0.0、文档版本各派生至 1.3.0 →
嵌套字段经 UI 提交接口（PUT apis，object/array 多层 children）保存与读取一致 →
fastTrack 发布嵌套子字段新增 → delta 为点号路径
`request:POST ...:rule.scope.channels.channel_id`，模块 1.1.0、文档 1.4.0 →
新建大业务→文档→模块→发布→agent 可读（200）→ 归档已发布模块：agent 404、index 排除、
下一文档 manifest 移除 → 删除含已发布模块的文档 409 并列出已发布模块 → restore 恢复后 agent 200 →
agent key 对全部写端点（含三层 CRUD 新端点）403。

## License

MIT

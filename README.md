# SpecLock

> **其他 spec 工具把文档放进 repo 让 agent 可以改；SpecLock 把文档放在只读 API 后面。**

![Python](https://img.shields.io/badge/python-%E2%89%A53.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-%E2%89%A50.110-009688)
![License](https://img.shields.io/badge/license-MIT-green)

SpecLock 是业务文档的**单一事实源（Single Source of Truth）平台**，为"AI 参与开发"的团队设计：

- 文档按 **项目 → 大业务 → 文档 → 模块** 四级管理，带两级语义化版本与结构化 diff；
- 开发 AI 只能通过**只读 API**（REST + MCP）读取**已发布版本**，物理上无法修改文档；
- AI 唯一的写出口是**提案（Proposal）**通道，经人审批发布后才生效。

约束是物理的（权限隔离），不是提示词约定。

## 目录

- [为什么需要它](#为什么需要它)
- [核心特性](#核心特性)
- [工作原理](#工作原理)
- [文档模型](#文档模型)
- [快速开始](#快速开始)
- [配置与环境切换](#配置与环境切换)
- [密钥管理](#密钥管理)
- [Agent 接入](#agent-接入)
- [规则摘要](#规则摘要)
- [项目结构](#项目结构)
- [开发](#开发)
- [License](#license)

## 为什么需要它

AI 辅助开发中有两个已被一线实践反复验证的问题：

1. **业务漂移**：开发 AI 为理解业务必须参考文档，但只要它能写，就一定会改；业务被改 → 对端提新需求 → 无限循环。
2. **文档与代码脱节**：文档靠人脑维护，执行阶段无人遵守，停留在项目初期丧失指导意义。

根因判断：AI 对文档只要拥有写权限就一定会改文档。因此约束必须是**物理的**（权限隔离），不能是**约定的**（提示词）。SpecLock 把这条原则落到代码结构里：写端点与读端点分属两个 router、两套凭据，agent 凭据对所有写接口 100% 返回 403。

## 核心特性

- **物理只读隔离** — 写端点（admin router，仅 `human-*` key）与读端点（agent router，仅 `agent-*` key）物理分离；不存在任何接受 agent 凭据的文档写端点
- **项目级文档隔离** — 项目是文档隔离单元，每个项目有独立的一套 大业务→文档→模块；agent key 可绑定到单个项目，绑定后跨项目的模块/文档/ack/提案访问一律 404；不绑定的 key 保持全局可见
- **结构化文档模型** — 模块内容不是一整段散文，而是：业务背景（叙述）+ 业务规则清单（结构化，逐条可 diff）+ API 列表（结构化，每条带端点语义）+ 非功能性需求；发布时强制结构完备性校验（见[文档模型](#文档模型)）
- **结构化 API 文档** — API 区是递归字段模型（`object`/`array` 可无限嵌套 `children`），编辑与 diff 的真相源是结构化数据；发布时自动生成 OpenAPI 3.x YAML 供下游消费，全程不需要面对 YAML
- **两级版本** — 模块按自身 diff 独立递增 semver（破坏性 → MAJOR，新增 → MINOR，其余 PATCH）；任一模块发布时所属文档自动派生文档版本（manifest = 全部模块当前版本清单）
- **字段级 diff 与破坏性判定** — 基于递归 flatten 的点号路径（如 `response:GET /x:data.items.id`）；删除必填字段 / 删除整个 API / 类型或必填标志变更为破坏性，删除可选字段不算
- **分层索引树** — agent 一次调用 `get_index` 拿到 大业务→文档→模块 三层概要树（模块节点带一句话摘要与完成标记），选中后再按需精读，上下文占用最小
- **提案通道** — AI 发现文档有误或缺失时提交提案，收件箱一键"批准并发布"，小变更从提出到发布 ≤2 分钟
- **完成状态跟踪** — 模块级 `completed` 标记（发布新版自动重置），agent 可过滤未完成模块，只做没做完的小业务
- **全链路审计** — 发布 / 提案 / 拉取 / ack 全部落 `AuditLog`

## 工作原理

```
项目 Project                     （文档隔离单元，agent key 可绑定）
 └── 大业务 Domain               （如：运营 / 采购 / 商品）
      └── 文档 Document          （如：经营日报；有自己的文档级版本）
           └── 模块 Block        （= 小业务，如：数据采集模块）
                ├── 业务背景与流程（Markdown，必填）
                ├── 业务规则清单（结构化条目，必填，逐条可 diff）
                ├── API 列表（结构化表单；每条带端点语义 desc）
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

## 文档模型

模块内容的结构及发布时的硬性校验：

| 字段 | 必填 | 校验 |
|---|---|---|
| 业务背景与流程 `content_md` | 是 | 非空（≥20 字符） |
| 业务规则清单 `rules` | 是（≥1 条） | 每条 `name`/`detail` 非空；发布 diff 精确到条 |
| API 端点语义 `apis[].desc` | 是 | 每条 API 非空，报错指明哪条缺失 |
| 非功能性需求 `nfr_md` | 否 | — |

设计判据：规则与 API 是"后端不可猜"的东西（公式、阈值、状态机、端点形状），必须结构化才能被机器校验；叙述性背景保留自由 Markdown。校验在发布关口物理执行（422 + 具体缺失清单），AI 写入走提案通道时被同一校验覆盖——对 AI 的约束同样是拒绝+可操作报错，而不是提示词。

## 快速开始

```bash
# Windows
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"

# 生成 demo 数据（运营大业务下 2 文档 × 4 模块，全部发布 1.0.0）
.venv/Scripts/python.exe -m speclock.seed

# 启动服务（读取 speclock.toml 当前环境的 host/port）
.venv/Scripts/python.exe -m speclock.main
```

```bash
# Linux / macOS
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m speclock.seed
.venv/bin/python -m speclock.main
```

管理 UI（开发态固定 key）：

```
http://127.0.0.1:8000/ui?key=human-dev-0000000000000000000000000001
```

> **安全提示**：固定 key（`human-dev-…1` / `agent-dev-…1`）仅供本地开发。
> 生产部署必须用环境变量 `SPECLOCK_HUMAN_KEY` / `SPECLOCK_AGENT_KEY` 覆盖为随机 key。

## 配置与环境切换

仓库根目录 `speclock.toml` 管理多套环境，改 `active` 一行即切换（也可用环境变量 `SPECLOCK_ENV` 覆盖，systemd/CI 场景推荐）：

```toml
active = "local"

[local]
db_url = "sqlite:///speclock.db"   # 数据库（SPECLOCK_DB_URL 环境变量优先）
host = "127.0.0.1"                 # 监听地址
port = 8000                        # 监听端口
public_url = ""                    # MCP 页面对外地址；空 = 按访问地址动态生成

[server]
db_url = "sqlite:////opt/speclock/speclock.db"
host = "0.0.0.0"
port = 8000
public_url = "https://docs.example.com"
```

配置文件位置可用 `SPECLOCK_CONFIG` 指定；文件缺失时回退 local 默认值，裸 checkout 也能跑。

## 密钥管理

- 密钥**仅在创建时可见一次**：`POST /api/v1/keys` 的响应是唯一能看到明文的地方；数据库只存 SHA-256 哈希与脱敏 hint（如 `human-…26c7`），丢失只能重新生成
- 管理入口：UI「密钥管理」页（`/ui/keys`）——新建（human/agent + 标签 + 可选项目绑定）、列表（只显示 hint）、吊销（删除即生效，下次请求 401；最后一把 human key 拒绝删除）
- 项目绑定仅对 agent key 生效：绑定后该 key 只能读取所选项目的文档；human key 是管理端，始终全局
- 审计与 ack 回执只记录 hint，不记录明文

## Agent 接入

### REST API（只读 + 提案）

```bash
KEY="agent-xxx"
curl -H "X-API-Key: $KEY" http://127.0.0.1:8000/api/v1/index             # 三层索引树（一次拿全图）
curl -H "X-API-Key: $KEY" "http://127.0.0.1:8000/api/v1/index?incomplete=true"  # 只看未完成模块
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
        "SPECLOCK_KEY": "<你的 agent key——密钥管理页生成，仅此一次可见>"
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

没有任何写文档的工具；为控制 AI 上下文占用，工具数保持精简。管理 UI 的「AI 接入」页（`/ui/mcp`）提供可直接复制的配置与给 agent 的完整接入说明，`SPECLOCK_URL` 按当前环境自动生成。

## 规则摘要

- **删除语义**：已发布内容不可消失。已发布模块的删除 = 归档（agent 读 404、索引排除、历史版本保留，并立即派生文档新版本）；归档模块可在归档管理页恢复或彻底删除（purge，不可恢复）；文档 / 大业务 / 项目仅当其下无已发布模块时可删
- **完成状态**：发布新版本时 `completed` 自动重置为 False，`completed_version` 保留上次完成版本；ack 是单次回执，`completed` 是权威状态，两者不自动联动
- **审计**：发布（模块 + 文档）/ 提案 / 拉取 / ack 全部写 `AuditLog`，「AI 接入」页展示最近 50 条 agent 活动

## 项目结构

```
speclock/
├── main.py        # FastAPI 装配 + 按环境启动（python -m speclock.main）
├── settings.py    # speclock.toml 多环境配置加载（active / SPECLOCK_ENV）
├── api_admin.py   # 写路由：仅 human-* key；发布 + 结构完备性校验 + 文档版本派生
├── api_agent.py   # 只读路由：仅 agent-* key；项目隔离；不存在任何文档写端点
├── auth.py        # X-API-Key 双凭据 + 审计
├── diffing.py     # 结构化 API/规则校验、字段级 delta、破坏性判定、OpenAPI 生成、两级 semver
├── mcp_server.py  # stdio MCP，7 工具，经 HTTP 调本系统 REST
├── ui.py          # 管理 UI（文档树 / 编辑 / diff / 提案收件箱 / 归档 / 密钥 / AI 接入页）
├── seed.py        # demo 数据 + 打印两个开发 key
└── templates/ static/
tests/             # pytest：auth / 发布 / diff / 归档 / 完成状态 / 项目隔离 / 环境配置 / UI 等
inject_ops.py      # 真实业务数据注入脚本（.inject_data/*.json → DB，先清空再注入，幂等）
```

## 开发

```bash
.venv/Scripts/python.exe -m pytest -v          # 跑测试
SPECLOCK_DB_URL=sqlite:///test.db .venv/Scripts/python.exe -m speclock.seed   # 用临时库 seed
.venv/Scripts/python.exe inject_ops.py         # 注入真实业务文档数据（清空后重建，幂等）
```

- 生产形态应把 admin 与 agent 拆成两个服务、两套凭据分开部署；当前用代码结构（双 router + 双 auth 依赖）保证这条边界可拆分
- 数据库默认 `./speclock.db`（SQLite），可用 `SPECLOCK_DB_URL` 环境变量或 `speclock.toml` 覆盖

## License

[MIT](LICENSE)

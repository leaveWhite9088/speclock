# SpecLock

> **其他 spec 工具把文档放进 repo 让 agent 可以改；SpecLock 把文档放在只读 API 后面。**

![Python](https://img.shields.io/badge/python-%E2%89%A53.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-%E2%89%A50.110-009688)
![License](https://img.shields.io/badge/license-MIT-green)

SpecLock 是业务文档的**单一事实源（Single Source of Truth）平台**，为"AI 参与开发"的团队设计：

- 文档按 **项目 → 大业务 → 小业务 → 模块** 四级管理，带两级语义化版本与结构化 diff；
- 开发 AI 通过 REST + MCP 读取**已发布版本**；
- 规格库**只有一条写入通道**：需求 Agent 整理**审核单（Change Request）**→ 人批准 → 需求 Agent 在已批准的审核单下提交 **Commit**；人不直接改库，Agent 也批准不了任何东西。SpecLock 自己不是 Agent，只提供让外部 Agent 接入的接口。

约束是物理的（权限隔离），不是提示词约定。

架构：**FastAPI 纯 JSON API + Vue 3 展示网页（`web/`，参考实现）**。后端只出 JSON；网页是**只读展示**（文档树、模块与版本、审核单、待办、归档、AI 接入说明），不提供任何修改操作，只调用公开 REST 接口，别人想自己做一个同样能接。构建产物（`web/dist/`）存在时由同一 FastAPI 进程顺带托管，不构建或不打开它都不影响 Core。所有修改都由 Agent 经 MCP 完成。

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

根因判断：AI 对文档只要拥有写权限就一定会改文档。因此约束必须是**物理的**（权限隔离），不能是**约定的**（提示词）。SpecLock 把这条原则落到代码结构里：key 绑定**角色**，角色是**权限集合**；批准审核单是人类专属权限，挂不到任何 agent 类角色上，agent 凭据对批准接口 100% 返回 403。

## 核心特性

- **角色与权限** — key 绑定角色，角色是权限集合（权限目录由代码定义，角色与映射可自定义，预置 admin / reviewer / requirements-agent / executor-agent / tester-agent / scanner-agent；scanner 只能读和提建议，不能开单）；接口按权限放行。人类专属权限（批准 / 驳回审核单、管理项目与密钥）不能挂在 agent 类角色上，约束是物理的
- **审核单 + Commit 是唯一写入通道** — 没有任何直接建 / 改 / 发布模块的接口。审核单只含业务意图（为什么变、变成什么样、不再成立的旧认知、验收条件、影响说明），提交即冻结并带内容哈希，批准后不可改；批准渠道（按钮 / CLI / 自然语言）与原话留痕；Commit 是已批准审核单下的原子写入，整体成功或整体回滚
- **项目级文档隔离** — 项目是文档隔离单元，每个项目有独立的一套 大业务→小业务→模块；key 可绑定到单个项目，绑定后跨项目的模块 / 文档 / 待办 / 审核单访问一律 404；不绑定的 key 保持全局可见
- **结构化文档模型** — 模块内容不是一整段散文，而是：业务背景（叙述）+ 业务规则清单 + 验收条件（均为结构化，每条带稳定 id，逐条可 diff）+ API 列表（结构化，每条带端点语义）；发布时强制结构完备性校验（见[文档模型](#文档模型)）
- **结构化 API 文档** — API 区是递归字段模型（`object`/`array` 可无限嵌套 `children`），编辑与 diff 的真相源是结构化数据；发布时自动生成 OpenAPI 3.x YAML 供下游消费，全程不需要面对 YAML
- **两级版本** — 模块独立递增 semver，级别标签由代码按结构化 diff 机械算出（有任何删除或修改 → MAJOR，只有新增 → MINOR，其余 PATCH），只是给外部 Agent 的参考，Core 不规定它们据此该做什么；任一模块发布时所属小业务自动派生小业务版本（manifest = 全部模块当前版本清单）
- **字段级 diff 与版本标签** — 基于递归 flatten 的点号路径（如 `response:GET /x:data.items.id`）；API 侧任何删除（含可选字段）或类型 / 必填标志变更都算 MAJOR 级变更；规则与验收条件按稳定 id 匹配，详述变了算修改，只改名称算 renamed（PATCH）
- **分层索引树** — agent 一次调用 `get_index` 拿到 大业务→小业务→模块 三层概要树（小业务节点带可选的一句话简述）（模块节点带一句话摘要与当前版本的执行状态），选中后再按需精读，上下文占用最小
- **内部整理（纯重组免人批准）** — 审核单有 `kind`：业务变更（默认，须人批准）或内部整理（改名、搬模块、拆分 / 合并，由需求 Agent 自行判定并写明理由，提交即生效，需要 `cr.internal` 权限）；Core 机械兜底：落地时规则 / 验收条件 / API 的条目总和必须一字未变，否则 422 回滚；新操作 `move_block`；全程留痕，网页标记「内部整理」
- **溯源与覆盖检查** — 每个模块版本 / 小业务版本记录产生它的 `cr_id` + `commit_id`，从版本能追到「为什么改」，从审核单能追到全部 Commit 与受影响版本；Commit 声明满足审核单的哪些验收条件（`covers`），审核单要进入 `applied`，全部验收条件必须被覆盖（Core 只做这个机械检查，不判断语义）
- **执行记录（规格状态与执行状态分开）** — 每个已发布的模块版本自动产生一条执行记录：`pending → in_progress → implemented → verified`，另有 `blocked` / `failed`（可重新领取）和 `superseded`（模块发布新版本后，旧版本上没做完的记录被取代）。执行 Agent 领取任务时拿到**锁定到该版本**的完整规格；提交实现结果必须逐条验收条件给 pass + 证据；**测试 Agent 独立验收**，验证者不能是实现者（同一把 key 403）。每次转换写只追加的事件历史。待办看板 `/work` 与模块页版本历史展示状态与事件
- **全链路审计** — 审核单流转 / Commit / 发布 / 拉取 / 执行记录转换 / 密钥与角色变更全部落 `AuditLog`

## 工作原理

```
项目 Project                     （文档隔离单元，agent key 可绑定）
 └── 大业务 Business             （如：运营 / 采购 / 商品）
      └── 小业务 Capability      （如：经营日报；只聚合模块，版本 = 其全部模块当前版本的快照）
           └── 模块 Block        （= 小业务，如：数据采集模块）
                ├── 业务背景与流程（Markdown，必填）
                ├── 业务规则清单（结构化条目，必填，每条带稳定 id R-n）
                ├── 验收条件（结构化条目，必填，每条带稳定 id AC-n）
                └── API 列表（结构化表单；每条带端点语义 desc）
```

```
人（cr.approve）               需求 Agent（cr.write / commit.write）        执行 Agent（exec.write）→ 测试 Agent（exec.verify）
─────────────                 ─────────────────────────────              ────────────────────────────────
                              创建审核单（draft）
                              提交（pending_review，内容冻结 + 哈希）
批准 / 驳回（按钮 / CLI / 自然语言）──►
                              approved ──► 提交 Commit（原子写入并发布）──► 已发布版本 ◄── get_index / get_block（只读，可 pin）
                              complete（覆盖检查通过）──► applied
                              发布 ──► 自动产生执行记录（pending）──► 领取 ──► 实现 ──► 独立验收（verified）
```

- **版本 pin**：`GET /blocks/{id}@{version}`、`GET /capabilities/{id}@{version}` 读不可变快照；草稿对 agent 永远不可见
- **发布**：Commit 应用 ops 后自动发布（没有草稿阶段、没有二次确认闸门——授权已在审核单上完成）；可先 `dryRun` 预览版本号 / 级别标签 / delta，预览完整执行后回滚，不落库。同一个 Commit 里每个被改的小业务只派生一个小业务版本
- **执行记录**：每个已发布模块版本一条；`GET /work` 是待办队列（`status=pending` 待领取、`implemented` 待验收、`blocked` 等业务答复），`POST /work/{id}/claim` 领取并拿到锁定版本的规格，`/blocked` `/failed` 报告，`/implementation` 提交逐条验收结果，`/verification` 独立验收。业务上卡住（blocked）由需求 Agent 经审核单发布新版本解决，旧记录随之被取代，不需要额外机制

## 文档模型

模块内容的结构及发布时的硬性校验：

| 字段 | 必填 | 校验 |
|---|---|---|
| 业务背景与流程 `content_md` | 是 | 非空（≥20 字符） |
| 业务规则清单 `rules` | 是（≥1 条） | 每条 `name`/`detail` 非空；发布 diff 精确到条 |
| 验收条件 `acceptance` | 是（≥1 条） | 每条 `name`/`detail` 非空；发布 diff 精确到条 |
| API 端点语义 `apis[].desc` | 是 | 每条 API 非空，报错指明哪条缺失 |

规则与验收条件的每一条带**稳定 id**（`R-1` / `AC-1`）：创建时由服务端分配，之后不变，编号取已用最大编号 + 1，条目删除后也不复用。Commit 里的 `rule_ops` / `acceptance_ops` 按 id 定位（upsert + id 修改，upsert 不带 id 新增，delete + id 删除，id 不存在 409）。

设计判据：规则与 API 是"后端不可猜"的东西（公式、阈值、状态机、端点形状），必须结构化才能被机器校验；叙述性背景保留自由 Markdown。校验在发布关口物理执行（422 + 具体缺失清单），Agent 的 Commit 被同一校验覆盖——对 AI 的约束同样是拒绝+可操作报错，而不是提示词。

## 快速开始

```bash
# Windows
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"

# 生成 demo 数据（运营大业务下 2 小业务 × 4 模块，全部发布 1.0.0）
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

展示网页是 Vue 3 SPA（只读）。想从零开始（空库，只有一个空项目和一把 admin key），用 `python -m speclock.seed --empty`。构建后由后端顺带托管：

```bash
cd web && npm install && npm run build   # 产出 web/dist/（已 gitignore）
# 启动后端后访问 http://127.0.0.1:8000/ ，登录页粘贴 human key 进入
```

前端开发模式（热更新，vite 把 `/api` 代理到 8000 端口的后端）：

```bash
cd web && npm install && npm run dev     # 默认 http://127.0.0.1:5173/
```

开发态固定 key（seed 只生成这一把 admin key，拥有全部权限，人和 Agent 共用）：`human-dev-0000000000000000000000000001`；MCP 的 `SPECLOCK_KEY` 填它即可。所有 API 请求带 `X-API-Key` 头。

> SpecLock 是**本机个人使用**的需求管理工具，不是为公网部署设计的。固定 key 仅供本地开发；想换成随机 key 用环境变量 `SPECLOCK_ADMIN_KEY` 覆盖。
> 编码阶段暂不区分人和 Agent 的 key；角色与权限机制保留在代码里，将来需要分权时再启用。

## 配置与环境切换

仓库根目录 `speclock.toml` 管理多套环境，改 `active` 一行即切换（也可用环境变量 `SPECLOCK_ENV` 覆盖，systemd/CI 场景推荐）：

```toml
active = "local"

[local]
db_url = "sqlite:///speclock.db"   # 数据库（SPECLOCK_DB_URL 环境变量优先）
host = "127.0.0.1"                 # 监听地址
port = 8000                        # 监听端口
public_url = ""                    # 保留字段，当前未被服务端使用（SPA 按访问地址自动生成接入配置）

[server]
db_url = "sqlite:////opt/speclock/speclock.db"
host = "0.0.0.0"
port = 8000
public_url = "https://docs.example.com"
```

配置文件位置可用 `SPECLOCK_CONFIG` 指定；文件缺失时回退 local 默认值，裸 checkout 也能跑。

## 密钥管理

- 密钥**仅在创建时可见一次**：`POST /api/v1/keys` 的响应是唯一能看到明文的地方；数据库只存 SHA-256 哈希与脱敏 hint（如 `human-…26c7`），丢失只能重新生成
- 创建 key 时选**角色**（`POST /api/v1/keys {role, label, project_id?, via?, evidence?}`），key 类别（human-* / agent-*）由角色的 kind 决定；**不预置多把 key**：seed 只发一把 admin key，其余由持有 admin key 的 Agent 经 MCP `create_api_key` 创建——必须先问人，附人同意的原话（`via=natural_language` 不带 `evidence` 会 422，来源与原话写进审计）；`speclock-cli key create` 是兜底；吊销即生效（下次请求 401）；拥有 `key.manage` 的最后一把 human key 拒绝删除
- **角色与权限**：权限目录由代码定义（`GET /api/v1/permissions`），角色可自定义（`/api/v1/roles` 增删改，预置角色可改权限、不可删）。预置：`admin`（全部）、`reviewer`（读 + 批准 / 驳回）、`requirements-agent`（读 + 整理审核单 + 内部整理 + 提交 Commit）、`executor-agent`（读 + 领取 / 实现）、`tester-agent`（读 + 独立验收）、`scanner-agent`（读规格 / 审核单 / 待办，只提建议，不能开单）。agent 类角色挂不上人类专属权限（`cr.approve` / `project.manage` / `key.manage`），改权限也不能让系统里没有管理员
- **给各目录的 Agent 发身份**：同一目录下多个 Agent 彼此看得见对方的文件，身份靠各目录 AGENTS.md 里的提示词。[AGENT_IDENTITY_TEMPLATE.md](AGENT_IDENTITY_TEMPLATE.md) 是模板：一段通用部分（先 `whoami`、已有 key 不重复创建、创建 key 是危险操作必须先问人）加需求 / 执行 / 测试三个角色部分，复制到对应目录的 AGENTS.md 并填好「我的 SpecLock 身份」。key 由人用 `speclock-cli key create` 创建，或在人同意后由持有 admin key 的 Agent 创建，创建后用 `use_api_key` 立即切换使用，不需要重启客户端
- 项目绑定对所有 key 生效：绑定后该 key 只能访问所选项目；不绑定 = 全局
- `GET /api/v1/me` 返回当前 key 的角色与权限
- 审计只记录 hint，不记录明文

## Agent 接入

### 审核单 → Commit（唯一写入通道）

```bash
REQ="agent-xxx"   # requirements-agent 角色的 key
H="http://127.0.0.1:8000/api/v1"
# 1. 需求 Agent 建单（草稿），只写业务意图；验收条件的 id（AC-n）由服务端分配
curl -X POST -H "X-API-Key: $REQ" -H "Content-Type: application/json" $H/change-requests -d '{"title":"日报口径调整","intent":"财务要求销售额含退款","expected_outcome":"日报销售额含退款","obsolete":["销售额不含退款"],"acceptance":[{"name":"口径一致","detail":"日报销售额与财务报表一致"}],"project_id":1}'
curl -X POST -H "X-API-Key: $REQ" $H/change-requests/1/submit           # 提交：内容冻结 + 内容哈希
# 2. 人批准（审核页按钮 / CLI / 自然语言，都必须出示人类 key，且带上看过的内容哈希）
speclock-cli cr approve 1                                              # 或 --hash <哈希前缀>
# 3. 需求 Agent 在已批准的审核单下提交 Commit：一组 ops，原子写入并发布，covers 声明满足的验收条件
curl -X POST -H "X-API-Key: $REQ" -H "Content-Type: application/json" $H/change-requests/1/commits -d '{"covers":["AC-1"],"ops":[{"op":"update_block","id":1,"rule_ops":[{"op":"upsert","id":"R-1","entry":{"name":"销售额口径","detail":"支付成功订单金额合计（含退款）"}}]}]}'
curl -X POST -H "X-API-Key: $REQ" $H/change-requests/1/complete        # 覆盖检查通过 → applied
```

Commit 的 ops：`create_business` / `update_business` / `create_capability` / `update_capability` / `create_block` / `update_block`（整体替换 `rules` / `apis` / `acceptance`，或增量 `rule_ops` / `api_ops` / `acceptance_ops`）/ `archive_block` / `restore_block` / `move_block`（搬到另一个小业务，保留身份与历史）；同一 Commit 里先建的对象起 `ref` 名，后面用 `"$ref"` 引用其 id。`dryRun: true` 预览不落库。

### 读规格（REST）

```bash
KEY="agent-xxx"
curl -H "X-API-Key: $KEY" http://127.0.0.1:8000/api/v1/index             # 三层索引树（一次拿全图）
curl -H "X-API-Key: $KEY" "http://127.0.0.1:8000/api/v1/work?status=pending"    # 待办队列
curl -H "X-API-Key: $KEY" http://127.0.0.1:8000/api/v1/blocks/1@1.0.0    # 精读模块（版本 pin；响应带 cr_id / commit_id 溯源）
curl -H "X-API-Key: $KEY" http://127.0.0.1:8000/api/v1/capabilities/1@1.2.0 # 小业务 manifest（pin 历史快照）
curl -H "X-API-Key: $KEY" "http://127.0.0.1:8000/api/v1/blocks/1/diff?from=1.0.0&to=1.1.0"
curl -X POST -H "X-API-Key: $EXEC" http://127.0.0.1:8000/api/v1/work/1/claim   # 领取，返回锁定版本的完整规格
curl -X POST -H "X-API-Key: $EXEC" -H "Content-Type: application/json" http://127.0.0.1:8000/api/v1/work/1/implementation -d '{"results":[{"ac_id":"AC-1","result":"pass","evidence":"测试输出……"}]}'
curl -X POST -H "X-API-Key: $QA" -H "Content-Type: application/json" http://127.0.0.1:8000/api/v1/work/1/verification -d '{"results":[{"ac_id":"AC-1","result":"pass","evidence":"独立验证……"}]}'
```

### 人批准：CLI

```bash
export SPECLOCK_URL=http://127.0.0.1:8000 SPECLOCK_KEY=<人类 key>
speclock-cli cr list --status pending_review
speclock-cli cr show 1
speclock-cli cr approve 1 [--hash <内容哈希前缀>] [--via natural_language --evidence "同意，按这个来"]
speclock-cli cr reject 1 --reason "验收条件没写清楚"          # 驳回必须写理由；rejected 是终态
speclock-cli key create --role executor-agent --label "后端执行 Agent"   # 兜底：人直接发 key（明文只显示一次）
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
        "SPECLOCK_KEY": "<该 agent 的 key——按它的角色分配，仅创建时可见一次>"
      }
    }
  }
}
```

MCP server 暴露 **27 个工具**，key 的角色决定哪些能用（没权限的返回 403；编码阶段的 admin key 全部可用）：

| 工具 | 权限 | 用途 |
|---|---|---|
| `whoami` | 任意 | 当前 key 的角色与权限 |
| `get_index` / `get_block` / `get_capability` / `get_diff` | `spec.read` | 读规格：索引树、模块（带版本级别标签与 cr_id / commit_id）、小业务 manifest、版本 diff |
| `get_block_history` / `get_capability_history` | `spec.read` | 版本历史（从旧到新）：级别标签、变更说明、delta、产生它的审核单 / Commit、状态（current / deprecated）；小业务历史带 manifest |
| `list_work` / `get_work` | `exec.read` | 待办队列（按状态筛选）/ 一条执行记录：事件历史、已提交结果、锁定到该版本的完整规格 |
| `claim_work` / `release_work` / `report_blocked` / `report_failed` / `submit_implementation` | `exec.write` | 执行 Agent：领取、放弃、报告业务阻塞 / 失败（必须写原因）、提交实现结果（逐条验收条件 pass + 证据，缺一条或有不通过都被拒） |
| `verify_work` | `exec.verify` | 测试 Agent 独立验收：逐条给结果，全通过 → verified，有不通过 → failed；验证者不能是实现者 |
| `create_api_key` | `key.manage` | **危险操作**，只有 admin 能做：必须先问人并等到明确同意，附人同意的原话 `evidence`；明文只返回一次，创建后立即可用 |
| `use_api_key` | 任意 | 在当前 MCP 会话里切换使用的 key（例如刚创建的那把），不用重启客户端；传空切回配置里的那把 |
| `list_change_requests` / `get_change_request` | `cr.read` | 读审核单（含状态、覆盖情况、人的决定与驳回理由） |
| `create_change_request` / `update_change_request` / `submit_change_request` / `withdraw_change_request` | `cr.write` | 整理审核单：草稿 → 提交（冻结）→ 需要改时撤回 |
| `submit_commit` / `complete_change_request` | `commit.write` | 在已批准的审核单下写规格库 / 报告完成 |
| `approve_change_request` / `reject_change_request` | `cr.approve` | Agent **代人**批准 / 驳回：必须带上人看过的那一版的 `content_hash` 与人的原话 `evidence`（驳回必须写理由），Core 把渠道记为 natural_language 并留原话；没有人的明确指示时不得调用 |

所有操作都由 Agent 经 MCP 完成；网页只做展示（参考实现，可不启动），也只调用公开 REST 接口，别人想自己做一个同样能接。

## 规则摘要

- **删除语义**：已发布内容不可消失。模块下线 = 通过 Commit 归档（`archive_block`：agent 读 404、索引排除、历史版本保留，并立即派生小业务新版本），可通过 `restore_block` 恢复；没有硬删除接口，只有删除整个项目会级联硬删（且要求其下没有已发布模块）
- **没有作废功能**：发布错了就再提一个审核单往前改（留痕完整，追溯链不断），不提供撤回已发布版本的入口；版本号永不复用
- **版本级别标签**：`diffing.bump_level` 对整份 delta 机械算出——API 或规则 / 验收条件有任何删除或修改 → MAJOR；只有新增 → MINOR；其余（只改背景、条目仅改名）→ PATCH。规则与验收条件是自然语言，机器分不清改措辞与改语义，按保守一侧归类。标签写入 `BlockVersion.level` 并随 `get_block` / `get_diff` 下发，只是参考；agent 读旧版本时响应带派生状态 `status`（`current` / `deprecated`）与 `superseded_by`。
- **升级到 0.5.0**：移除全部旧的直接写入口（建 / 改 / 删 / 发布模块与小业务、提案收件箱与批准）与 `applied_ops`；新增角色与权限、审核单、Commit、溯源字段、`speclock-cli`。老库在启动时由 `init_db` 自动补列 / 建表 / 补预置角色，没有角色的老 key 回填默认角色（human→admin，agent→executor-agent）；旧的 `proposals` 表不再使用也不删除。agent 端需升级 MCP wheel（工具集已变）。
- **术语与升级**：Business（大业务）/ Capability（小业务）/ Block（模块）；0.4.0 起原 Domain / Document 改名为 Business / Capability（接口 `/domains`→`/businesses`、`/documents`→`/capabilities`，MCP `get_document`→`get_capability`，不保留旧别名）。老库在启动时由 `init_db` 自动迁移（表与外键列改名、删除 `doc_type`、新增小业务 `summary`），幂等；agent 端需升级 MCP wheel。
- **执行状态机**：见 `executions.py`。验证者 ≠ 实现者按 key 判定；模块发布新版本时旧版本的未结束记录变 `superseded`，对它们的写操作一律 409 并指向最新版本；归档的模块不出现在待办里，恢复后回来；`verified` 与 `superseded` 是终态，`failed` / `blocked` 可重新领取（不限次数，旧结果清空、历史留在事件里）；不做领取超时。
- **升级到 0.6.0**：删除 `ack_block` / `Block.completed*` / `acks` 表（被执行记录取代）与版本作废（`spec.void` / `voided_at`）；新增执行记录、`exec.read` / `exec.write` / `exec.verify`、`tester-agent`、`create_api_key`。老库启动时自动删旧列旧表、给已发布模块补 pending 记录、给还没有 exec.* 权限的预置角色补上对应权限。
- **审计**：审核单流转（含批准渠道与原话）/ Commit / 发布（模块 + 小业务）/ 拉取 / 执行记录转换 / 密钥与角色变更全部写 `AuditLog`

## 项目结构

```
speclock/            # FastAPI 纯 JSON API
├── main.py        # 应用装配 + SPA 托管（web/dist 存在时）+ 按环境启动
├── settings.py    # speclock.toml 多环境配置加载（active / SPECLOCK_ENV）
├── api_cr.py      # 审核单 + Commit 接口：规格库唯一写入通道（状态机 / 批准 / 覆盖检查）
├── commits.py     # Commit 引擎：ops 原子应用、$ref、跨 Block / Capability、回滚
├── engine.py      # 发布引擎（内部）：草稿 → 不可变版本 + 小业务版本派生 + 结构完备性校验
├── permissions.py # 权限目录 / 预置角色 / require_permission 依赖
├── api_admin.py   # 管理与读视图：树 / 版本 / 归档 / 审计 / 项目 / 密钥 / 角色
├── api_agent.py   # 读规格（索引 / 小业务 / 模块 / diff）；不存在任何规格写端点
├── api_exec.py    # 执行接口：待办 / 领取 / 阻塞 / 失败 / 提交实现 / 独立验收
├── executions.py  # 执行记录状态机（机械：登记、转换、校验、留痕）
├── auth.py        # key 生成 / 哈希 / 脱敏 + 审计
├── cli.py         # speclock-cli：人用人类 key 查看 / 批准 / 驳回审核单，管理密钥
├── diffing.py     # 结构化 API/规则校验、字段级 delta、版本级别标签、OpenAPI 生成、两级 semver
├── mcp_server.py  # stdio MCP，27 工具，经 HTTP 调本系统 REST
└── seed.py        # demo 数据 + 打印两个开发 key
web/               # Vue 3 + Vite 只读展示网页（文档树 / 模块 / 版本 diff / 审核单 / 待办 / 归档 / AI 接入）；npm run build 产出 dist/，已 gitignore
tests/             # pytest：auth / 发布 / diff / 归档 / 执行记录 / 项目隔离 / 环境配置 / SPA 托管等
inject_ops.py      # 真实业务数据注入脚本（.inject_data/*.json → DB，先清空再注入，幂等）
```

## 开发

```bash
.venv/Scripts/python.exe -m pytest -v          # 跑测试
cd web && npm install && npm run dev           # 前端热更新开发（vite 代理 /api → 127.0.0.1:8000）
cd web && npm run build                        # 构建 SPA 到 web/dist/，后端启动后即整站可用
SPECLOCK_DB_URL=sqlite:///test.db .venv/Scripts/python.exe -m speclock.seed   # 用临时库 seed
.venv/Scripts/python.exe inject_ops.py         # 注入真实业务文档数据（清空后重建，幂等）
```

- 权限边界由「角色 → 权限集合 + 人类专属权限不可挂在 agent 类角色上」保证；规格库唯一写入通道是审核单 → Commit
- 数据库默认 `./speclock.db`（SQLite），可用 `SPECLOCK_DB_URL` 环境变量或 `speclock.toml` 覆盖

## License

[MIT](LICENSE)

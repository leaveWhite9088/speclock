# SpecLock — 开发指南

> 给**开发 SpecLock 本身**的人和 AI agent 读。使用者看 [README](../README.md)，接口和规则细节看 [REFERENCE](REFERENCE.md)，
> 给业务 Agent 的提示词在 [`roles/`](../roles/)。
>
> 本文件只描述**现在的样子**，不记历史。决策有变更时，先改本文件，再改代码；做完的事不留"已实施"标记，不做的事不留计划。

## 1. 产品边界

SpecLock 是**纯记录工具**：业务规格的单一信源，只管记录、保持版本和文档的准确。

- **Core 是确定性的，不含 LLM，不做任何判断**：保存业务事实、管理版本、控制权限、留痕。
- **不是 Agent，也不调度 Agent**：谁写、谁实现、谁测、谁扫描、谁转发消息、谁定时叫醒谁，都是外面的脚手架和 Agent 的事。
  Core 只提供被动的接口（REST、MCP），调度器靠轮询 `/activity`、`list_work` 等接口就够，Core 不推送。
- **行为约定只写在提示词里**（[`roles/`](../roles/)），Core 只强制权限和机械的一致性检查。
  凡是需要"判断"的事（改动算不算业务变更、规格写得好不好）都不在 Core 里。
- **只管业务**：后端重构、界面样式、代码组织变化而业务不变，不产生新版本。
- **本机个人使用**：服务只监听 127.0.0.1，不做公网部署，不考虑会话令牌和跨域加固。

## 2. 层级与术语

```
Project（项目）            隔离单元，key 可绑定到一个项目
 └── Business（大业务）     如：运营 / 采购 / 商品
      └── Capability（小业务）  如：经营日报；只做聚合与版本快照，自身不带 API / 规则
           └── Block（模块）     最小业务知识单元，可单独交给一个 Agent
```

- 中文固定叫法：**大业务 / 小业务 / 模块**。
- 模块内容：业务背景（`content_md`）+ 规则清单 + API 列表 + **验收条件**。API 属于模块。
- 小业务有可选的一句话 `summary`，随索引下发。

## 3. 规格与版本

- 规则和验收条件带**稳定 id**（`R-n` / `AC-n`）：服务端分配，编号取"草稿与全部历史快照已用最大编号 + 1"，不复用；
  改动按 id 匹配，不按名称。
- **模块有独立的两级语义化版本**，背景、规则、API、验收条件任何一处改动都产生新版本。
  **小业务版本** = 其全部模块当前版本的确定快照（manifest），任一模块发布即派生新的小业务版本。
- **级别标签由代码机械算出**（`diffing.bump_level`），仅供参考，不判断"意思变没变"：
  有任何删除或修改 → MAJOR；只有新增 → MINOR；其余（只改背景、API 文字说明、条目只改名）→ PATCH。
  所以改一个错别字也是 MAJOR。标签存在 `BlockVersion.level`，随 `get_block` / `get_diff` / 发布预览下发。
- 改名、改简述（标题 / `summary`）**不产生版本**；要查是谁改的看审核单或活动日志。
- `deprecated` 是**派生状态**，不存库：读到不是最新的版本时响应带 `status: deprecated` 与 `superseded_by`
  （永远指向当前最新版本）。`archived`（模块下线）和 `deprecated`（被取代）是两回事。
- **没有作废功能**：发布错了就再提审核单往前改。
- 整体替换列表时，没带 id 的条目是**新条目**、旧条目被删除（delta 里是 removed + added）；要改某一条用 `rule_ops` / `acceptance_ops` 或保留它的 id。

## 4. 变更链路：审核单 → Commit

规格库**只有一条写入通道**，没有任何直接建 / 改 / 发布模块的接口。

**审核单（Change Request）** 只含业务意图：`intent`（为什么变）、`expected_outcome`（变成什么样）、`obsolete`（不再成立的旧认知）、
`acceptance`（`{id, name, detail}`，`AC-n`）、`impact_note`（写给人看的影响说明）。不含改哪个模块、哪个 Agent、什么技术。

- **状态**：`draft → pending_review → approved → applied`；`pending_review → rejected`；`approved → superseded`。
- **提交即冻结**：`pending_review` 后内容只读，要改先撤回成 `draft`。批准时带内容哈希，批准的就是人看到的那一版。
- **批准后不可修改**：想改就新开一张取代旧的（`superseded`）。
- **驳回**是终态，必须写理由；Agent 读到后新开一张。
- **草稿归属**：只有开单的那把 key（或拥有 `key.manage` 的管理员）能改、提交、撤回，其他 key 一律 403。
- **请求体不认识的字段直接 422**（`StrictModel`），不静默忽略。

**Commit** 是 ops 的原子批次（按稳定 id 的 upsert / delete），写入必须带 `approved` 的审核单。
一个 Commit 可新建大业务 / 小业务 / 模块（用 `ref` 与 `"$名字"` 互相引用）、更新、归档 / 恢复、`move_block`，可跨多个模块和小业务；
任何一条 op 失败整体回滚，成功即发布。`dry_run` 完整执行后回滚，用于预览版本号、级别和 delta。

- **覆盖检查（机械）**：Commit 声明自己满足审核单的哪些 `AC-n`（`covers`）；审核单要 `complete`，全部验收条件必须被至少一个 Commit 覆盖。
  声明是否属实由后续验证环节负责，Core 不判断。
- **溯源**：每个 `BlockVersion` 记录 `cr_id` + `commit_id`，可从版本追溯到"哪个 Commit、哪个审核单、为什么改"，也可反查。
- `move_block {id, capability}`：把已发布模块搬到同项目的另一个小业务，身份、历史版本、执行记录不变，不产生新的模块版本；
  原小业务和新小业务各派生一个新的小业务版本。

**内部整理**：审核单有 `kind`——`business`（默认，须人批准）或 `internal`。
**由需求 Agent 自己声明**，选 `internal` 必须写 `kind_reason` 并需要 `cr.internal` 权限；提交即生效（`decision_via=agent_declared`），
不能取代其他审核单。Core **不比较内容**，只做三件机械的事：检查权限、要求写理由、留痕（网页标注"由 Agent 自行判定"）。
卡在 `approved` 且没有任何 Commit 落地的内部整理单，创建它的 key（或 admin）可以撤回。
"什么算业务变更"的规矩在 [`roles/requirements-agent.md`](../roles/requirements-agent.md)。

## 5. 角色、权限与密钥

- key 绑定**角色**，角色是**权限集合**；权限目录由代码定义（接口按权限放行），角色和映射可自定义。
- 角色有 `kind`（human / agent）。**人类专属权限**（`cr.approve`、`project.manage`、`key.manage`）不能挂在 agent 类角色上，
  所以受限角色的 Agent 批准不了审核单，也创建不了 key。
- 预置角色：`admin`（全部）、`reviewer`（读 + 批准 / 驳回）、`viewer`（只读，网页自动使用）、`requirements-agent`（读 + 整理审核单 + `cr.internal` + 提交 Commit）、
  `executor-agent`（读 + 领取 / 实现）、`tester-agent`（读 + 独立验收）、`scanner-agent`（只读）。预置角色可改权限、不可删。
- **批准的渠道**：出示人类 key 才能把审核单置为 `approved`，Core 不区分渠道，只记录渠道（`cli` / `natural_language` / `api`）和人的原话。
  实际用法有两种：人用 `speclock cr approve`；或人在对话里明确同意，持有 admin key 的 Agent 经 MCP 代为调用，
  **必须带 `content_hash`（批准哪一版）和 `evidence`（人的原话）**。后者的"人确认了"只是约定，靠提示词和留痕。
- **密钥**：`speclock init` 只发一把**随机**的 admin key，明文只打印一次，库里只存 SHA-256 哈希和脱敏 hint。
  其余 key 由 admin 创建（MCP `create_api_key`、REST、或 `speclock key create`）。创建 key 是**危险操作**，
  Agent 必须先问人、拿到明确同意，`evidence` 附原话（缺了 422，来源与原话写进审计）。网页不提供创建 key 的操作。
- **key 的存放（`keyfiles.py`）**：Agent 类 key 由服务端直接写成 `.speclock/keys/<角色>--<名称>.key`，创建响应里只有文件名、没有明文，
  所以明文不经过对话；人类 key（admin / reviewer）不存文件，只在创建时返回一次。吊销时文件一并删除。
  MCP 用 `--key-file` / `SPECLOCK_KEY_FILE` / `use_api_key(key_file=…)` 直接读文件。`keys/README.md` 告诉 Agent 只读自己的那个。
  同目录的 Agent 互相看得见文件，"只读自己的"是约定，Core 强制不了；把人类 key 排除在外，是为了让越界读取最多拿到低权限。
- 新建的 Agent key 立即可用；`use_api_key` 在会话内切换，不用重启客户端（无效的 key 保持原身份）。
- **身份靠提示词**：同一目录下多个 Agent 彼此看得见对方的文件，所以不靠 key 保密隔离角色；key 的作用是角色权限 + 项目隔离，
  Agent 的身份靠各目录 `AGENTS.md` 里的提示词（`roles/`）。
- **「验证者 ≠ 实现者」只是按 key 判定的机械规则**，同一个 Agent 有意切换 key 能绕过；真正的独立性靠不同的 Agent 实例和提示词约定。
- **网页不用登录，也不持有 admin key**：`init` / `serve` 时准备一把 `viewer` 角色的只读 key（明文在 `.speclock/web.key`，库里只存哈希，缺了启动时自动补），
  网页经 `GET /api/v1/web/session` 取用；该接口只对本机 Host、同源请求开放（挡 DNS 重绑定和跨站读取）。`viewer` 有 `key.read`（看密钥 / 角色 / 权限目录，不含明文），没有任何写权限。
- 审计只记 hint，不记明文。

## 6. 执行记录

规格状态与执行状态**分开**。Core 只做机械的事——登记、转换、校验、留痕。

- **每个已发布的模块版本自动一条执行记录**（发布后 `sync_block`）：`pending → in_progress → implemented → verified`；
  `in_progress` 可去 `blocked`（业务上卡住，写原因）/ `failed`（写原因），这两个状态可重新领取（不限次数，旧结果清空，历史留在事件里）；
  验收不通过也回到 `failed`。模块发布新版本时旧版本上未结束的记录变 `superseded`（写一律 409 并指向最新版本）。`verified` / `superseded` 是终态。
- **领取时拿到锁定版本的完整规格**；不做领取超时，卡住了用 `release_work` 放弃（领取者本人或管理员）。
- **实现结果逐条验收条件**：`submit_implementation` 必须对每条 AC 给 `pass` + 证据，缺一条、证据为空、有不通过都拒绝。
- **独立验收**：`verify_work` 需要 `exec.verify`，同样逐条给结果；验证者的 key 不能等于实现者的（403）。
  全通过 → `verified`，有不通过 → `failed` 且原因写进记录。
- **blocked 的解决**：Core 不路由。需求 Agent 在 `list_work(status=blocked)` 里看到，走正常审核单发布新版本，旧记录自动被取代。

## 7. 数据与运行

配置和数据在 `.speclock/`（`config.toml` + `speclock.db` + `.gitignore`），**永远不在源码目录里**。
查找顺序：`SPECLOCK_HOME` → 从当前目录往上找最近的 `.speclock/` → `~/.speclock/`（见 `home.py`）。
`speclock init` 在当前目录建（端口自动选空闲的），`speclock init --global` 在 `~/.speclock/` 建（端口 `47821`）。
`SPECLOCK_DB_URL` 可直接指定数据库（测试用），`SPECLOCK_URL` / `SPECLOCK_KEY` 给 MCP 和 CLI 用。

库结构变更在 `db.py` 写幂等迁移（`_ensure_columns` 等）；预置角色的权限变更用一次性迁移标记（`MigrationMark`），不覆盖管理员改过的角色。

## 8. 开发约定

- 改动同步：测试、REFERENCE / README、`roles/`（如果影响 Agent 的用法）。
- 版本号的源头是 `speclock/__version__`（pyproject 和 FastAPI 都读它）；对外接口有变化时升它，同时改 `web/src/App.vue` 的版本标签和 `web/package.json`，并在 [CHANGELOG](CHANGELOG.md) 记一条。
- 环境：Python 虚拟环境在 `.venv/`，前端在 `web/`。

```bash
.venv/Scripts/python.exe -m pytest -q          # 后端测试
cd web && npm test                             # 前端单元测试（vitest）
cd web && npm run dev                          # 前端热更新（代理 /api 到 SPECLOCK_URL，默认 47821）
speclock init && speclock serve                # 在一个测试目录里跑起来
```

**发布网页**：`web/dist/` 平时被 gitignore。只在发布版本时构建并提交，让使用者克隆下来不装 Node 也有网页：

```bash
cd web && npm install && npm run build
git add -f web/dist        # 发布提交里带上；日常开发提交不带
```

## 9. 代码地图

后端 `speclock/`：

- `api_cr.py`：审核单 + Commit 接口，规格库唯一写入通道（状态机、批准、覆盖检查）。
- `commits.py`：Commit 引擎（ops 原子应用、`$ref`、跨模块 / 小业务、整体回滚）。
- `engine.py`：发布引擎（内部，无对外写接口）：草稿 → 不可变版本、小业务版本派生、结构完备性校验。
- `diffing.py`：结构化 API / 规则校验、字段级 delta、级别标签、OpenAPI 生成、版本号计算。
- `api_agent.py`：读规格（索引 / 小业务 / 模块 / diff / 历史），没有任何写端点。
- `api_exec.py` + `executions.py`：执行接口与执行记录状态机。
- `api_admin.py`：读视图（树 / 版本 / 归档 / 审计 / 活动）+ 项目 / 密钥 / 角色管理。
- `api_search.py`：搜索（已发布模块的当前版本 + 审核单，子串匹配，项目隔离）。
- `keyfiles.py`：Agent key 文件的读写与 `keys/README.md`。
- `permissions.py`：权限目录、预置角色、`require_permission`、一次性迁移。
- `webkey.py` + `api_web.py`：网页用的只读 key 的准备与自动发放。
- `home.py` + `settings.py`：`.speclock/` 的查找、`config.toml`、`init_home`。
- `cli.py`：统一命令 `speclock`：`init` / `serve` / `mcp`，以及 `cr`、`key`。
- `mcp_server.py`：stdio MCP，29 个工具，经 HTTP 调用本系统 REST。
- `models.py`、`schemas.py`（请求体全部 `StrictModel`）、`db.py`（含迁移）、`auth.py`（key 哈希 + 审计）、`main.py`（应用装配 + 托管 `web/dist`）。

前端 `web/`：Vue 3 **只读展示**网页，是人监控整个工具的**唯一通道**，不用登录（key 只存在内存里）。**不提供任何修改操作**，新增页面也不要加；
只调用公开 REST 接口，不依赖 Core 内部实现。页面：总览、文档树、模块 / 版本 / diff / 追溯、审核单、待办、活动、Agent 与密钥、搜索、归档、AI 接入。
结构：`api/`（客户端 + `resources.js`）、`composables/`（取数、轮询、自动刷新）、`components/`（纯展示）、`views/`（薄页面）、`labels.js` / `errors.js`；
整理逻辑是纯函数并有测试。

`roles/`：推荐的角色提示词（`common.md` + 需求 / 执行 / 测试 / 扫描）。`tests/`：pytest。

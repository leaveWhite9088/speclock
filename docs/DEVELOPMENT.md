# SpecLock — 开发指南

> 给**开发 SpecLock 本身**的人和 AI agent 读。使用者看 [README](../README.md) 和 [使用指南](GUIDE.md)，接口和规则细节看 [REFERENCE](REFERENCE.md)，
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

- **只补覆盖的 Commit**：`ops` 可以为空，但必须写 `covers` 和 `change_note`；用于事后补上漏写的覆盖声明，不改规格。
- **覆盖检查（机械）**：Commit 声明自己满足审核单的哪些 `AC-n`（`covers`）；审核单要 `complete`，全部验收条件必须被至少一个 Commit 覆盖。
  声明是否属实由后续验证环节负责，Core 不判断。
- **溯源**：每个 `BlockVersion` 记录 `cr_id` + `commit_id`，可从版本追溯到"哪个 Commit、哪个审核单、为什么改"，也可反查。
- `move_block {id, capability}`：把已发布模块搬到同项目的另一个小业务，身份、历史版本、执行记录不变，不产生新的模块版本；
  原小业务和新小业务各派生一个新的小业务版本。

**内部整理**：审核单有 `kind`——`business`（默认，须人批准）或 `internal`。
**由需求 Agent 自己声明**，选 `internal` 必须写 `kind_reason` 并需要 `cr.internal` 权限；提交即生效（`decision_via=agent_declared`），
不能取代其他审核单。Core **不比较内容**，只做三件机械的事：检查权限、要求写理由、留痕（网页标注"由 Agent 自行判定"）。
卡在 `approved` 且没有任何 Commit 落地的内部整理单，创建它的 key（或 admin）可以撤回。
边界划在 SpecLock 管辖的内容上：**改了模块的背景、规则、验收条件或 API 里的任何一个字，都是业务变更**；
内部整理只有两类——改名（业务 / 小业务 / 模块的标题与简述）和 `move_block`，共同点是不产生新的模块版本（机械可核对：`dry_run` 的 `blocks`、`archived_blocks`、`restored_blocks` 都为空）。
具体规矩在 [`roles/requirements-agent.md`](../roles/requirements-agent.md)。

## 5. 角色、权限与密钥

- key 绑定**角色**，角色是**权限集合**；权限目录由代码定义（接口按权限放行），角色和映射可自定义。
- 角色有 `kind`（human / agent）。**人类专属权限**（`cr.approve`、`project.manage`、`key.manage`）不能挂在 agent 类角色上，
  所以受限角色的 Agent 批准不了审核单，也创建不了 key。
- 预置角色：`admin`（**超级管理员**，全部权限，唯一可以是全局 key 的角色）、`project-admin`（**项目管理员 / 项目主管**：批准本项目的审核单、管理本项目的 key；key 必须绑定项目，不能建项目、改角色、建超级管理员）、`reviewer`（读 + 批准 / 驳回）、`viewer`（只读，网页自动使用）、`requirements-agent`（读 + 整理审核单 + `cr.internal` + 提交 Commit）、
  `executor-agent`（读 + 领取 / 实现）、`tester-agent`（读 + 独立验收）、`scanner-agent`（只读）。预置角色可改权限、不可删。
- **项目范围由 key 决定，不靠调用参数**：Agent 类角色和 `project-admin` 的 key 创建时必须绑定项目（否则 422 `project_required`），只有 `admin` 可以是全局的；
  项目管理员（有 `key.manage` 但没有 `project.manage`）只能在自己的项目里建 / 看 / 删 key，建不出带人类专属权限的角色，角色增删改和项目管理都要超级管理员（403 `super_admin_required`）。
  「最后一把管理员」指超级管理员（`key.manage` + `project.manage`）。升级前就存在的全局 Agent key 不受影响，但新建不出来了。
- **批准的渠道**：出示人类 key 才能把审核单置为 `approved`，Core 不区分渠道，只记录渠道（`cli` / `natural_language` / `api`）和人的原话。
  实际用法有两种：人用 `speclock cr approve`；或人在对话里明确同意，持有 admin key 的 Agent 经 MCP 代为调用，
  **必须带 `content_hash`（批准哪一版）和 `evidence`（人的原话）**。后者的"人确认了"只是约定，靠提示词和留痕。
- **密钥**：`speclock init` 只发一把**随机**的 admin key，明文只打印一次，库里只存 SHA-256 哈希和脱敏 hint。
  其余 key 由 admin 创建（MCP `create_api_key`、REST、或 `speclock key create`）。创建 key 是**危险操作**，
  Agent 必须先问人、拿到明确同意，`evidence` 附原话（缺了 422，来源与原话写进审计）。网页不提供创建 key 的操作。
- **key 的存放（`speclock_config.keyfiles`）**：Agent 类 key 由服务端直接写成 `.speclock/keys/<角色>--<名称>.key`，创建响应里只有文件名、没有明文，
  所以明文不经过对话；人类 key（admin / reviewer）不存文件，只在创建时返回一次。吊销时文件一并删除。
  MCP 用 `--key-file` / `SPECLOCK_KEY_FILE` / `use_api_key(key_file=…)` 直接读文件。`keys/README.md` 告诉 Agent 只读自己的那个。
  同目录的 Agent 互相看得见文件，"只读自己的"是约定，Core 强制不了；把人类 key 排除在外，是为了让越界读取最多拿到低权限。
- **admin key 不进 Agent 读得到的文件**：`init` 只打印一次，不再生成含 admin key 的 `.mcp.json` 片段；人用的 CLI 没有 key 时在终端里提示输入（`getpass`）；
  创建 Agent key 时返回现成的 `mcp_config`（`speclock_config.mcp_config`：key 文件名 + 写死的 `SPECLOCK_HOME` + Python 绝对路径），所以 MCP 不依赖启动时的工作目录，两种用法一致。
- **身份不能被环境悄悄顶替**：MCP 里 key 文件优先于 `SPECLOCK_KEY`；`whoami` 带 `key_source`；`use_api_key(key_file=)` 是严格模式，只认 `keys/` 里的文件名（`keyfiles.read_key(strict=True)`）；工具参数多余时报错（与 REST 的 `StrictModel` 一致）。
- 新建的 Agent key 立即可用；`use_api_key` 在会话内切换，不用重启客户端（无效的 key 保持原身份）。
- **身份靠提示词**：同一目录下多个 Agent 彼此看得见对方的文件，所以不靠 key 保密隔离角色；key 的作用是角色权限 + 项目隔离，
  Agent 的身份靠各目录 `AGENTS.md` 里的提示词（`roles/`）。
- **「验证者 ≠ 实现者」只是按 key 判定的机械规则**，同一个 Agent 有意切换 key 能绕过；真正的独立性靠不同的 Agent 实例和提示词约定。
- **网页不用登录，也不持有 admin key**：`init` / `serve` 时准备一把 `viewer` 角色的只读 key（明文在 `.speclock/web.key`，库里只存哈希，缺了启动时自动补），
  网页经 `GET /api/v1/web/session` 取用；该接口只对本机 Host、同源请求开放（挡 DNS 重绑定和跨站读取）。`viewer` 有 `key.read`（看密钥 / 角色 / 权限目录，不含明文），没有任何写权限。
- 审计只记 hint，不记明文。

## 6. 执行记录

规格状态与执行状态**分开**。Core 只做机械的事——登记、转换、校验、留痕。

- **每个已发布的模块版本自动一条执行记录**（发布 / 恢复时由 `events` 通知 `executions.sync_block`，发布引擎不认识执行记录）：`pending → in_progress → implemented → verified`；
  `in_progress` 可去 `blocked`（业务上卡住，写原因）/ `failed`（写原因），这两个状态可重新领取（不限次数，旧结果清空，历史留在事件里）；
  验收不通过也回到 `failed`。模块发布新版本时旧版本上未结束的记录变 `superseded`（写一律 409 并指向最新版本）。`verified` / `superseded` 是终态。
- **领取时拿到锁定版本的完整规格**；不做领取超时，卡住了用 `release_work` 放弃（领取者本人或管理员）。
- **实现结果逐条验收条件**：`submit_implementation` 必须对每条 AC 给 `pass` + 证据，缺一条、证据为空、有不通过都拒绝。
- **独立验收**：`verify_work` 需要 `exec.verify`，同样逐条给结果；验证者的 key 不能等于实现者的（403）。
  全通过 → `verified`，有不通过 → `failed` 且原因写进记录。
- **blocked 的解决**：Core 不路由。需求 Agent 在 `list_work(status=blocked)` 里看到，走正常审核单发布新版本，旧记录自动被取代。

## 7. 数据与运行

配置和数据在 `.speclock/`（`config.toml` + `speclock.db` + `.gitignore`），**永远不在源码目录里**。
查找顺序：`SPECLOCK_HOME` → 从当前目录往上找最近的 `.speclock/` → `~/.speclock/`（见 `speclock_config.home`）。
`speclock init` 在当前目录建（端口自动选空闲的），`speclock init --global` 在 `~/.speclock/` 建（端口 `47821`）。
`SPECLOCK_DB_URL` 可直接指定数据库（测试用），`SPECLOCK_URL` / `SPECLOCK_KEY` 给 MCP 和 CLI 用。

库结构变更在 `speclock_core/migrations.py` 写幂等迁移（`_ensure_columns` 等）；预置角色的权限变更用一次性迁移标记（`MigrationMark`），不覆盖管理员改过的角色。

## 8. 仓库结构与分层

monorepo：Python 后端拆成按层依赖的多个包（`packages/`），前端是 `apps/web`，用 uv 工作区一次装全。

```
packages/
├── config/   speclock_config   .speclock/ 的查找、config.toml、key 文件、web.key 文件。不依赖任何 speclock 包
├── core/     speclock_core     模型、版本 / diff、发布引擎、Commit、执行记录、权限目录、引导（init_db / init_home）
├── server/   speclock_server   FastAPI 路由与应用装配、网页托管。依赖 config、core
├── mcp/      speclock_mcp      MCP server，只经 HTTP 调 REST，不碰数据库。依赖 config
├── cli/      speclock_cli      命令行与导出 / 备份。依赖 config、core、server、mcp
└── speclock/ speclock          总装包：只声明依赖，提供 `python -m speclock`
apps/web/                       Vue 3 只读展示网页
```

**规则**（`tests/test_architecture.py` 强制，违反会让测试失败）：

1. **只能依赖下层**：config < core < server / mcp < cli < speclock，server 与 mcp 互不依赖。
2. **跨包只走 index**：`from speclock_core import X`，X 必须在对方 `__init__.py` 的 `__all__` 里；不能 `from speclock_core.engine import ...`。
   要给别的包用的东西，先加进 `__all__`——index 就是这一层的公开接口。
3. **包内也分层**（核心：`db/events/diffing/schemas` < `models` < `auth/migrations/permissions` < `engine/executions` < `commits` < `bootstrap`），只能依赖更低的层。
4. **pyproject 里的 speclock-* 依赖要和代码里真实的导入一致**；各包版本号一致。
5. **例外**要在 `DEEP_IMPORT_EXCEPTIONS` 里登记并写理由；`tests/` 不受这些规则限制。

几个关键的解耦点：

- **发布与执行记录**：`engine` / `commits` 只 `events.emit(...)`，`executions` 订阅 `block.published` / `block.restored` 去同步执行记录；谁都不反向依赖谁。订阅发生在 `executions` 被导入时，所以 `speclock_core/__init__.py` 必须导入它。
- **建库与种子数据**：`db` 只管引擎 / 会话，`migrations.create_schema` 管表结构，`bootstrap.init_db` 再补预置角色和执行记录；下层不反向调用上层。
- **配置与引导**：`speclock_config` 只读写文件；需要数据库的初始化（`init_home`、`ensure_web_key`）在 `speclock_core.bootstrap`。
- **路由共用的逻辑**（项目隔离 `scope.py`、响应序列化 `serializers.py`、鉴权依赖 `deps.py`）是 server 里的独立模块，路由之间不互相 import 私有函数。

## 9. 开发约定

- 改动同步：测试、GUIDE / REFERENCE / README、`roles/`（如果影响 Agent 的用法）。
- 临时的、一次性的测试（联调报告回归、按「第几轮修复」命名的测试）用完就删，不留；测试按功能命名、放进对应的文件。
- 版本号的源头是 `speclock_config.__version__`；各包 `pyproject.toml` 的 `version` 与它保持一致（测试检查）。对外接口有变化时一起升，
  同时改 `apps/web/package.json`（网页显示的版本号读它），并在 [CHANGELOG](CHANGELOG.md) 记一条。向后兼容的增量升 `0.2.x` 的末位。
- 环境：`uv sync` 在 `.venv/` 里装好全部包（editable）和 pytest；前端在 `apps/web`。

```bash
uv sync                                        # 装全部包（editable）+ 开发依赖
uv run pytest -q                               # 后端测试（含架构规则）
cd apps/web && npm test                        # 前端单元测试（vitest）
uv run python tests/e2e_real_flow.py           # 端到端（跟项目走）：真的 init + serve，用 MCP 工具走完整个业务流程
uv run python tests/e2e_real_flow.py --global  # 同上（跟电脑走）
cd apps/web && npm run dev                     # 前端热更新（代理 /api 到 SPECLOCK_URL，默认 47821）
uv run speclock init && uv run speclock serve  # 在一个测试目录里跑起来
```

### 对外接口的稳定性约定

外部系统（脚手架、调度器）只经 REST（`/api/v1`）和 MCP 集成，不碰 Core 代码，所以**接口的形状就是契约**：

- **响应形状有声明，有测试盯着**：每个接口都写 `response_model=…`，模型集中在 `speclock_server/responses.py`
  （规格读视图的模型在 `speclock_core/schemas.py`）。`docs/openapi.json` 是整份 OpenAPI 的快照，
  `tests/test_openapi_contract.py` 逐字比对；另一个测试要求每个 `/api/` 接口都声明了 JSON 响应，**新增接口不声明就过不了**。
- **改了响应形状要更新快照并记 CHANGELOG**：`UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_openapi_contract.py`，
  把 `docs/openapi.json` 的变化和代码一起提交，CHANGELOG 里写清楚改了什么。
  **只增不改**：新增接口、新增可选字段、新增查询参数是向后兼容的增量；改字段名 / 类型、删字段、把可选改必填、改状态码或权限都不是，要避免，不得不改就明说。
- **响应模型的写法**：字段默认必填（`X | None` 表示值可以是 null，键仍在）；`extra="forbid"`，处理函数多返回没声明的字段会在测试里暴露；
  只有确实"有时没有这个键"的才给默认值并在路由上加 `response_model_exclude_unset=True`（目前只有创建密钥）。
  有几种形状的接口用 `A | B` 并让各自的字段保持必填（`/diff`、提交 Commit、搜索命中）。
- **错误都带稳定的 `code`**：错误响应是 `{"detail": …, "code": …}`，`detail` 给人看（措辞可以改），`code` 给程序判断。
  要区分的情形在 `speclock_core/errors.py` 登记并用 `ApiError("code", detail)` 抛出（状态码以登记表为准）；
  其余的由状态码给通用 code（404 `not_found`、403 `permission_denied`、422 `validation_failed`……）。
  新增、改名、删除 code 都是对外接口变化，要记 CHANGELOG；`tests/test_error_codes.py` 核对登记表和代码里实际使用的一致。
- **新增接口的检查单**：声明响应模型 → 声明/复用错误码 → 更新 `docs/openapi.json` → 补测试 → CHANGELOG →（有意义的话）REFERENCE。
- **MCP 工具的名字和参数不能随意变**：它们是 Agent 的契约；要加参数只能加可选的。
  `docs/mcp_tools.json` 是 MCP 工具的快照（名字、参数、调用的 REST 接口、返回结构），`tests/test_mcp_contract.py` 比对；
  有意改了就 `UPDATE_MCP_SNAPSHOT=1 uv run pytest tests/test_mcp_contract.py` 并记 CHANGELOG。新增工具会让它失败，直到快照更新。
  工具返回是 `{"status", "body"}` 文本，`body` 是 REST 响应——所以**工具的返回结构由对应接口的 response_model 决定**，
  工具里对 body 再加工（如 `whoami` 加 `key_source`）要写进测试里的 `RETURN_NOTES`。
- **健康检查**：`GET /api/v1/health`（不需要 key，只对本机开放）；轮询活动日志用 `GET /api/v1/activity?after_id=`。

**发布网页**：`apps/web/dist/` 平时被 gitignore。只在发布版本时构建并提交，让使用者克隆下来不装 Node 也有网页：

```bash
cd apps/web && npm install && npm run build
git add -f apps/web/dist   # 发布提交里带上；日常开发提交不带
```

服务默认从仓库的 `apps/web/dist` 托管网页；部署到别处时用环境变量 `SPECLOCK_WEB_DIST` 指向构建产物。

## 10. 代码地图

`packages/config/src/speclock_config/`：`home.py`（`.speclock/` 查找、`config.toml`、`mcp_config`）、`keyfiles.py`（Agent key 文件与 `keys/README.md`）、`webkey.py`（`web.key` 文件）。

`packages/core/src/speclock_core/`：

- `models.py`、`schemas.py`（请求体全部 `StrictModel`）、`db.py`（引擎 / 会话）、`migrations.py`（幂等迁移 + 建表）、`auth.py`（key 哈希 + 审计）。
- `engine.py`：发布引擎（内部，无对外写接口）：草稿 → 不可变版本、小业务版本派生、结构完备性校验。
- `commits.py`：Commit 引擎（ops 原子应用、`$ref`、跨模块 / 小业务、整体回滚）。
- `diffing.py`：结构化 API / 规则校验、字段级 delta、级别标签、OpenAPI 生成、版本号计算。
- `executions.py`：执行记录状态机；`events.py`：发布 / 恢复事件。
- `permissions.py`：权限目录、预置角色、一次性迁移。
- `errors.py`：错误码登记表与 `ApiError`（对外接口的稳定错误类型）。
- `bootstrap.py`：`init_db`、`init_home`、`ensure_web_key`。

`packages/server/src/speclock_server/`：

- `api_cr.py`：审核单 + Commit 接口，规格库唯一写入通道（状态机、批准、覆盖检查）。
- `api_agent.py`：读规格（索引 / 小业务 / 模块 / diff / 历史），没有任何写端点。
- `api_exec.py`：执行接口。
- `api_admin.py`：读视图（树 / 版本 / 归档 / 审计 / 活动）+ 项目 / 密钥 / 角色管理。
- `api_search.py`：搜索（已发布模块的当前版本 + 审核单，子串匹配，项目隔离）。
- `api_web.py`：网页用的只读 key 的自动发放。
- `api_meta.py`：`GET /api/v1/health`（服务状态与版本，不需要 key，只对本机开放）。
- `responses.py`：全部响应模型（接口形状的声明），`ERROR_RESPONSES` 把统一的错误结构挂到各路由上。
- `deps.py`（按权限放行的依赖、仅限本机的检查）、`scope.py`（项目隔离）、`serializers.py`（共用的响应转换）。
- `static/embed.js`：给外层页面引用的嵌入脚本（`GET /embed.js`，不依赖网页构建）；`main.py` 装配应用、给所有响应加 `frame-ancestors`
  （来源由 `config.toml` 的 `embed_origins` 决定，默认只有本机）、托管网页；没有构建网页时 `/` 返回构建提示页。

`packages/mcp/src/speclock_mcp/server.py`：stdio MCP，33 个工具，经 HTTP 调用本系统 REST。工具返回是文本包着的 JSON（`{"status", "body"}`），body 与 REST 响应一致（错误也带 `code`）。

`packages/cli/src/speclock_cli/`：`cli.py`（统一命令 `speclock`：`init` / `serve` / `mcp`，以及 `cr`、`key`）、`exporter.py`
（完整备份 / 恢复（SQLite 在线备份）与文本导出（稳定、无时间戳、可进 git），`backup` / `restore` / `export` 直接调它，不走 HTTP）。

前端 `apps/web/`：Vue 3 **只读展示**网页，是人监控整个工具的**唯一通道**，不用登录（key 只存在内存里）。**不提供任何修改操作**，新增页面也不要加；
只调用公开 REST 接口，不依赖 Core 内部实现。页面：总览、文档树、模块 / 版本 / diff / 追溯、审核单、待办、活动、Agent 与密钥、搜索、归档、AI 接入。
嵌入模式（`?embed=1`，`src/embed.js`）：只显示内容、站内跳转保持参数、用 `postMessage` 报告路径与高度并接受外层的跳转指令，用法见 [EMBED.md](EMBED.md)。
结构：`api/`（客户端 + `resources.js`）、`composables/`（取数、轮询、自动刷新）、`components/`（纯展示）、`views/`（薄页面）、`labels.js` / `errors.js`；
整理逻辑是纯函数并有测试。

`roles/`：推荐的角色提示词（`common.md` + 需求 / 执行 / 测试 / 扫描）。`tests/`：pytest（跨包的集成测试 + `test_architecture.py`）。

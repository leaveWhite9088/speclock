# 版本记录

版本号的源头是 `speclock_config.__version__`（各包 pyproject 的版本与它一致）。

## 0.2.7 — 对外接口成为可机器检查的契约；monorepo 与分层

**对外接口（纯增量：路径、方法、字段、状态码、权限、MCP 工具都没变；改动前后用 1700 多次真实请求逐条比对过响应）**

- **响应都有声明**：全部 47 个 REST 操作声明了响应模型（`speclock_server/responses.py`），接口文档里能看到返回结构；
  服务端按它校验后再返回，字段缺了会直接报错而不是悄悄交出错的形状。
- **OpenAPI 契约快照**：`docs/openapi.json` 是整份接口的快照，`tests/test_openapi_contract.py` 逐字比对；
  形状变了测试失败，并提示用 `UPDATE_OPENAPI_SNAPSHOT=1` 有意更新。外部集成方可以拿它生成客户端或检查"接口没变"。
- **`GET /api/v1/health`**：不需要 key，只对本机地址开放（否则 403 `local_only`）；返回 `{"status":"ok","version":…}`，数据库读不动时 503 + `status: error`。
- **错误带稳定的 `code`**：所有错误响应是 `{"detail": …, "code": …}`，`detail` 原样不变，`code` 集中登记在 `speclock_core/errors.py`：
  通用的（`unauthenticated` / `permission_denied` / `not_found` / `bad_request` / `method_not_allowed` / `conflict` / `validation_failed`）
  和需要区分的（`cr_state_conflict` / `cr_content_changed` / `cr_supersede_invalid` / `cr_no_commits` / `cr_coverage_incomplete` / `cr_not_owner` /
  `work_superseded` / `work_state_conflict` / `work_already_claimed` / `work_not_holder` / `work_verifier_is_implementer` / `block_archived` / `local_only`）。
  MCP 工具返回的错误体里也随之多了 `code`。
- **`GET /api/v1/activity?after_id=`**：只取 id 大于它的事件，排序仍是新的在前；可与 `before_id` 组合补齐中间缺的一段。MCP 的 `get_activity` 同样多了可选参数 `after_id`（只加可选参数，原有工具名、参数、返回都没变）。
- **MCP 工具契约快照**：`docs/mcp_tools.json` 记录每个 MCP 工具的名字、参数、调用的 REST 接口和返回结构，`tests/test_mcp_contract.py` 逐字比对（`UPDATE_MCP_SNAPSHOT=1` 有意更新）。
  工具返回仍是文本 JSON `{"status", "body"}`，`body` 就是对应 REST 接口的响应，所以返回结构直接引用 OpenAPI 里的响应模型；
  和"原样包一层"不一样的三处（`whoami` 多 `key_source`、`use_api_key`、`create/update_change_request` 的 kind 校验错误）在快照里单独标注。工具的描述文字不在快照里。

**项目管理员看得到本项目的动态；除超级管理员外所有 key 都绑项目（会改变行为）**

- **项目管理员（`project-admin`）有 `audit.read`**：能看本项目的全部动态——卡点（blocked）、失败（failed）、待审批（pending_review）、活动日志（待办和审核单本来就能读）。活动日志已按项目隔离，所以只限本项目。
- **key 的创建和吊销只有超级管理员做**：项目管理员不再有 `key.manage`（仍能读本项目的 key 列表）；超级管理员可以给任何项目一次建出整套 key，也能删。
- **除超级管理员 `admin` 外，所有角色的 key 创建时都必须绑定项目**：`reviewer`、`viewer`、自定义角色也一样（422 `project_required`；规则是「没有 `project.manage` 的角色必须绑」）。升级前遗留的没绑项目的 key 不受影响。


**网页只看一个项目；删除模块 / 小业务 / 大业务 / 项目（会改变行为）**

- **网页按项目隔离**：网页不再用一把能看全库的只读 key，而是每个项目一把**绑定该项目**的 `viewer` key（`.speclock/web-keys/<项目 id>.key`），所以别的项目的结构、审核单、待办、搜索、活动、密钥它都拿不到。地址带 `?project=<id>` 指明看哪个；库里只有一个项目时自动选；多个又没指明时先显示项目选择页（嵌入模式必须由外层指明：`data-project` / `project:` 选项）。
  `GET /api/v1/web/session` 多了查询参数 `project_id`，返回里多了 `project_id`；新增 `GET /api/v1/web/projects`（项目选择页用，只有 id 和名称）；多项目又没指明时 422 `web_project_required`。旧版全局的 `web.key` 和它的库记录在启动时清掉。
- **活动日志按项目隔离**：审计记录新增 `project_id`（升级时按对象尽力回填），项目绑定的 key 读 `/api/v1/activity` 只看得到本项目的；推不出项目的记录只有全局 key 看得到。
- **删除**：新增 REST `DELETE /api/v1/blocks/{id}` / `capabilities/{id}` / `businesses/{id}`，MCP 工具 `delete_block` / `delete_capability` / `delete_business` / `delete_project`（共 37 个工具），都是**不可恢复**的危险操作：须附人同意的原话 `evidence`（写进审计）；已发布的模块要先通过审核单归档（409 `published_blocks_exist`）。
  新增人类专属权限 `spec.delete`（admin、project-admin 有；项目管理员只能删本项目的）；删项目仍是 `project.manage`（只有超级管理员）。`DELETE /api/v1/projects/{id}` 多了可选的 `via` / `evidence` 查询参数。新增错误码 `published_blocks_exist`、`web_project_required`。
- 附带：上一版 CHANGELOG 里写的「超级管理员与项目管理员」同步到了参考手册（上一版漏了这部分文档）。

**项目隔离收紧（会改变行为）**

- **超级管理员与项目管理员**：`admin` 是超级管理员（全局）；新增预置角色 `project-admin`（项目管理员 / 项目主管）：批准本项目的审核单、管理本项目的 key，不能建项目、改角色、建超级管理员。
- **Agent key 和项目管理员 key 创建时必须绑定项目**：`POST /api/v1/keys` 对 agent 类角色和 `project-admin` 不带 `project_id` 返回 422 `project_required`；只有 `admin` 可以是全局的。
  升级前就存在的全局 Agent key 照常工作，但新建不出来了。`speclock key create` 对应加了 `--project` 的说明。
- **项目管理员只管本项目**：建 key 时 `project_id` 默认并只能是自己的项目，只看得到 / 删得掉本项目的 key；角色增删改要超级管理员（403 `super_admin_required`）；「最后一把管理员」改为指最后一把超级管理员。
- 新增错误码 `project_required`、`super_admin_required`。MCP `create_api_key` / `create_change_request` 的描述写明了 `project_id` 的规则（工具签名没变）。

接口形状方面没有改动的：所有路径、方法、字段名、状态码、权限、MCP 工具名、参数和返回文本（上面「项目隔离收紧」是行为上的唯一例外：为 Agent / 项目管理员建 key 不带 `project_id` 现在会被拒绝）。没做的：`GET /embed.js`、`/docs`、`/openapi.json` 和网页托管不在契约内。

**monorepo 与分层**

- **仓库改成 monorepo**：后端拆成 `speclock-config` / `core` / `server` / `mcp` / `cli` 五个包加一个总装包 `speclock`（`packages/`），前端移到 `apps/web`；`uv sync` 一次装全，命令和 MCP 配置不变。
- **层间只能向下依赖，跨包只走 index**（`__all__`），由 `tests/test_architecture.py` 强制；包内核心模块同样分层。
- 路由之间不再互相 import 私有函数：项目隔离、响应序列化、鉴权依赖各有独立模块（`scope` / `serializers` / `deps`）。
- `home` / `webkey` / `settings` 理顺：配置与文件在 `speclock_config`，需要数据库的初始化在 `speclock_core.bootstrap`；`db` 不再反向依赖权限和执行记录。
- 发布与执行记录解耦：发布引擎发 `block.published` / `block.restored` 事件，执行记录订阅，不再互相 import。
- 网页构建产物默认从 `apps/web/dist` 托管，部署到别处可用 `SPECLOCK_WEB_DIST` 指定。
- 删除按「联调报告第几轮」命名的一次性回归测试。

## 0.2.6 — 联调 v3 修复

- **MCP 身份不再被环境变量顶替**：配了 `--key-file` 就以文件为准（之前 `SPECLOCK_KEY` 会静默覆盖，人为跑 CLI 设的 admin key 让需求 Agent 变成了管理员）；
  `whoami` 返回 `key_source`；启动时在 stderr 打印服务、数据目录和身份来源。
- **`use_api_key(key_file=…)` 只认 `keys/` 里的文件名**，`../web.key` 之类的路径一律拒绝（之前能借此读到别处的 key 文件）。
- **启动时说明数据目录**：`serve` / `mcp` 打印用的是哪个 `.speclock/`、怎么找到的，用了上层目录会提醒；在嵌套目录里 `init` 会提示上层已有一份。
- **`init --new-admin`**：说明旧 key 仍有效，新增 `--revoke-old` 一并吊销；不再重复"下一步"。
- **只补覆盖的 Commit**：`ops: []` + `covers` + `change_note`，不用为补覆盖随便改个字段。
- **网页不再说"系统检查了内部整理"**：系统不检查内容。内部整理单的详情页会指出落地后升了级（大改 / 小改）的模块，提醒人看一眼。
- MCP 工具参数拼错会报错；绑定项目的 key 在别的项目开单给出明确提示；请求体编码错误提示 UTF-8；CLI 删除 key 的审计来源记为 `cli`。
- **内部整理的边界划清**：只有改名（标题与简述）和 `move_block`；改了模块的背景、规则、验收条件或 API 的任何一个字（含错别字）、以及新建 / 拆分 / 合并 / 归档模块，都是业务变更。网页对内部整理单落地后出现的模块新版本给出提醒。
- 提示词：内部整理先用 `dry_run` 核对（`blocks` 等为空才算）、全局 key 先 `list_projects`、漏了 covers 怎么补、不要试别人的 key 文件；扫描 Agent 重点标出升了级的内部整理单。

## 0.2.5 — 备份导出，收紧 admin key

- **备份与导出**（本机命令，不走 HTTP）：`speclock backup`（SQLite 在线备份，完整）、`speclock restore`（先检查、服务在跑就拒绝、原库改名留着）、
  `speclock export`（当前规格 + 审核单导出成 Markdown 和 spec.json，无时间戳、按 id 排序，可提交进 git）。
- **admin key 不再放进 Agent 读得到的地方**：`init` 不再打印含 admin key 的 `.mcp.json` 片段，改为提示"别写进项目文件"并给出下一步；
  人用的 CLI 没有 key 时在终端提示输入（不用存文件）；`roles/common.md` 写明发现项目文件里有 admin key 时不要用、告诉用户。
- **MCP 不依赖启动时的工作目录**：`speclock key create` 和 `create_api_key` 现在返回现成的 `.mcp.json`（`mcp_config`：key 文件名 + 写死的 `SPECLOCK_HOME` + Python 绝对路径），
  跟项目走、跟电脑走一样；端到端脚本两种用法各跑一遍（50 项检查）。
- 内部整理的审核单不再强求写验收条件（改名、搬模块本来就没有）。
- 文档重做：README 改为简洁的项目主页（logo、工作方式与架构两张示意图、原则、快速开始），实用内容挪到新的 `docs/GUIDE.md`（使用指南）。

## 0.2.4 — 网页可嵌入

- 网页既可以单独打开，也可以一键嵌进别的前端：`GET /embed.js` 是统一入口，`<div data-speclock="overview">` 即用，高度自适应；
  也可以 `SpecLock.mount(...)` 用代码控制，或纯 iframe 加 `?embed=1`。
- 嵌入模式只显示内容（没有侧栏、顶栏），站内跳转保持 `embed` 参数，通过 `postMessage` 向外层报告 ready / navigate / height，并接受外层的跳转指令。
- 只有 `embed_origins` 里的来源能嵌（响应头 `frame-ancestors`），默认只有本机；在 `.speclock/config.toml` 里改。
- 网页新增「嵌入」页，列出可复制的代码；新增文档 `docs/EMBED.md`。
- 没有构建网页时，`/` 显示构建提示页而不是 404。

## 0.2.3 — 补齐工具

- MCP 新增 4 个工具（共 33 个）：`list_projects`、`create_project`、`rename_project`、`get_activity`。
  之前全局 key 开审核单要 `project_id`，却没有任何办法列出或创建项目。
- 刻意不做的：已归档模块不给 Agent 看；搜索不做成 Agent 工具（Agent 从索引逐层定位：大业务 → 小业务 → 模块）；角色增删改只留 REST。
- CLI 新增 `speclock project list|create|rename`。
- `list_api_keys` 的说明改为需要 `key.read`（原写 `key.manage`，已过时）。
- 需求 / 扫描 Agent 的提示词补上新工具和"逐层定位"的做法。

## 0.2.2 — key 存成文件

- **Agent 类 key 存成 `.speclock/keys/` 里的文件**（一把一个，`<角色>--<名称>.key`）：创建时由服务端直接写，响应里只有文件名、没有明文，
  明文不经过对话；吊销时文件一并删除；`keys/README.md` 告诉 Agent 只读自己的那个，`.gitignore` 忽略 `*.key`。
  人类 key（admin / reviewer）不存文件，创建时显示一次，由人保管。
- MCP 直接读 key 文件：`speclock mcp --key-file …` / `SPECLOCK_KEY_FILE`，`use_api_key` 新增 `key_file` 参数。
- 新命令 `speclock key show <id>`（查看已保存的 Agent key）、`speclock init --new-admin`（admin key 丢了再发一把）。
- 网页的 Agent 页显示每把 key 的文件名（不显示内容）。
- `roles/` 的提示词改为：身份里写 key 文件名而不是 key 本身。
- 测试不再有机会碰到真实的 `.speclock/`。

## 0.2.1 — 网页免登录

- 网页不再需要登录，也不再持有 admin key：自动使用一把 `viewer` 角色的只读 key（`.speclock/web.key`），
  经 `GET /api/v1/web/session` 取得，只对本机同源请求开放。
- 新增预置角色 `viewer` 和权限 `key.read`（读密钥 / 角色 / 权限目录，不含明文）；`/keys`、`/roles`、`/permissions` 的读取改用它，
  创建 / 修改 / 吊销仍然是 `key.manage`。老库升级时自动给 admin 补上 `key.read`。
- 删除登录页和"退出登录"。

## 0.2.0 — Agent 优先

**从这一版起，人不再直接操作需求库**：规格由 Agent 维护，人只做授权和监控。

- **唯一的写入通道**：Agent 开审核单 → 人批准 → Agent 提交 Commit（原子、可预览、可回滚）。没有任何直接建 / 改 / 发布模块的接口。
  批准靠人的明确输入（对话里的原话 + 内容哈希，或 `speclock cr approve`），网页没有任何操作按钮。
- **稳定 id、版本与溯源**：规则 / 验收条件带 `R-n` / `AC-n`；模块和小业务各有版本和结构化 diff；
  每个版本可追溯到哪个 Commit、哪个审核单；`move_block`；模块版本历史接口。
- **角色与权限**：key 绑定角色，角色是权限集合；预置 admin / reviewer / requirements / executor / tester / scanner。
  人类专属权限不能挂在 Agent 角色上；创建 key 是危险操作，必须有人的原话；`use_api_key` 会话内切换。
- **执行记录**：每个模块版本一条，`pending → in_progress → implemented → verified`（及 `blocked` / `failed`）；
  领取时拿到锁定版本的规格，逐条验收条件给证据，验收必须由另一把 key 完成。
- **内部整理**：审核单可由需求 Agent 声明为内部整理（不经人批准，Core 只留痕、不判断内容）。
- **只读网页**：总览、文档树、追溯、审核单、待办、活动时间线、Agent 与密钥、搜索，自动刷新。
- **开箱即用**：`speclock init` 在项目里建 `.speclock/`（或 `--global` 建在 `~/.speclock/`），随机 admin key，
  统一命令 `speclock init / serve / mcp / cr / key`；`roles/` 是推荐的角色提示词。MCP 共 29 个工具。

## 0.1.0 — 人与 Agent 协同

最初的版本：人在网页里编辑文档、发布，有提案收件箱和破坏性变更确认；Agent 通过 REST / MCP 读取已发布版本。

> 开发过程中提交记录里出现过 0.3 ~ 0.9 的编号，那是内部迭代时的临时标记，没有发布过，已统一并入 0.2.0。

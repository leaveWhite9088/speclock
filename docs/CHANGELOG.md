# 版本记录

版本号的源头是 `speclock/__init__.py` 的 `__version__`。

## 0.2.5 — 备份导出，收紧 admin key

- **备份与导出**（本机命令，不走 HTTP）：`speclock backup`（SQLite 在线备份，完整）、`speclock restore`（先检查、服务在跑就拒绝、原库改名留着）、
  `speclock export`（当前规格 + 审核单导出成 Markdown 和 spec.json，无时间戳、按 id 排序，可提交进 git）。
- **admin key 不再放进 Agent 读得到的地方**：`init` 不再打印含 admin key 的 `.mcp.json` 片段，改为提示"别写进项目文件"并给出下一步；
  人用的 CLI 没有 key 时在终端提示输入（不用存文件）；`roles/common.md` 写明发现项目文件里有 admin key 时不要用、告诉用户。
- **MCP 不依赖启动时的工作目录**：`speclock key create` 和 `create_api_key` 现在返回现成的 `.mcp.json`（`mcp_config`：key 文件名 + 写死的 `SPECLOCK_HOME` + Python 绝对路径），
  跟项目走、跟电脑走一样；端到端脚本两种用法各跑一遍（48 项检查）。
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

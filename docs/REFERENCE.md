# SpecLock 参考手册

> 上手看 [使用指南](GUIDE.md)。这里是完整的特性、接口与规则说明。

> **其他 spec 工具把文档放进 repo 让 agent 可以改；SpecLock 把文档放在只读 API 后面。**


SpecLock 是业务文档的**单一事实源（Single Source of Truth）平台**，为"AI 参与开发"的团队设计：

- 文档按 **项目 → 大业务 → 小业务 → 模块** 四级管理，带两级语义化版本与结构化 diff；
- 开发 AI 通过 REST + MCP 读取**已发布版本**；
- 规格库**只有一条写入通道**：需求 Agent 整理**审核单（Change Request）**→ 人批准 → 需求 Agent 在已批准的审核单下提交 **Commit**；人不直接改库，Agent 也批准不了任何东西。SpecLock 自己不是 Agent，只提供让外部 Agent 接入的接口。

约束是物理的（权限隔离），不是提示词约定。

架构：**FastAPI 纯 JSON API + Vue 3 展示网页（`apps/web/`，参考实现）**。后端只出 JSON；网页是**人监控整个工具的唯一通道**，**只读展示**（总览、文档树、模块与版本、审核单、待办、活动时间线、Agent 与密钥、搜索、归档、AI 接入说明），不提供任何修改操作，只调用公开 REST 接口，别人想自己做一个同样能接。构建产物（`apps/web/dist/`）存在时由同一 FastAPI 进程顺带托管，不构建或不打开它都不影响 Core。所有修改都由 Agent 经 MCP 完成。

## 目录

- [为什么需要它](#为什么需要它)
- [核心特性](#核心特性)
- [工作原理](#工作原理)
- [文档模型](#文档模型)
- [快速开始](#快速开始)
- [配置与数据目录](#配置与数据目录speclock)
- [密钥管理](#密钥管理)
- [Agent 接入](#agent-接入)
- [REST 接口约定](#rest-接口约定给外部集成方)
- [规则摘要](#规则摘要)
- [License](#license)

## 为什么需要它

AI 辅助开发中有两个已被一线实践反复验证的问题：

1. **业务漂移**：开发 AI 为理解业务必须参考文档，但只要它能写，就一定会改；业务被改 → 对端提新需求 → 无限循环。
2. **文档与代码脱节**：文档靠人脑维护，执行阶段无人遵守，停留在项目初期丧失指导意义。

根因判断：AI 对文档只要拥有写权限就一定会改文档。因此约束必须是**物理的**（权限隔离），不能是**约定的**（提示词）。SpecLock 把这条原则落到代码结构里：key 绑定**角色**，角色是**权限集合**；批准审核单是人类专属权限，挂不到任何 agent 类角色上，agent 凭据对批准接口 100% 返回 403。

## 核心特性

- **角色与权限** — key 绑定角色，角色是权限集合（权限目录由代码定义，角色与映射可自定义，预置 admin（超级管理员）/ project-admin（项目管理员）/ reviewer / requirements-agent / executor-agent / tester-agent / scanner-agent，各角色推荐的提示词在 [`roles/`](roles/)；scanner 只能读，不能开单）；接口按权限放行。人类专属权限（批准 / 驳回审核单、管理项目与密钥）不能挂在 agent 类角色上，约束是物理的
- **审核单 + Commit 是唯一写入通道** — 没有任何直接建 / 改 / 发布模块的接口。审核单只含业务意图（为什么变、变成什么样、不再成立的旧认知、验收条件、影响说明），提交即冻结并带内容哈希，批准后不可改；批准渠道（自然语言 / CLI）与原话留痕；Commit 是已批准审核单下的原子写入，整体成功或整体回滚
- **项目级文档隔离** — 项目是文档隔离单元，每个项目有独立的一套 大业务→小业务→模块；key 绑定到单个项目后，跨项目的模块 / 文档 / 待办 / 审核单访问一律 404；**Agent 类角色和项目管理员（project-admin）的 key 必须绑定项目**，只有超级管理员 admin 可以是全局的（可见全部项目）
- **结构化文档模型** — 模块内容不是一整段散文，而是：业务背景（叙述）+ 业务规则清单 + 验收条件（均为结构化，每条带稳定 id，逐条可 diff）+ API 列表（结构化，每条带端点语义）；发布时强制结构完备性校验（见[文档模型](#文档模型)）
- **结构化 API 文档** — API 区是递归字段模型（`object`/`array` 可无限嵌套 `children`），编辑与 diff 的真相源是结构化数据；发布时自动生成 OpenAPI 3.x YAML 供下游消费，全程不需要面对 YAML
- **两级版本** — 模块独立递增 semver，级别标签由代码按结构化 diff 机械算出（有任何删除或修改 → MAJOR，只有新增 → MINOR，其余 PATCH），只是给外部 Agent 的参考，Core 不规定它们据此该做什么；任一模块发布时所属小业务自动派生小业务版本（manifest = 全部模块当前版本清单）
- **字段级 diff 与版本标签** — 基于递归 flatten 的点号路径（如 `response:GET /x:data.items.id`）；API 侧任何删除（含可选字段）或类型 / 必填标志变更都算 MAJOR 级变更；规则与验收条件按稳定 id 匹配，详述变了算修改，只改名称算 renamed（PATCH）
- **分层索引树** — agent 一次调用 `get_index` 拿到 大业务→小业务→模块 三层概要树（小业务节点带可选的一句话简述）（模块节点带一句话摘要与当前版本的执行状态），选中后再按需精读，上下文占用最小
- **内部整理（由 Agent 声明，Core 不判断）** — 审核单有 `kind`：业务变更（默认，须人批准）或内部整理（由需求 Agent 声明并写明理由，提交即生效，需要 `cr.internal` 权限）。内部整理只有改名和搬模块两类（不产生新的模块版本），改了模块内容的任何一个字都是业务变更；「是不是业务变更」只能由 Agent 判断，规矩写在 [`roles/requirements-agent.md`](roles/requirements-agent.md) 的提示词里；Core 不比较内容，只留痕（声明者、理由、版本 diff、审计），网页上标注「由 Agent 自行判定」。新操作 `move_block`
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
批准 / 驳回（对话中的明确输入 / CLI）──►
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

见 [使用指南](GUIDE.md)。

### 网页的页面

网页是人监控整个工具的唯一通道，只做展示，没有任何操作按钮（批准靠对话里人的明确输入，或 CLI）。顶栏有全局搜索（按 `/` 聚焦）和刷新状态指示：全站每 5 秒看一眼有没有新的变化，有就让当前页面静默刷新（保留你展开的内容和滚动位置）。

| 页面 | 回答什么 |
|---|---|
| 总览 `/` | 现在有什么需要我关注的：等我确认的审核单、卡住的任务（被阻塞 / 失败）、Agent 自行判定的内部整理、等验收、进行中，以及数字概览和最近活动 |
| 文档树 `/tree` | 大业务 → 小业务 → 模块；小业务显示「已验收 / 总数」，可按执行状态筛选 |
| 审核单 `/change-requests` | 全部审核单；详情里有「落地明细」：Commit → 受影响的模块 / 小业务（版本怎么变的）→ 现在的执行状态 |
| 待办 `/work` | 每个模块版本的执行记录与事件历史 |
| 活动 `/activity` | 谁在什么时候做了什么，按天分组，可按类别 / 谁 / 时间 / 对象筛选（条件写在地址栏） |
| Agent `/agents` | 有哪些密钥、各是什么角色、手里有什么权力、最近有没有在用；角色 × 权限矩阵（需要 `key.manage`） |
| 搜索 `/search` | 在已发布模块的当前版本和审核单里找关键词，命中词高亮，规则 / 验收条件直达对应的行 |
| 模块页 | 完整快照、版本历史（每个版本可展开「为什么改」与执行进展）、版本对比 |

代码结构（`apps/web/src/`）：`api/`（客户端 + 按资源封装的请求）、`composables/`（`useAsync` 取数、`usePolling`、`useChangeSignal` / `useAutoRefresh` 自动刷新）、`components/`（只收 props 的展示组件）、`views/`（薄页面）、`labels.js`（全站统一中文文案）、`errors.js`（请求错误翻成人话）；整理逻辑都是纯函数（`overview.js` / `activity.js` / `agents.js` / `search.js` / `trace.js` / `treeFilter.js`），都有单元测试。

展示网页是 Vue 3 SPA（只读）。构建后由后端顺带托管（发布版本已带构建产物；自己改前端才需要 `cd apps/web && npm install && npm run build`）。启动服务后访问 `speclock init` 打印的地址即可，**网页不用登录**：它从 `GET /api/v1/web/session` 自动取一把只读 key（`viewer` 角色，**绑定一个项目**，是一把和其他 key 一样存在 `.speclock/keys/` 的普通 key，项目创建时自动建），只对本机地址、同源请求开放。**网页一次只看一个项目**：地址带 `?project=<项目 id>` 指明；库里只有一个项目时自动选它；有多个又没指明时先显示项目选择页。别的项目的内容它拿不到（用的是绑定项目的 key，隔离由服务端保证）。

**嵌入**：网页可以被一键嵌进别的前端（`/embed.js` + `?embed=1`），只读、高度自适应、有 `postMessage` 通信，只有 `embed_origins` 里允许的来源能嵌，详见 [EMBED.md](EMBED.md)。

前端开发模式（热更新，vite 把 `/api` 代理到 `SPECLOCK_URL`，默认 47821）：

```bash
cd apps/web && npm install && npm run dev     # 默认 http://127.0.0.1:5173/
```

所有 API 请求带 `X-API-Key` 请求头。

> SpecLock 是**本机个人使用**的需求管理工具，不是为公网部署设计的，服务只监听 127.0.0.1。

## 备份与导出

两件不同的事，都是**本机命令**，直接读 `.speclock/` 里的库，不走 HTTP、不需要 key：

| 命令 | 做什么 |
|---|---|
| `speclock backup [--out 文件]` | **完整备份**：用 SQLite 在线备份拷出整个库（服务在跑也安全），含全部版本历史、审核单、执行记录、密钥哈希。默认放 `.speclock/backups/`（被 `.gitignore` 忽略）。已有同名文件不覆盖 |
| `speclock restore <备份文件>` | 用备份恢复：先检查是 SpecLock 的库且完整；**服务还在运行就拒绝**；原来的库改名留着（`speclock.db-before-restore-时间`） |
| `speclock export [--out 目录]` | **可读的文本快照**：当前已发布的规格（`<项目>/<大业务>/<小业务>/<模块>.md`）、每张审核单（`change-requests/`）、`index.md`、`spec.json`。**没有时间戳、按 id 排序**，重复导出内容一字不差，可以提交进 git 对照历史。默认 `.speclock/export/` |

`export` 是单向的只读快照，不能导回库里（要还原用 `restore`）；已归档的模块不导出，它们在完整备份里。
导出目录必须是空目录或以前导出过的目录（里面有 `.speclock-export` 标记），否则拒绝，避免误删别的文件。

## 配置与数据目录（`.speclock/`）

配置和数据库放在 `.speclock/` 目录里，**不放在 SpecLock 源码目录**：

```
.speclock/
├── config.toml     # host（固定 127.0.0.1）/ port / 数据库文件名；不含任何密钥，可提交 git
├── speclock.db     # 数据库，init 生成的 .gitignore 默认忽略
└── .gitignore
```

- **跟项目走**：在项目根目录 `speclock init`，生成 `<项目>/.speclock/`，端口自动选一个空闲的。
- **跟电脑走**：`speclock init --global`，生成 `~/.speclock/`，默认端口 `47821`。起一个服务，所有项目的 Agent 都连它（每个项目一套 key，项目隔离）。
- **查找顺序**（和 git 找 `.git` 一样）：环境变量 `SPECLOCK_HOME`（直接指向某个 `.speclock` 目录）→ 从当前目录往上找最近的 `.speclock/` → `~/.speclock/`。所以 SpecLock 源码克隆在项目里面（如 `myproject/speclock/`）也没问题：在那里运行同样能找到 `myproject/.speclock/`。
- `SPECLOCK_DB_URL` 环境变量可直接指定数据库地址（测试用）；MCP 与 CLI 的服务地址可用 `SPECLOCK_URL` 覆盖。

## 密钥管理

- **数据库只存 SHA-256 哈希与脱敏 hint**（如 `human-…26c7`），不存明文。明文放在哪取决于 key 的类别：
  - **Agent 类 key**（需求 / 执行 / 测试 / 扫描）：创建时由服务端直接写成 `.speclock/keys/<角色>--<名称>.key`，**响应里只有文件名，没有明文**，明文不经过任何对话。`keys/` 下有 `README.md`（告诉 Agent 只读自己的那个文件）和 `.gitignore`（忽略 `*.key`）。吊销 key 时文件一并删除；`speclock key show <id>` 查看内容；网页的 Agent 页只显示文件名。
  - **人类 key**（admin / reviewer）：不存文件，明文只在创建时返回一次，请自己保管；丢了就新建一把。
  - 同一个项目目录里 Agent 互相看得见文件，所以"只读自己的 key 文件"靠 README 和提示词约束，Core 强制不了。
- 创建 key 时选**角色**（`POST /api/v1/keys {role, label, project_id?, via?, evidence?}`；**除超级管理员 admin 外的所有角色都必须带 `project_id`**，否则 422 `project_required`；key 由超级管理员创建 / 吊销，项目管理员不管 key），key 类别（human-* / agent-*）由角色的 kind 决定；**不预置多把 key**：`speclock init` 只发一把随机的 admin key，其余由持有 admin key 的 Agent 经 MCP `create_api_key` 创建——必须先问人，附人同意的原话（`via=natural_language` 不带 `evidence` 会 422，来源与原话写进审计）；`speclock key create` 是兜底；吊销即生效（下次请求 401）；最后一把超级管理员 key 拒绝删除
- **角色与权限**：权限目录由代码定义（`GET /api/v1/permissions`），角色可自定义（`/api/v1/roles` 增删改，预置角色可改权限、不可删）。预置：`admin`（超级管理员，全部权限，可以是全局的）、`project-admin`（项目管理员 / 项目主管：看**本项目**的卡点、失败、待审批和活动日志，批准 / 驳回审核单，删本项目的模块；绑定项目，不管 key / 项目 / 角色）、`reviewer`（读 + 批准 / 驳回，绑定项目）、`requirements-agent`（读 + 整理审核单 + 内部整理 + 提交 Commit）、`executor-agent`（读 + 领取 / 实现）、`tester-agent`（读 + 独立验收）、`scanner-agent`（只读规格 / 审核单 / 待办，不能开单、不能提交 Commit）。agent 类角色挂不上人类专属权限（`cr.approve` / `project.manage` / `key.manage`），改权限也不能让系统里没有超级管理员
- **给各目录的 Agent 发身份**：同一目录下多个 Agent 彼此看得见对方的文件，身份靠各目录 AGENTS.md 里的提示词。[`roles/`](roles/) 是我们推荐的一套：`common.md`（先 `whoami`、已有 key 不重复创建、创建 key 是危险操作必须先问人）加需求 / 执行 / 测试 / 扫描四个角色文件，复制到对应目录的 AGENTS.md 并填好「我的 SpecLock 身份」（写文件名，不写 key）。key 由人用 `speclock key create` 创建，或在人同意后由持有 admin key 的 Agent 创建，创建后用 `use_api_key(key_file=…)` 立即切换使用，不需要重启客户端；Agent 的配置里只写 key 文件名（`speclock mcp --key-file …`），不写 key 本身
- 项目绑定对所有 key 生效：绑定后该 key 只能访问所选项目；不绑定 = 全局，只有超级管理员 admin 允许。项目管理员读到的活动、待办、审核单、key 列表都只限本项目
- `GET /api/v1/me` 返回当前 key 的角色与权限
- 审计只记录 hint，不记录明文

## Agent 接入

### 审核单 → Commit（唯一写入通道）

```bash
REQ="agent-xxx"   # requirements-agent 角色的 key
H="http://127.0.0.1:<端口>/api/v1"
# 1. 需求 Agent 建单（草稿），只写业务意图；验收条件的 id（AC-n）由服务端分配
curl -X POST -H "X-API-Key: $REQ" -H "Content-Type: application/json" $H/change-requests -d '{"title":"日报口径调整","intent":"财务要求销售额含退款","expected_outcome":"日报销售额含退款","obsolete":["销售额不含退款"],"acceptance":[{"name":"口径一致","detail":"日报销售额与财务报表一致"}],"project_id":1}'
curl -X POST -H "X-API-Key: $REQ" $H/change-requests/1/submit           # 提交：内容冻结 + 内容哈希
# 2. 人批准（对话中的明确输入 / CLI，都必须出示人类 key，且带上看过的内容哈希）；网页只做展示，没有按钮
speclock cr approve 1                                              # 或 --hash <哈希前缀>
# 3. 需求 Agent 在已批准的审核单下提交 Commit：一组 ops，原子写入并发布，covers 声明满足的验收条件
curl -X POST -H "X-API-Key: $REQ" -H "Content-Type: application/json" $H/change-requests/1/commits -d '{"covers":["AC-1"],"ops":[{"op":"update_block","id":1,"rule_ops":[{"op":"upsert","id":"R-1","entry":{"name":"销售额口径","detail":"支付成功订单金额合计（含退款）"}}]}]}'
curl -X POST -H "X-API-Key: $REQ" $H/change-requests/1/complete        # 覆盖检查通过 → applied
```

Commit 的 ops：`create_business` / `update_business` / `create_capability` / `update_capability` / `create_block` / `update_block`（整体替换 `rules` / `apis` / `acceptance`，或增量 `rule_ops` / `api_ops` / `acceptance_ops`）/ `archive_block` / `restore_block` / `move_block`（搬到另一个小业务，保留身份与历史）；同一 Commit 里先建的对象起 `ref` 名，后面用 `"$ref"` 引用其 id。`dryRun: true` 预览不落库。

### 读规格（REST）

```bash
KEY="agent-xxx"
curl -H "X-API-Key: $KEY" http://127.0.0.1:<端口>/api/v1/index             # 三层索引树（一次拿全图）
curl -H "X-API-Key: $KEY" "http://127.0.0.1:<端口>/api/v1/work?status=pending"    # 待办队列
curl -H "X-API-Key: $KEY" http://127.0.0.1:<端口>/api/v1/blocks/1@1.0.0    # 精读模块（版本 pin；响应带 cr_id / commit_id 溯源）
curl -H "X-API-Key: $KEY" http://127.0.0.1:<端口>/api/v1/capabilities/1@1.2.0 # 小业务 manifest（pin 历史快照）
curl -H "X-API-Key: $KEY" "http://127.0.0.1:<端口>/api/v1/blocks/1/diff?from=1.0.0&to=1.1.0"
curl -X POST -H "X-API-Key: $EXEC" http://127.0.0.1:<端口>/api/v1/work/1/claim   # 领取，返回锁定版本的完整规格
curl -X POST -H "X-API-Key: $EXEC" -H "Content-Type: application/json" http://127.0.0.1:<端口>/api/v1/work/1/implementation -d '{"results":[{"ac_id":"AC-1","result":"pass","evidence":"测试输出……"}]}'
curl -X POST -H "X-API-Key: $QA" -H "Content-Type: application/json" http://127.0.0.1:<端口>/api/v1/work/1/verification -d '{"results":[{"ac_id":"AC-1","result":"pass","evidence":"独立验证……"}]}'
```

### 人批准：CLI

```bash
# 注意：SPECLOCK_KEY 只给你自己的命令用；MCP 配了 --key-file 时以 key 文件为准，不会被它顶替
# 不设 SPECLOCK_KEY 也行：在终端里运行时会提示输入 admin / reviewer key（输入不显示），不用把它存进任何文件
export SPECLOCK_KEY=<人类 key>   # 或者设环境变量 / 传 --key；服务地址默认取自 .speclock/config.toml
speclock cr list --status pending_review
speclock cr show 1
speclock cr approve 1 [--hash <内容哈希前缀>] [--via natural_language --evidence "同意，按这个来"]
speclock cr reject 1 --reason "验收条件没写清楚"          # 驳回必须写理由；rejected 是终态
speclock key create --role executor-agent --label "后端执行 Agent"   # Agent 类 key 存成 .speclock/keys/ 里的文件
speclock key show 3                                                  # 查看已保存的 Agent key
```

### MCP（Claude Code 等）

给某个 Agent 的 `.mcp.json`：**用 `speclock key create` 创建 key 时会直接打印这段**（经 MCP 的 `create_api_key` 创建时，响应里的 `mcp_config` 也是这段），不用手写：

```json
{
  "mcpServers": {
    "speclock": {
      "command": "<python 的绝对路径>",
      "args": ["-m", "speclock", "mcp", "--key-file", "tester-agent--qa.key"],
      "env": { "SPECLOCK_HOME": "<.speclock 的绝对路径>" }
    }
  }
}
```

要点：里面只有 key 的**文件名**，没有 key 本身；`SPECLOCK_HOME` 写死，MCP 据此找到服务地址和 `keys/`，所以**不管客户端从哪个目录启动都能用**，
跟项目走（`<项目>/.speclock`）和跟电脑走（`~/.speclock`）两种用法完全一样。

MCP 启动时会在 stderr 打印服务地址、数据目录（以及它是怎么找到的）和身份来源；`whoami` 返回里有 `key_source`。**配了 `--key-file` 就以 key 文件为准**，忽略环境变量 `SPECLOCK_KEY`（免得你在 shell 里为跑命令设的 admin key 顶替了 Agent 的身份）。`use_api_key(key_file=…)` 只认 `keys/` 里的**文件名**，带路径一律拒绝。工具参数拼错（多出不认识的参数）会直接报错。

**admin key 不要写进项目里的 `.mcp.json`**（同目录的 Agent 读得到）。需要让客户端以管理员身份代你操作时，配在用户级的 MCP 配置里（如 `claude mcp add --scope user`），
并且只在你自己跟它对话的那个会话里用。

MCP server 暴露 **37 个工具**，key 的角色决定哪些能用（没权限的返回 403；admin key 全部可用）：

| 工具 | 权限 | 用途 |
|---|---|---|
| `whoami` | 任意 | 当前 key 的角色与权限 |
| `get_index` / `get_block` / `get_capability` / `get_diff` | `spec.read` | 读规格：索引树、模块（带版本级别标签与 cr_id / commit_id）、小业务 manifest、版本 diff |
| `list_projects` | `spec.read` | 看得到的项目（全局 key 开审核单、建 key 绑项目要用 id） |
| `create_project` / `rename_project` | `project.manage` | 创建项目 / 项目改名（人类专属权限，只有 admin 能做；先问人） |
| `delete_block` / `delete_capability` / `delete_business` | `spec.delete` | **危险操作，不可恢复**：删除模块 / 小业务 / 大业务（连同下面的模块、版本历史、执行记录）。已发布的模块要先通过审核单归档，否则 409 `published_blocks_exist`；**必须有人批准的审核单授权**：先开一张业务变更单写明要删什么（点名它的名称）、等人批准，再把它的 `cr_id` 传进来；`spec.delete` 是人类专属权限（admin / project-admin） |
| `delete_project` | `project.manage` | **危险操作，不可恢复**：删除整个项目（含全部内容、审核单和绑定它的 key）。里面还有已发布模块时拒绝；只有超级管理员 admin 能做；同样必须有该项目里人批准过、点名这个项目的审核单（`cr_id`） |
| `get_activity` | `audit.read` | 审计日志（新的在前），可按谁 / 动作 / 对象 / 时间筛选，`before_id` 往回翻页、`after_id` 取更新的事件 |
| `get_block_history` / `get_capability_history` | `spec.read` | 版本历史（从旧到新）：级别标签、变更说明、delta、产生它的审核单 / Commit、状态（current / deprecated）；小业务历史带 manifest |
| `list_work` / `get_work` | `exec.read` | 待办队列（按状态筛选）/ 一条执行记录：事件历史、已提交结果、锁定到该版本的完整规格 |
| `claim_work` / `release_work` / `report_blocked` / `report_failed` / `submit_implementation` | `exec.write` | 执行 Agent：领取、放弃、报告业务阻塞 / 失败（必须写原因）、提交实现结果（逐条验收条件 pass + 证据，缺一条或有不通过都被拒） |
| `verify_work` | `exec.verify` | 测试 Agent 独立验收：逐条给结果，全通过 → verified，有不通过 → failed；验证者不能是实现者 |
| `create_api_key` | `key.manage` | **危险操作**，只有 admin 能做：必须先问人并等到明确同意，附人同意的原话 `evidence`；Agent 类 key 由服务端存成 `.speclock/keys/` 里的文件，只返回文件名；人类 key 明文只返回一次 |
| `list_api_keys` / `revoke_api_key` | `key.manage` | 列出密钥（带活动统计，不含明文）/ 吊销密钥（不可恢复；**危险操作**，须先问人并附原话 `evidence`；最后一把管理员 key 删不掉） |
| `use_api_key` | 任意 | 在当前 MCP 会话里切换使用的 key，不用重启客户端；可传 `key_file`（keys/ 里的文件名，不用看到明文）；都不传则切回配置里的那把 |
| `list_change_requests` / `get_change_request` | `cr.read` | 读审核单（含状态、覆盖情况、人的决定与驳回理由） |
| `create_change_request` / `update_change_request` / `submit_change_request` / `withdraw_change_request` | `cr.write` | 整理审核单：草稿 → 提交（冻结）→ 需要改时撤回 |
| `submit_commit` / `complete_change_request` | `commit.write` | 在已批准的审核单下写规格库 / 报告完成 |
| `approve_change_request` / `reject_change_request` | `cr.approve` | Agent **代人**批准 / 驳回：必须带上人看过的那一版的 `content_hash` 与人的原话 `evidence`（驳回必须写理由），Core 把渠道记为 natural_language 并留原话；没有人的明确指示时不得调用 |

所有操作都由 Agent 经 MCP 完成；网页只做展示（参考实现，可不启动），也只调用公开 REST 接口，别人想自己做一个同样能接。

## REST 接口约定（给外部集成方）

- **接口契约**：[`docs/openapi.json`](openapi.json) 是整份 OpenAPI 的快照（服务运行时 `/openapi.json` 是同一份，多一个版本号），每个接口的返回结构都有声明；
  它有测试盯着，接口形状变化会在 [CHANGELOG](CHANGELOG.md) 里写明。
- **MCP 工具契约**：[`docs/mcp_tools.json`](mcp_tools.json) 列出每个工具的参数、调用的 REST 接口和返回结构。工具返回文本 `{"status": <HTTP 状态码>, "body": <REST 响应>}`（连不上服务时是 `{"error": …}`），`body` 的形状见 `returns` 引用的响应模型。
- **健康检查**：`GET /api/v1/health` → `{"status":"ok","version":"0.2.7"}`。不需要 key，只对本机地址开放（Host 不是回环地址返回 403）；数据库读不动时返回 503 + `{"status":"error",…}`。
- **错误**：所有错误都是 `{"detail": …, "code": …}`。`detail` 是给人看的中文（有的是带结构的对象，如 `{"error", "missing"}`；请求体字段校验失败时是 FastAPI 的错误列表），措辞可能调整，**程序请按 `code` 判断**：

| code | 状态码 | 含义 |
|---|---|---|
| `unauthenticated` | 401 | 缺少 `X-API-Key`，或 key 不存在 / 已吊销 |
| `permission_denied` | 403 | key 的角色缺少该接口需要的权限 |
| `not_found` | 404 | 不存在，或这把 key（项目隔离）无权访问——两者故意不区分 |
| `bad_request` / `method_not_allowed` | 400 / 405 | 请求本身不合法 / 路径不支持该方法 |
| `validation_failed` | 422 | 请求内容校验失败（字段缺失、类型不对、业务校验不通过） |
| `conflict` | 409 | 与当前状态冲突（没有更具体的 code 时） |
| `cr_state_conflict` | 409 | 审核单当前状态不允许这个操作（含在未批准的审核单下提交 Commit） |
| `cr_content_changed` | 409 | 批准时带的 `content_hash` 过期（撤回并重新提交过） |
| `cr_supersede_invalid` | 409 | 要取代的审核单不是 `approved` |
| `cr_no_commits` / `cr_coverage_incomplete` | 409 | 完成审核单时：还没有 Commit / 仍有验收条件没被覆盖（`detail.missing`） |
| `cr_not_owner` | 403 | 草稿只有开单的 key（或管理员）能改、提交、撤回 |
| `work_superseded` | 409 | 执行记录针对的版本已被取代（`detail.latest_work_id` 指向最新的） |
| `work_state_conflict` / `work_already_claimed` | 409 | 记录当前状态不允许该操作 / 已被别人领取 |
| `work_not_holder` / `work_verifier_is_implementer` | 403 | 只有领取者能操作 / 验证者不能是实现者 |
| `block_archived` | 409 | 模块已归档 |
| `local_only` | 403 | 接口只对本机地址开放 |
| `project_required` | 422 | 除超级管理员 admin 外，所有角色的 key 都必须绑定项目（创建时传 `project_id`） |
| `super_admin_required` | 403 | 只有超级管理员能做：改角色、建带人类专属权限的 key（项目管理员只管本项目的 key） |
| `delete_needs_approval` | 409 | 删除必须由本项目里人批准过的业务变更单授权（`cr_id`），且单子里点名了要删的东西 |
| `published_blocks_exist` | 409 | 删除时下面还有已发布的模块：先通过审核单归档（`detail.published_blocks` 列出哪些） |
| `web_project_required` | 422 | `GET /api/v1/web/session`：库里有多个项目，要指明 `project_id` |

- **轮询新事件**：`GET /api/v1/activity?after_id=<已处理到的最大 id>`，只返回更新的事件，排序仍是新的在前（`limit` 默认 50）。
  新事件多于 `limit` 时返回的是最新的那些，用 `before_id=<本页最小 id>` 往回补，直到补到 `after_id`。MCP 的 `get_activity` 也有同名的可选参数 `after_id`，用法一致。
- **待办轮询**：`GET /api/v1/work?status=pending|implemented|blocked|failed`。

## 规则摘要

- **删除语义**：已发布内容不可消失。模块下线 = 通过 Commit 归档（`archive_block`：agent 读 404、索引排除、历史版本保留，并立即派生小业务新版本），可通过 `restore_block` 恢复；没有硬删除接口，只有删除整个项目会级联硬删（且要求其下没有已发布模块）
- **没有作废功能**：发布错了就再提一个审核单往前改（留痕完整，追溯链不断），不提供撤回已发布版本的入口；版本号永不复用
- **版本级别标签**：`diffing.bump_level` 对整份 delta 机械算出——API 或规则 / 验收条件有任何删除或修改 → MAJOR；只有新增 → MINOR；其余（只改背景、条目仅改名）→ PATCH。规则与验收条件是自然语言，机器分不清改措辞与改语义，按保守一侧归类。标签写入 `BlockVersion.level` 并随 `get_block` / `get_diff` 下发，只是参考；agent 读旧版本时响应带派生状态 `status`（`current` / `deprecated`）与 `superseded_by`。
- **执行状态机**：见 `executions.py`。验证者 ≠ 实现者按 key 判定；模块发布新版本时旧版本的未结束记录变 `superseded`，对它们的写操作一律 409 并指向最新版本；归档的模块不出现在待办里，恢复后回来；`verified` 与 `superseded` 是终态，`failed` / `blocked` 可重新领取（不限次数，旧结果清空、历史留在事件里）；不做领取超时。
- **版本**：当前 0.2.0，各版本的变化见 [CHANGELOG](CHANGELOG.md)。从 0.1.0 升上来：配置与数据挪进 `.speclock/`（见上），把原来的 `speclock.db` 复制进去即可继续用；命令合并为 `speclock`。
- **审计**：审核单流转（含批准渠道与原话）/ Commit / 发布（模块 + 小业务）/ 拉取 / 执行记录转换 / 密钥与角色变更全部写 `AuditLog`

## License

[MIT](LICENSE)

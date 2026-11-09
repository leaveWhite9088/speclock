# SpecLock — Agent 工作说明与重构决策记录

> 本文件给在本仓库里工作的 AI agent 读：先读"产品边界"和"已定决策"，再动手。
> 项目正在**整体重构**，目标是对齐设计讨论中的 SpecLock Core。决策有变更时，先改本文件，再改代码。

## 1. 产品定位与边界

SpecLock 是**面向 AI Agent 的业务规格基础设施**：业务事实的单一信源，只管业务，不管实现。

- **Core 是确定性的知识服务**：保存业务事实、管理版本、控制权限、提供上下文。**不含 LLM，不做 Agent 调度，不依赖任何 Agent 框架。**
- 分工：人负责表达业务意图和最终授权；需求 Agent 理解业务、整理变更、维护规格；执行 Agent 按规格自主实现；分析/调度由外部系统完成。
- 人面对业务，Agent 面对结构：人不需要看到模块拆分、版本号、diff 细节。
- 只管业务：后端重构、界面样式、代码组织变化而业务不变，**不产生新版本**。
- 约束是物理的（权限隔离），不是提示词：权限机制已实现（见第 5 节）；编码阶段为方便只发一把 admin key，分权暂时关闭（见「编码阶段的简化」）。

## 2. 层级与术语（已定）

```
Project（项目）            文档隔离单元，agent key 可绑定；"业务隔离" = Project 隔离
 └── Business（大业务）     如：运营 / 采购 / 商品
      └── Capability（小业务）  如：经营日报；只做聚合与版本快照，自身不带 API / 规则
           └── Block（模块）     最小业务知识单元，可单独交给一个 Agent
```

- 中文固定叫法：**大业务 / 小业务 / 模块**。不要再把 Block 叫"小业务"，也不要把 Capability 叫"文档"。
- Block 的内容：业务背景（`content_md`）+ 业务规则清单 + API 列表 + **验收条件**。API 属于 Block，不属于 Capability。
- Capability 版本 = 其全部 Block 当前版本的确定快照（manifest）；任一 Block 发布即派生新的 Capability 版本。
- Capability 有可选的一句话 `summary`，随索引下发给 agent。

## 3. 已完成的重构

- 删除会议记录模块（后端、前端、测试、库表全部移除，数据另有备份）。
- Domain → Business，Document → Capability（表、外键列、模型、接口、MCP、前端、文案）。
  - 接口：`/domains→/businesses`，`/documents→/capabilities`；MCP `get_document→get_capability`；响应字段 `domain→business`、`document_version→capability_version`。**不保留旧别名。**
  - 老库在 `init_db` 里自动迁移（`db._rename_legacy_tables` + `_ensure_columns`），幂等，有测试。
- 删除 `doc_type`；新增 `Capability.summary`（创建 / `PUT /capabilities/{id}` / 索引 / 详情 / 前端编辑）。
- 版本号 0.4.0。**以上改动尚未提交。**

## 4. Block 重构（已实施，尚未提交）

1. **去掉非功能性需求 `nfr_md`**（模型、接口、MCP、前端、数据全部移除，不迁移）。
2. **新增验收条件 `acceptance`**：结构化列表，每条 `{id, name, detail}`，与规则同构；发布时必填至少 1 条；逐条 diff；提案通道有 `proposed_acceptance_ops`。
3. **规则与验收条件带稳定 id**（`R-n` / `AC-n`）：服务端分配（缺 id 的条目在保存 / 发布时补），编号取当前草稿与全部历史快照已用最大编号 + 1，**不复用**；提案 ops 与 delta 都按 id 匹配，不再按名称。
4. **Block 独立语义化版本**：背景、规则、API、验收条件四部分的任何改动都是业务变更。
5. **版本级别标签由代码机械算出，不让 Agent 判断，也不强制外部 Agent 怎么用**（`diffing.bump_level`）：
   - MAJOR：有任何删除或修改——API（删 API / 字段含可选字段、类型或必填标志变更）、规则、验收条件；
   - MINOR：只有新增；
   - PATCH：其余（只改背景、API 文字说明、条目只改名——名称只是标签，详述不变算 `renamed`）。
   - 规则 / 验收条件是自然语言，机器分不清改措辞与改语义，按保守一侧归类。
   - 标签存入 `BlockVersion.level`（`initial|major|minor|patch`），随 `get_block` / `get_diff` / 发布预览下发。**已移除**原有的「破坏性变更」闸门（`breaking` / `affected` / `fastTrack` / `confirm`）：需求数据由 Agent 维护、人只通过审核单与需求 Agent 沟通，不再有人在界面上点确认；发布只保留 `dryRun` 预览。
6. **版本状态**：`Deprecated` 是**派生状态**，不存库——agent 读到不是最新版本的快照时，响应带 `status: deprecated` 与 `superseded_by`；`archived`（模块下线）和 `Deprecated`（被取代）是两回事，不要混。**没有作废功能**：发布错了就再提审核单往前改。`Approved` 等审核单做出来时一起做。

## 5. 审核机制（已实施，0.5.0；尚未提交）

- 现有"提案收件箱 + 人在界面批准并发布"**不是 AI Native 的**，将被**审核单（Change Request）**取代，不需要人进界面介入。
- **人基本不再直接修改需求库**：写入基本由需求 Agent 完成，人只通过审核单与它沟通。因此为"人在界面上编辑 / 确认"设计的东西（破坏性确认闸门、提案收件箱、编辑页的人工流程）都不再是重点，新设计以 Agent 作为写入方。
- 审核单只含业务意图：为什么变、业务变成什么样、哪些旧认知不再成立、验收条件、影响说明。**不含**改哪个 Block、哪个 Agent 负责、什么技术。
- 一个审核单对应多个 Commit，一个 Commit 可涉及多个 Block / Capability；拆分由需求 Agent 内部完成，对人隐藏。已批准的业务语义被改动才需要重新确认，内部重组不需要。
- 顺序（已改）：**不保留旧写入口**。用户明确表示"做对之前不会去用"，所以审核单系统与旧的人工写入口（编辑 Block、发布、提案收件箱 / 批准）**同一轮替换**，不并存。库里的数据是 demo，不迁移。

### 审核单设计（已实施）

- **CR 字段**：`intent`（为什么变）、`expected_outcome`（变成什么样）、`obsolete`（不再成立的旧认知）、`acceptance`（`{id, name, detail}`，`AC-n`）、`impact_note`（需求 Agent 写给人看）、`project_id`、`status`、`created_by`。不含 block_id / 技术方案 / 负责 Agent。
- **状态**：`draft → pending_review → approved → applied`；`pending_review → rejected`；`approved → superseded`。
- **批准后不可修改**：想改就新开 CR 并取代旧的（`superseded`），保证每个 Commit 对应的授权内容不会被悄悄改变。
- **接入方式**：SpecLock **不做 Agent**，而是作为服务提供接口（REST / MCP），供外部 Agent（需求 Agent、执行 Agent 等）接入；需求 Agent 用自己的 agent 类 key 调 CR / Commit 接口。
- **批准方式**：批准只落在"人能点的地方"：一个只读审核页上的批准 / 驳回按钮（不能编辑内容），以及 CLI / 签名命令（人类 key）。**只有人类 key 能把 CR 置为 `approved`**，需求 Agent 的 key 一律 403——Agent 本来就不持有人类 key，所以这是物理约束；"提交后提示人去批准、不要诱导或代替"另外靠需求 Agent 的提示词约束。
- **Commit**：一个 CR 对应多个 Commit，一个 Commit 可涉及多个 Block、跨多个 Capability，是 ops（按稳定 id 的 upsert / delete，沿用提案 ops 的校验与应用逻辑）的原子批次，应用后发布。写入必须带 `approved` 的 CR id，且 key 是需求 Agent 类型、Project 一致。
- **溯源**：`BlockVersion` 记录 `cr_id` + `commit_id`；任何一个版本都能追溯到"哪个 Commit、哪个 CR、为什么改"，反向也能查 CR → Commit → 受影响 Block 版本。
- **覆盖检查（机械，不含 LLM）**：Core 判断不了语义是否吻合，但能检查结构——Commit 须声明自己满足 CR 的哪些 `AC-n`（`covers`），CR 要进入 `applied`，其全部验收条件必须被至少一个 Commit 覆盖。`covers` 声明是否属实，由后续验证环节负责，不由 Core 判断。已确认要做。
- **提交即冻结**：CR 从 `draft` 提交为 `pending_review` 后内容只读；想改要先撤回成 `draft`。批准时携带 CR 内容哈希，批准的就是人看到的那一版。
- **驳回**：`rejected` 是终态，必须填驳回理由，Agent 读到后新开 CR，不在原单上改。
- **角色与权限**：key 绑定**角色**，角色是**权限集合**；角色和权限映射都可自定义，系统预置几个角色（管理员、审核人、需求 Agent、执行 Agent、扫描 Agent）。权限目录由代码定义（接口按权限放行，而不是按 key 前缀）；角色有 `kind`（human / agent），**人类专属权限**（如批准 CR）不允许挂在 agent 类角色上——"Agent 不能替人批准"仍是物理约束。
- **Commit 可新建结构**：新建 Business / Capability / Block、下线 Block 都只能通过带 CR 的 Commit 完成，不再有直接的人工建 / 改 / 发布接口。Commit 原子应用，任何一条 op 失败整体回滚；应用成功即发布，不经过草稿。
- **批准的渠道**（都必须以人类 key 调用 Core，模型本身不持有人类 key）：审核页按钮、CLI / 签名命令、官方 SpecLock-Scaffold 里的按钮或人的明确自然语言批准（由 Scaffold 的代码识别并代人调用，不由模型自己调）。Core 只认"出示了人类 key"，不区分渠道。

### 编码阶段的简化（已定，覆盖上面"批准只落在人能点的地方"的部分）

- SpecLock 是**本机个人使用**的需求管理工具，不做公网部署：不考虑公网安全、会话令牌、跨域加固。
- **暂不区分人和 Agent 的 key**：编码阶段就发**一把拥有全部权限的 admin key**（seed / inject 只生成这一把）。角色与权限机制保留在代码里（预置角色、人类专属权限、测试都在），等将来需要分权时再启用，不删。
- **所有操作都由 Agent 通过 MCP 完成**，包括批准 / 驳回：MCP 提供 `approve_change_request` / `reject_change_request`。因为 Agent 持有 admin key，"Agent 不能批准"在此阶段只是约定，不再是物理约束；为了事后可查，MCP 的批准工具**必须带 `content_hash`（批准的是哪一版）和 `evidence`（人的原话）**，Core 照常留痕（`decision_via=natural_language`）。
- **网页只做展示**（参考实现，可启动可不启动），不承担任何操作；它只调用公开 REST 接口，别人想自己做一个也能接。已做（见第 8 节 `web/`）。

## 6. 执行记录（已实施，0.6.0）

规格状态与执行状态**分开**。Core 只做机械的事——登记、转换、校验、留痕；谁来做、怎么做、做得好不好是外部 Agent 的事。

- **每个已发布的模块版本自动一条执行记录**（发布引擎在发布后 `sync_block`）：`pending → in_progress → implemented → verified`；`in_progress` 可去 `blocked`（业务上卡住，必须写原因）/ `failed`（必须写原因），这两个状态可重新领取（不限次数，旧结果清空，历史留在事件里）；验收不通过也回到 `failed`；模块发布新版本时旧版本上未结束的记录变 `superseded`（对它的写一律 409 并指向最新版本）。`verified` / `superseded` 是终态。
- **领取时拿到锁定版本的完整规格**；不做领取超时，卡住了用 `release_work` 放弃（领取者本人或管理员）。
- **实现结果逐条验收条件**：`submit_implementation` 必须对该版本每条 AC 给 `pass` + 证据，缺一条、证据为空、有不通过都拒绝（做不下去用 `report_failed` / `report_blocked`）。
- **独立验收**：`verify_work` 需要 `exec.verify`（测试 Agent），同样逐条给结果；**验证者不能是实现者（同一把 key → 403）**。全通过 → `verified`，有不通过 → `failed` 且原因写进记录。
- **blocked 的解决**：Core 不路由。需求 Agent 在 `list_work(status=blocked)` 里看到，走正常审核单发布新版本，旧记录自动被取代、新版本产生新的 pending。
- 权限：`exec.read`（看待办 / 记录）、`exec.write`（领取 / 报告 / 提交）、`exec.verify`（验收）。预置 `executor-agent`（读 + exec.write）、`tester-agent`（读 + exec.verify）、`requirements-agent` 也能 `exec.read`。
- 旧的 `ack_block` / `Block.completed*` / `acks` 表已删除，不保留。

### 密钥与身份（已定，覆盖「编码阶段的简化」里单把 key 的部分）

- **同一目录下多个 Agent 协作，key 在 Core 之外互相看得见**，所以不靠 key 保密来隔离角色：key 的作用是**角色权限 + 项目隔离**；Agent 的身份靠各目录（根目录 / `web/` / `backend/` …）的 `AGENTS.md` 里的身份提示词：先弄清自己的职位，看自己的 `AGENTS.md` 里有没有已领取的 key，有就用，**不要重复领取**；没有则问人，人同意后再创建，并把 key 写进自己的 `AGENTS.md`。这部分是**靠自觉**，Core 不强制（只强制验证者 ≠ 实现者按 key 判定）。
- **不预置多把 key**：seed 只发一把 admin key；其余 key 由持有 admin key 的 Agent 经 MCP `create_api_key` 创建。**这是危险操作**（新 key 就是新权力）：只有 admin 能做（`key.manage` 是人类专属权限，受限角色 403）；Agent 绝不能自作主张——必须先告诉人要创建哪个角色、为什么，等到明确同意后才调用，`evidence` 附人同意的原话（不带原话 422，来源与原话写进审计）；`speclock-cli key create` 是兜底。网页不提供创建 key 的操作。
- **新建的 key 立即可用**：服务端创建即生效；MCP 里用 `use_api_key` 在当前会话切换，不用重启客户端（无效的 key 保持原身份）。长期使用则把 key 记进使用它的 Agent 的 `AGENTS.md` / MCP 配置。key 明文不要在对话里复述。
- 注意：能随时切换 key 之后，「验证者 ≠ 实现者」只是按 key 判定的机械规则，同一个 Agent 有意切换就能绕过；真正的独立性靠不同的 Agent 实例和提示词约定（与上面「靠自觉」一致）。
- 已知限制：只有带 `key.manage`（人类专属权限）的 key 能创建 key，所以受限角色的 Agent 自己领不到 key，得由持有 admin key 的 Agent 或人代为创建。

## 6.1 后续路线（未开始）

- Finding 存储：语义扫描 Agent 只能提交发现，不能改文档（`scanner-agent` 目前只读，等 Finding 做出来再给它 `finding.write`；可能要关联到执行记录）。
- （已完成）读取侧的 `get_block_history` / `get_capability_history`：`/blocks/{id}/history`、`/capabilities/{id}/history`，只读、项目隔离、已归档 / 未发布对 Agent 不可见；版本状态 `current` / `deprecated`（派生，不存库）也带在管理端的版本列表里。
- 官方 Agent 脚手架只是最佳实践示范，不属于 Core。

## 7. 开发约定

- 这是 **demo 项目，库里的数据没有实际意义**：不为老数据写兼容逻辑，需要时重新 seed。
- 改动要同步：测试、README、`seed.py`、`inject_ops.py` 与 `.inject_data/*.json`（顶层键为 `business` / `capability` / `modules`）。
- 数据库文件（`*.db`）不要删改，`speclock.db` 是本地在用的库。
- 对外接口有破坏性变化时同步升 `pyproject.toml` 版本（agent 端 wheel 随之更新）。
- 环境：Windows；Python 虚拟环境在 `.venv/`，前端在 `web/`。

```bash
.venv/Scripts/python.exe -m pytest -q          # 后端测试
cd web && npm run build                        # 前端构建（产物 web/dist/，后端同进程托管）
.venv/Scripts/python.exe -m speclock.main      # 启动服务，默认 http://127.0.0.1:8000
```

## 8. 代码地图

- `speclock/api_cr.py`：审核单 + Commit 接口，规格库**唯一写入通道**（状态机、批准、覆盖检查）。
- `speclock/commits.py`：Commit 引擎（ops 原子应用、`$ref`、跨 Block / Capability、整体回滚）。
- `speclock/engine.py`：发布引擎（内部，无对外写接口）：草稿 → 不可变版本、Capability 版本派生、结构完备性校验；seed / inject 也直接调它。
- `speclock/permissions.py`：权限目录、预置角色、`require_permission`。
- `speclock/api_admin.py`：读视图（树 / 版本 / 归档 / 审计）+ 项目 / 密钥 / 角色管理。
- `speclock/api_agent.py`：读规格；不存在任何规格写端点。
- `speclock/cli.py`：`speclock-cli`，人用人类 key 查看 / 批准 / 驳回审核单。
- `speclock/diffing.py`：结构化 API / 规则校验、字段级 delta、版本级别标签、OpenAPI 生成、版本号计算。
- `speclock/api_exec.py` + `speclock/executions.py`：执行接口与执行记录状态机（待办 / 领取 / 阻塞 / 失败 / 提交实现 / 独立验收）。
- `speclock/mcp_server.py`：stdio MCP，27 个工具（含代人批准 / 驳回，必须带哈希与人的原话；执行协议；`create_api_key` 必须带人的原话；`use_api_key` 会话内切换 key），经 HTTP 调用本系统 REST。
- `speclock/models.py`、`schemas.py`、`db.py`（含迁移）。
- `web/`：Vue 3 **只读展示**网页（参考实现，已适配 0.6.0）：文档树、模块 / 版本 / diff（带到审核单的溯源与执行状态）、审核单列表与详情、待办（执行记录与事件）、归档、AI 接入说明。**不提供任何修改操作**，新增页面也不要加；只调用公开 REST 接口，不依赖 Core 内部实现。

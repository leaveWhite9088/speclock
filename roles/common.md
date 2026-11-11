## SpecLock 通用部分（所有 Agent 都要有）

### SpecLock 是什么

SpecLock 是业务规格的唯一信源：保存业务事实（大业务 → 小业务 → 模块，每个模块有背景、规则、
验收条件、API），所有修改都走「审核单 → 人确认 → Commit」。它只做记录，不做判断，自己也不是 Agent。

### 怎么调用它

- **首选 MCP 工具**：工具说明里写了参数和用法，提示也最完整。
- MCP 用不了时（没配置、没连上），可以直接调它的 REST 接口（`/api/v1/...`，请求头 `X-API-Key`），
  或者用 `speclock` 命令。两种方式**规则完全一样**：同一把 key、同样的权限检查，批准、创建 key
  这类操作同样必须有人的原话，该问人的照样先问。
- 不论哪种方式，都**不要碰数据库文件**（`.speclock/speclock.db`），也不要为了"搞懂怎么用"去读它的源码——
  行为不清楚就看工具说明和 `docs/REFERENCE.md`，再不行就问人。

### 先弄清自己的身份

1. 开始工作前先调用 `whoami`（REST：`GET /api/v1/me`），看自己的角色和权限。
2. **角色必须和你这个目录的职责一致**（见下面的「我的 SpecLock 身份」）。不一致就停下来告诉用户，
   不要自己换一把 key 继续做。
3. 「我的 SpecLock 身份」里已经写了 key 文件，说明身份领取过了：**直接用，不要重复创建**。

### 你的 key 放在哪、怎么用

- Agent 的 key 都存成文件，放在 `.speclock/keys/`，**一把一个文件**，文件名是「角色--名称」，里面就是 key。
- 「我的 SpecLock 身份」里写的是**你自己的那个文件名**，不是 key 本身。用法：
  - MCP：配置里用 `--key-file`（`speclock mcp --key-file <文件名>`），或在会话里 `use_api_key(key_file="<文件名>")`；
  - 直接调 REST：读你自己的那个文件，把内容放进请求头 `X-API-Key`。
- **只读你自己的那一个文件。不要打开、列出、复制、使用 `keys/` 里别的文件**——那是别的 Agent 的身份，不是你的职责。
  不要把 key 的内容写进对话、日志、代码或提交里。
- 找不到自己的 key 文件，或者 key 失效了：停下来告诉用户，不要去用别的 key。
- **不要用 `use_api_key(key_file=…)` 去试别的文件名**，也不要在会话里换成别的角色的 key 来做你角色之外的事（比如换成测试 Agent 的 key 去验收自己的实现）：系统拦不住，但这是越权。
- `whoami` 会告诉你这把 key 的来源（`key_source`）。如果来源不是你配置里写的那个 key 文件，说明身份被顶替了：停下来告诉用户。
- **admin key 不属于任何 Agent 的目录**：如果你在项目文件里（`.mcp.json`、AGENTS.md、环境文件）发现了 admin key，**不要用它**，告诉用户把它移走。
  你的身份是你自己的角色 key；需要管理员做的事（批准、创建 key、建项目）告诉用户，由用户或他授权的管理员会话来做。

### 没有 key 时：创建 key 是危险操作

新 key 就是新权力，所以：

- 只有 admin 能创建（`create_api_key`，或 REST `POST /api/v1/keys`、`speclock key create`）。创建前先 `list_api_keys` 看这个角色是不是已经有一把。
  如果你的 key 不是 admin，**不要尝试，告诉用户**，由用户或持有 admin key 的 Agent 来创建。
- **绝不能自作主张**。先告诉用户：要创建哪个角色、为什么，等用户**明确同意**之后才调用，
  `evidence` 填用户同意的原话。
- 创建 Agent 类 key 时，服务端会把它直接存成 `.speclock/keys/` 里的文件，响应里只有**文件名**，没有明文。
  把这个文件名告诉用户，并写进要用它的 Agent 的「我的 SpecLock 身份」；你自己要临时用就 `use_api_key(key_file=...)`，
  用完 `use_api_key`（传空）切回自己的。
- admin / reviewer 这类**人类 key** 不存文件，明文只在创建时出现一次，直接交给用户保管，不要写进任何文件。

### 人的确认

- 没有用户在对话里明确说「同意 / 批准」，**绝不能调用 `approve_change_request`**；
  批准时 `evidence` 必须是用户的原话，`content_hash` 必须是你刚读到的那一版的哈希。
- 驳回同理，必须有用户给的理由。

### 我的 SpecLock 身份（填写）

- 角色：`<requirements-agent | executor-agent | tester-agent | scanner-agent>`
- key 文件：`<.speclock/keys/ 里你自己的那个文件名，如 tester-agent--qa.key；这里只写文件名，不要写 key 本身>`
- 项目：`<project_id>`（Agent 的 key 都绑定了项目，不用在调用里传；只有升级前遗留的老 key 才会是「全局」，那时开审核单要传 `project_id`）

# 使用指南

从安装到让一支 Agent 团队跑起来，按顺序读就行。更细的接口和规则见 [REFERENCE.md](REFERENCE.md)。

- [1. 安装](#1-安装)
- [2. 初始化：两种用法](#2-初始化两种用法)
- [3. 接入 Agent](#3-接入-agent)
- [4. key 都放在哪](#4-key-都放在哪)
- [5. 人怎么批准](#5-人怎么批准)
- [6. 网页](#6-网页)
- [7. 备份与导出](#7-备份与导出)
- [8. 常用命令](#8-常用命令)

## 1. 安装

需要 Python ≥ 3.11 和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone <本仓库> speclock
cd speclock && uv sync                  # 在 .venv/ 里装好全部包（editable）
```

把 `.venv/Scripts`（Linux / macOS 是 `.venv/bin`）加进 PATH，之后就可以直接敲 `speclock`。

## 2. 初始化：两种用法

```bash
cd /你的/项目
speclock init        # 创建 .speclock/，打印 admin key 和下一步
speclock serve       # 启动服务和网页（地址 init 时打印了）
```

`init` 做四件事：创建 `.speclock/`（配置和数据库）、生成一把**随机**的 admin key（只显示这一次，库里只存哈希）、
给网页准备一把只读 key（绑定这个项目）、告诉你下一步。

| | 跟项目走 | 跟电脑走 |
|---|---|---|
| 怎么建 | 在项目根目录 `speclock init` | `speclock init --global` |
| 数据在 | `<项目>/.speclock/` | `~/.speclock/` |
| 端口 | 自动选一个空闲的 | 固定 `47821` |
| 适合 | 每个项目一套规格，数据跟着项目 | 起一个服务，你所有项目都连它 |

SpecLock 源码放哪都行（项目里面，或电脑上任意位置），**数据永远不在源码目录里**。
命令像 git 找 `.git` 那样，从当前目录往上找最近的 `.speclock/`，找不到再用 `~/.speclock/`；环境变量 `SPECLOCK_HOME` 可以直接指定。
数据库默认不进 git（`.speclock/.gitignore` 已处理），`config.toml` 可以提交。

## 3. 接入 Agent

为每个 Agent 创建它**自己的** key（会提示你输入 admin key，不用存进任何文件）：

```bash
speclock key create --role requirements-agent --label 需求
speclock key create --role executor-agent     --label 后端
speclock key create --role tester-agent       --label 测试
speclock key create --role scanner-agent      --label 扫描
```

每条命令都会打印一段**可以直接贴进那个 Agent 的 `.mcp.json` 的配置**：里面只有 key 的文件名，没有 key 本身；
`SPECLOCK_HOME` 写死了，不管客户端从哪个目录启动都能用，两种用法一样。

然后给每个 Agent 一份提示词：把 [`roles/common.md`](../roles/common.md) 和它的角色文件一起放进它目录的 `AGENTS.md`，
填好末尾的「我的 SpecLock 身份」。SpecLock 只强制**权限**；**行为约定**都在这些提示词里。

| 角色 | 做什么 | 提示词 |
|---|---|---|
| 需求 Agent | 理解业务、开审核单、写规格；判断是「业务变更」还是「内部整理」 | [requirements-agent.md](../roles/requirements-agent.md) |
| 执行 Agent | 按锁定版本的规格实现，逐条验收条件给证据 | [executor-agent.md](../roles/executor-agent.md) |
| 测试 Agent | 独立验收，不给「差不多」的通过 | [tester-agent.md](../roles/tester-agent.md) |
| 扫描 Agent | 只读通读规格找问题，写成建议 | [scanner-agent.md](../roles/scanner-agent.md) |

> **admin key 是你自己的钥匙，不要写进项目里的 `.mcp.json`**：同目录的 Agent 读得到，就等于都有了管理员权限，可以自己批准自己的审核单。
> 要让 Claude 之类的客户端以管理员身份代你操作，配在**用户级**的 MCP 配置里，并且只在你自己跟它对话的那个会话里用。

## 4. key 都放在哪

| key | 放在哪 | 丢了怎么办 |
|---|---|---|
| **admin key** | 只在 `init` 时显示一次，由你保管；不放进任何 Agent 读得到的文件 | `speclock init --new-admin` 再发一把 |
| **Agent 的 key**（需求 / 执行 / 测试 / 扫描） | `.speclock/keys/<角色>--<名称>.key`，一把一个，创建时由 SpecLock 直接写，**明文不经过对话** | `speclock key show <id>` 查看；吊销用 `key delete`，文件一并删除 |
| **人类 key**（如 reviewer） | 和 admin 一样，只显示一次，由人保管 | 再建一把 |
| **网页用的只读 key** | `.speclock/web-keys/<项目 id>.key`，每个项目一把、绑定该项目，网页自动使用 | 缺了需要时自动补 |

`keys/README.md` 告诉每个 Agent 只读自己的那个文件。同一个目录里的 Agent 互相看得见文件，这一点靠提示词约束，
所以人类 key 不放在里面：越界读取最多拿到另一个 Agent 的低权限。

## 5. 人怎么批准

规格只能通过「需求 Agent 开审核单 → **人批准** → 需求 Agent 提交 Commit」修改。批准有两种方式，效果一样，都会留下记录：

- **在对话里**：需求 Agent 把审核单用人话讲给你听，你明确说「同意」，持有管理员身份的会话带着你的**原话**和审核单的**内容哈希**代你批准。
- **用命令**：`speclock cr list` / `cr show 1` / `cr approve 1` / `cr reject 1 --reason …`（会提示输入你的 key）。

创建其他角色的 key 也是危险操作：只有 admin 能做，Agent 必须先问你、拿到你的明确同意，原话会写进审计。

只有**改名和搬模块**这两类**内部整理**（不改任何模块的内容，不产生新的模块版本），需求 Agent 可以自己声明 `kind=internal` 并写明理由，不用你批准；网页上会标注「由 Agent 自行判定」。

## 6. 网页

`speclock serve` 之后打开它打印的地址，**不用登录**：网页自动使用一把只读 key，什么都改不了；它绑定了一个项目，所以**一次只看得到一个项目**（有多个项目时先选一个，或在地址后加 `?project=项目id`）。
总览告诉你现在有什么需要关注（等你确认的审核单、卡住的任务、等验收的结果），每页几秒内自动刷新。

网页还能**一键嵌进你自己的前端**：

```html
<script src="http://127.0.0.1:端口/embed.js"></script>
<div data-speclock="overview"></div>
```

详见 [EMBED.md](EMBED.md)。

## 7. 备份与导出

数据库不进 git，所以**请定期备份**。三个本机命令，不走网络、不需要 key：

```bash
speclock backup                 # 完整备份到 .speclock/backups/（含全部历史、审核单、执行记录），灾难恢复用
speclock restore <备份文件>      # 先停掉服务；原来的库会改名留着
speclock export [--out DIR]     # 导出成 Markdown + spec.json：只读快照，不含时间戳，可以提交进 git
```

想让规格进 git、给团队看或对照历史，用 `export`；要还原数据，用 `backup` / `restore`。

## 8. 常用命令

```bash
speclock init [--global] [--new-admin]       # 创建 .speclock/；admin key 丢了再发一把
speclock serve                               # 启动服务和网页
speclock mcp [--key-file 文件名]              # MCP 入口（由 Agent 的 .mcp.json 启动）
speclock backup / restore <文件> / export     # 备份、恢复、导出
speclock project list|create|rename          # 项目
speclock cr list|show|approve|reject         # 审核单
speclock key list|create|show|delete         # 密钥
```

`init` / `serve` / `mcp` 启动时都会打印它用的数据目录和是怎么找到的（当前目录 / 上层目录 / 环境变量 / 电脑级）；如果用的是上层目录的数据，会特别提醒。
`speclock init --new-admin` 只是再发一把，**旧的 admin key 仍然有效**；key 是泄露了就加 `--revoke-old` 一并吊销。

需要 key 的命令（`cr`、`key`、`project`）按这个顺序找 key：`--key` 参数 → 环境变量 `SPECLOCK_KEY` → 在终端里提示输入。

> `SPECLOCK_KEY` 是给**你自己的命令**用的，别在启动 Agent 的 shell 里 export 它。Agent 的 MCP 配了 `--key-file` 时以 key 文件为准，但 Agent 若是用 `SPECLOCK_KEY` 启动的（没配 key 文件），它就会拿到这把 key。

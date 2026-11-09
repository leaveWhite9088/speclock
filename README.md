# SpecLock

**业务规格的单一信源。** 让人和 AI Agent 围绕同一份、带版本、改动可追溯的业务文档协作。

SpecLock 只是一个**记录工具**：它保存业务规格、守住版本和文档的准确，记下谁在什么时候做了什么。
它不做判断，也不是 Agent；谁来写、谁来实现、谁来测，由你的 Agent 通过 MCP 来完成。

- 规格按 **项目 → 大业务 → 小业务 → 模块** 管理，每次改动产生不可变的新版本，带结构化 diff；
- 规格库**只有一条写入通道**：Agent 开审核单 → **人批准** → Agent 提交 Commit；
- 每个模块的版本有**执行记录**：谁认领、实现到哪、是否被另一个 Agent 独立验收；
- 一个只读网页，让人随时看到全貌和 Agent 的动向。

## 快速开始

需要 Python ≥ 3.11。

```bash
git clone <本仓库> speclock
cd speclock && python -m venv .venv
.venv/Scripts/pip install -e .          # Linux / macOS：.venv/bin/pip install -e .
```

然后进入**你自己的项目目录**：

```bash
cd /你的/项目
/路径/到/speclock/.venv/Scripts/speclock init      # 创建 .speclock/，打印 admin key 和 .mcp.json 片段
/路径/到/speclock/.venv/Scripts/speclock serve     # 启动服务和网页（地址 init 时打印了）
```

> 把 `.venv/Scripts`（Linux/macOS 是 `.venv/bin`）加进 PATH，就可以直接敲 `speclock`。

`init` 做四件事：创建 `.speclock/`（配置和数据库）、生成一把**随机**的 admin key（只显示这一次，库里只存哈希）、再生成一把网页用的只读 key、
打印一段 `.mcp.json`——合并进你项目的 `.mcp.json`，Agent 就接上了。网页**不用登录**：打开服务地址就能看，它自动使用一把只读 key（`.speclock/web.key`，不进 git），什么都改不了。admin key 只留给你自己和 Agent，不会出现在网页里；**丢了的话**运行 `speclock init --new-admin` 再发一把。

## 两种用法

| | 跟项目走 | 跟电脑走 |
|---|---|---|
| 怎么建 | 在项目根目录 `speclock init` | `speclock init --global` |
| 数据在 | `<项目>/.speclock/` | `~/.speclock/` |
| 端口 | 自动选一个空闲的 | 固定 `47821` |
| 适合 | 每个项目一套规格，数据跟着项目 | 起一个服务，你所有项目都连它 |

SpecLock 源码放哪都行（项目里面、或电脑上任意位置），**数据永远不在源码目录里**。
命令会像 git 找 `.git` 那样，从当前目录往上找最近的 `.speclock/`，找不到再用 `~/.speclock/`。
数据库默认不进 git（`.speclock/.gitignore` 已处理），`config.toml` 可以提交。

## 让 Agent 干活：角色和提示词

SpecLock 只强制**权限**（谁能调用什么接口、验收者不能是实现者）；**行为约定**写在提示词里。
[`roles/`](roles/) 是我们推荐的一套，复制到各目录的 `AGENTS.md` 即用：

| 角色 | 做什么 |
|---|---|
| 需求 Agent | 理解业务、开审核单、写规格；自己判断是「业务变更」还是「内部整理」 |
| 执行 Agent | 按锁定版本的规格实现，逐条验收条件给证据 |
| 测试 Agent | 独立验收，不给「差不多」的通过 |
| 扫描 Agent | 只读通读规格找问题，写成建议 |

人的批准：Agent 把审核单讲给你听，你在对话里明确同意，Agent 带着你的原话和内容哈希调用批准；
也可以自己用命令：`speclock cr list` / `cr show 1` / `cr approve 1` / `cr reject 1 --reason …`。
创建其他角色的 key 是危险操作，只有 admin 能做，且 Agent 必须先问你、拿到你的明确同意。

## key 都放在哪

- **admin key**：`init` 时只显示一次，请自己保管（`.mcp.json` 里会有一份给你的 Agent 用）。
- **Agent 的 key**（需求 / 执行 / 测试 / 扫描）：创建时由 SpecLock 直接存成 `.speclock/keys/` 里的文件，一把一个，文件名是「角色--名称」，
  **明文不经过对话**。`keys/README.md` 告诉 Agent 只读自己的那个；你可以用 `speclock key show <id>` 查看，吊销时文件一并删除。
  Agent 的配置里只写**文件名**，比如 `speclock mcp --key-file tester-agent--qa.key`。
- **网页用的只读 key**：`.speclock/web.key`，自动使用。

## 常用命令

```bash
speclock init [--global]      # 创建 .speclock/（--new-admin：admin key 丢了再发一把）
speclock serve                # 启动服务和网页
speclock mcp                  # MCP 入口（Agent 用，由 .mcp.json 启动）
speclock cr list|show|approve|reject    # 审核单
speclock key list|create|show|delete    # 密钥（Agent 的 key 存成 .speclock/keys/ 里的文件）
```

## 更多

- [完整特性、接口与规则](docs/REFERENCE.md)
- [开发指南与设计决策](docs/DEVELOPMENT.md)
- [版本记录](docs/CHANGELOG.md)

MIT License

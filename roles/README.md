# 推荐的角色提示词

SpecLock 的 Core 只管记录和守住规格的准确，**不做任何判断**。谁该做什么、遇到什么情况怎么办，
靠各个 Agent 自己的提示词。这个目录就是我们推荐的一套，复制即用。

## 怎么用

1. 每个 Agent 所在的目录里放一份 `AGENTS.md`（或你的客户端认的提示词文件）。
2. 把 [`common.md`](common.md) 和该 Agent 对应的角色文件**一起**复制进去：

| 角色 | 文件 | 做什么 |
|---|---|---|
| 需求 Agent | [`requirements-agent.md`](requirements-agent.md) | 理解业务、开审核单、写规格；判断「业务变更」还是「内部整理」 |
| 执行 Agent | [`executor-agent.md`](executor-agent.md) | 按锁定版本的规格实现，逐条给证据 |
| 测试 Agent | [`tester-agent.md`](tester-agent.md) | 独立验收，不给「差不多」的通过 |
| 扫描 Agent | [`scanner-agent.md`](scanner-agent.md) | 只读通读规格找问题，写成建议 |

3. 填好 `common.md` 末尾的「我的 SpecLock 身份」（角色、**key 文件名**、项目）。key 本身存在 `.speclock/keys/` 里，不写进这个文件。

## 边界

- 角色对应的**权限**由 SpecLock 强制（`GET /api/v1/roles` 可看）；**行为约定**只在这些提示词里。
- Agent 之间怎么沟通（比如扫描 Agent 的建议怎么交给需求 Agent）、谁来定时叫醒谁，
  是外面的调度脚手架的事，不是 SpecLock 的事。提示词里只写「把建议写清楚」，不假设有谁来转发。

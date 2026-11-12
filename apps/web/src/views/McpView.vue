<script setup>
// AI 接入：SpecLock MCP（stdio）的接入说明与 agent 活动。
import { computed, onMounted, ref } from 'vue'
import { resources } from '../api/resources.js'
import { errText } from '../errors.js'
import { useKeyNames } from '../api/keyNames.js'
import { fmtTime } from '../time.js'

// 与后端 mcp_server.py 的工具保持一致的一句话说明
const TOOLS = [
  ['whoami', '当前 key 的角色与权限'],
  ['get_index', '大业务→小业务→模块 三层索引树，模块节点带当前版本的执行状态'],
  ['get_block', '读取一个模块的已发布版本（背景 / 规则 / 验收条件 / API，规则与验收条件带稳定 id），可 pin 版本；响应带 cr_id / commit_id 溯源'],
  ['get_capability', '读取小业务 manifest（模块→版本清单），可 pin 历史小业务版本'],
  ['get_diff', '两个已发布版本之间的结构化 + 文本 diff，带机械算出的 level 标签'],
  ['get_block_history', '模块的版本历史（从旧到新）：级别标签、变更说明、delta、产生它的审核单 / Commit、状态'],
  ['get_capability_history', '小业务的版本历史：每个版本的 manifest、由哪个模块触发、审核单 / Commit、状态'],
  ['list_projects', '看得到的项目 id 与名称（全局 key 开审核单、建 key 绑项目时要用）'],
  ['get_activity', '审计日志：谁在什么时候对什么做了什么，可筛选、可翻页（需要 audit.read）'],
  ['create_project', '创建项目（仅 admin，先问人）'],
  ['rename_project', '项目改名（仅 admin，先问人）'],
  ['delete_block', '删除模块（不可恢复）：须有人批准、点名它的审核单（cr_id）；已发布的要先归档'],
  ['delete_capability', '删除小业务（连同其下模块，不可恢复）：同样须审核单授权'],
  ['delete_business', '删除大业务（连同其下全部内容，不可恢复）：同样须审核单授权'],
  ['delete_project', '删除整个项目（含审核单和绑定的 key，不可恢复）：仅超级管理员，须审核单授权'],
  ['list_work', '待办列表：按状态筛选（待领取 / 进行中 / 被阻塞 / 失败 / 待验收 / 已验收）'],
  ['get_work', '一条执行记录：事件历史、已提交的结果、锁定到该版本的完整规格'],
  ['claim_work', '领取任务（执行 Agent）：返回锁定版本的完整规格；失败 / 被阻塞的可重新领取'],
  ['release_work', '放弃自己领取的任务，回到待领取'],
  ['report_blocked', '业务上卡住：规格缺信息或自相矛盾，写明问题，由需求 Agent 经审核单解决'],
  ['report_failed', '没做成：写明原因，之后可重新领取'],
  ['submit_implementation', '提交实现结果：逐条验收条件给 pass + 证据，全部通过才能提交'],
  ['verify_work', '独立验收（测试 Agent）：逐条验收条件给结果；验证者不能是实现者'],
  ['create_api_key', '危险操作（仅 admin）：为 Agent 角色创建 key，必须先问人并等到明确同意，附人的原话；明文只返回一次，创建后立即可用'],
  ['list_api_keys', '列出密钥（带最近活动，不含明文）：创建新 key 之前先看一眼是否已有'],
  ['revoke_api_key', '吊销密钥（不可恢复）：必须先问人并附原话；最后一把管理员 key 删不掉'],
  ['use_api_key', '在当前会话切换使用的 key（如刚创建的那把），不用重启客户端；传空切回配置里的'],
  ['list_change_requests', '列出审核单，可按状态过滤'],
  ['get_change_request', '读取审核单：状态、验收条件覆盖情况、人的决定、全部 Commit'],
  ['create_change_request', '创建审核单草稿：只写业务意图（为什么变 / 变成什么样 / 不再成立的旧认知 / 验收条件 / 影响说明）；kind=internal 表示不改业务内容的内部整理，Agent 自行判定、提交即生效，须写理由'],
  ['update_change_request', '编辑草稿审核单'],
  ['submit_change_request', '提交审核单给人确认（内容冻结并生成内容哈希）'],
  ['withdraw_change_request', '把待审核的审核单撤回成草稿'],
  ['approve_change_request', '代人批准：必须带人看过的 content_hash 和人的原话 evidence'],
  ['reject_change_request', '代人驳回：必须写理由'],
  ['submit_commit', '在已批准的审核单下写规格库：一组原子 ops，成功即发布（支持 dry_run 预览）'],
  ['complete_change_request', '报告审核单已落地；每条验收条件必须被某个 Commit 覆盖'],
]

const RULES = [
  '先调用 get_index 拿三层索引树，选中目标模块后用 get_block 拉取，不要逐个全量拉取。',
  '规格库只有一条写入通道：create_change_request → 把内容讲给人听 → 人明确同意后 approve_change_request（带人的原话）→ submit_commit → complete_change_request。没有任何直接改模块的工具。',
  '审核单只写业务意图，不要写“改哪个模块”；拆成哪些模块、哪些 ops 是你在 Commit 里自己决定的。',
  '没有人在对话里的明确同意，不得调用 approve_change_request；evidence 必须是人的原话。',
  '规则和验收条件按稳定 id（R-n / AC-n）定位；Commit 里用 covers 声明本次满足了审核单的哪些验收条件。',
  '提交 Commit 前可先 dry_run 预览版本号和级别标签；任何一条 op 失败整个 Commit 回滚。',
  '执行 Agent：list_work 找到待领取项 → claim_work（拿到锁定版本的规格）→ 实现 → submit_implementation，逐条验收条件附证据。业务上卡住用 report_blocked，别猜。',
  '测试 Agent：list_work(status=implemented) → get_work 看实现方的证据 → 自己测 → verify_work 逐条给结果；不能验收自己实现的。',
  '启动时先 whoami 弄清自己的角色，并检查自己目录的 AGENTS.md 是否已有 key，不要重复创建；创建 key 是危险操作，只有 admin 能做：先告诉人要建哪个角色、为什么，等到明确同意再 create_api_key，建好后用 use_api_key 直接切换使用。',
  '只能读到已发布版本；归档内容不可见。',
]

// 只放 key 文件名，不放 key 本身；admin key 不进任何 Agent 的配置。
// 最准确的版本由 `speclock key create` 直接打印（含 Python 绝对路径和 SPECLOCK_HOME）。
const configJson = computed(() =>
  JSON.stringify(
    {
      mcpServers: {
        speclock: {
          command: 'speclock',
          args: ['mcp', '--key-file', '<你的 key 文件名，如 tester-agent--qa.key>'],
          env: {
            SPECLOCK_HOME: '<.speclock 目录的绝对路径>',
          },
        },
      },
    },
    null,
    2,
  ),
)

const brief = computed(
  () =>
    `# SpecLock · AI 接入说明

你是一名 AI agent。SpecLock 是本项目的业务规格单一事实源：所有业务规格在这里维护并版本化。你通过它的 MCP server 以 stdio 方式接入：读取已发布版本的规格（支持版本 pin 锁定快照），并通过「审核单 → 人确认 → Commit」这一条通道修改规格。

请按以下步骤自行完成接入。

## 1. 确认 speclock 命令可用

SpecLock 装在这台电脑上（\`pip install -e .\` 之后有 \`speclock\` 命令）。\`speclock mcp\` 即为可启动的 MCP server（stdio 方式）；服务本身用 \`speclock serve\` 启动。

## 2. 写入 MCP 配置

你需要一把**你自己角色**的 key。它由用户用 \`speclock key create --role <你的角色>\` 创建，创建时会打印一段现成的配置（填好了 key 文件名和 \`SPECLOCK_HOME\`）——向用户要这段配置。形状如下，合并到你所在目录的 \`.mcp.json\`（若已有 \`mcpServers\`，只合并其中 \`speclock\` 一项），然后重启客户端。配置里只有 key 的**文件名**，不要把 key 本身写进去；**不要使用 admin key**。

\`\`\`json
${configJson.value}
\`\`\`

## 3. 你可用的工具（${TOOLS.length} 个）

${TOOLS.map(([name, desc]) => `- \`${name}\`：${desc}`).join('\n')}

## 4. 使用规则

${RULES.map((r) => `- ${r.replace(/(\w[\w_]*)/g, (m) => (TOOLS.some(([t]) => t === m) ? `\`${m}\`` : m))}`).join('\n')}
`,
)

const { keyName } = useKeyNames()
const activities = ref([])
const agentHint = ref('')
const loading = ref(true)
const error = ref('')
const copyState = ref('') // 'install' | 'config' | 'brief' 最近复制了哪个
const copied = ref(false)

async function copyText(text, which) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copyState.value = which
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    activities.value = await resources.activity({ limit: 50 })
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page mcp-page">
    <h1 class="page-title">AI 接入</h1>

    <div class="intro-card">
      <button type="button" class="btn btn-primary" @click="copyText(brief, 'brief')">
        {{ copied && copyState === 'brief' ? '已复制 ✓' : '复制接入说明' }}
      </button>
    </div>

    <!-- 第 1 步：MCP 配置 -->
    <section class="section">
      <h2 class="section-title">第 1 步：写入 MCP 配置</h2>
      <div class="card section-card">
        <p class="step-text">
          合并进项目根目录的 <code>.mcp.json</code>，重启客户端。每个 Agent 用自己的 key：
          <code>speclock key create --role requirements-agent --label 需求 --project 1</code> 会直接打印这段配置。
          <strong>admin key 不要写进 <code>.mcp.json</code></strong>。
        </p>
        <pre class="config-pre mono">{{ configJson }}</pre>
        <button type="button" class="btn" @click="copyText(configJson, 'config')">
          {{ copied && copyState === 'config' ? '已复制到剪贴板 ✓' : '复制配置' }}
        </button>
      </div>
    </section>

    <!-- 第 2 步：工具清单 -->
    <section class="section">
      <h2 class="section-title">第 2 步：AI 可用工具清单（{{ TOOLS.length }} 个）</h2>
      <div class="card section-card table-wrap">
        <table class="tool-table">
          <thead>
            <tr><th>工具</th><th>说明</th></tr>
          </thead>
          <tbody>
            <tr v-for="[name, desc] in TOOLS" :key="name">
              <td class="mono tool-name">{{ name }}</td>
              <td>{{ desc }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 第 3 步：使用规则 -->
    <section class="section">
      <h2 class="section-title">第 3 步：使用规则</h2>
      <div class="card section-card">
        <ul class="rule-list">
          <li v-for="(r, i) in RULES" :key="i">{{ r }}</li>
        </ul>
      </div>
    </section>

    <!-- AI 最近活动 -->
    <section class="section">
      <h2 class="section-title">AI 最近活动<template v-if="activities.length">（{{ activities.length }} 条）</template></h2>

      <p v-if="loading" class="muted">加载中…</p>

      <div v-else-if="error" class="card section-card state-inner">
        <p class="error-text">{{ error }}</p>
        <button type="button" class="btn" @click="load">重试</button>
      </div>

      <div v-else-if="!activities.length" class="card section-card">
        <p class="muted">暂无</p>
      </div>

      <div v-else class="card section-card table-wrap">
        <table class="act-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>动作</th>
              <th>目标</th>
              <th>Key</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in activities" :key="a.id">
              <td class="muted time-cell">{{ fmtTime(a.created_at) }}</td>
              <td><span class="action-badge mono">{{ a.action }}</span></td>
              <td class="mono target-cell">{{ a.target }}</td>
              <td class="mono muted key-cell" :title="a.actor">{{ keyName(a.actor) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.mcp-page {
  max-width: 860px;
}

.section {
  margin-top: var(--sp-6);
}

.section-title {
  font-size: var(--text-lg);
  font-weight: 600;
  margin-bottom: var(--sp-3);
}

.section-card {
  padding: var(--sp-4) var(--sp-5);
}

.state-inner {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.intro-card {
  margin-top: var(--sp-5);
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  flex-wrap: wrap;
}

.intro-hint {
  font-size: var(--text-xs);
}

.step-text {
  font-size: var(--text-sm);
  margin-bottom: var(--sp-2);
}

.step-text code {
  font-size: var(--text-xs);
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  padding: 0 var(--sp-1);
}

.config-pre {
  margin: var(--sp-3) 0;
  padding: var(--sp-3) var(--sp-4);
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  font-size: var(--text-xs);
  line-height: 1.7;
  overflow-x: auto;
}

.table-wrap {
  overflow-x: auto;
}

.tool-table,
.act-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.tool-table th,
.act-table th {
  text-align: left;
  font-weight: 500;
  font-size: var(--text-xs);
  color: var(--ink-2);
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--hairline);
  white-space: nowrap;
}

.tool-table td,
.act-table td {
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--hairline);
  vertical-align: top;
}

.tool-table tbody tr:last-child td,
.act-table tbody tr:last-child td {
  border-bottom: none;
}

.tool-name {
  white-space: nowrap;
  font-weight: 500;
}

.rule-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  font-size: var(--text-sm);
}

.rule-list li {
  padding-left: var(--sp-4);
  position: relative;
}

.rule-list li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.62em;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--contract);
}

.action-badge {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--paper);
  white-space: nowrap;
}

.target-cell {
  font-size: var(--text-xs);
  word-break: break-all;
}

.key-cell,
.time-cell {
  font-size: var(--text-xs);
  white-space: nowrap;
}
</style>

<script setup>
// AI 接入：Tab 切换 ——「接口契约 MCP」（文档树，MCP stdio）/「会议记录分享」
//（哈希码只读链接，面板组件 AiMeetingsView）。tab 状态放在 route query
//（/mcp?tab=meetings），可分享直达。
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client.js'
import AiMeetingsView from './AiMeetingsView.vue'

const route = useRoute()
const router = useRouter()

const tab = computed(() => (route.query.tab === 'meetings' ? 'meetings' : 'mcp'))

function setTab(t) {
  router.replace({ query: { ...route.query, tab: t === 'mcp' ? undefined : t } })
}

// 与后端 ui.py 的 MCP_TOOLS 保持一致的一句话说明
const TOOLS = [
  ['get_index', '大业务→小业务→模块 三层索引树，模块节点带 completed 完成标记（先取索引树选块，再按需拉块；迭代时只做 completed=false 的模块）'],
  ['get_block', '读取一个模块的已发布版本，可 pin 版本号锁定快照'],
  ['get_document', '读取文档 manifest（模块→版本清单），可 pin 历史文档版本回放快照'],
  ['get_diff', '两个已发布版本之间的结构化 + 文本 diff'],
  ['ack_block', '回执：声明「已按 模块@版本 实现」'],
  ['submit_proposal', '提交变更提案——AI 唯一的写出口，需人审批发布后才生效'],
  ['get_proposal', '轮询提案状态（submitted / published / rejected）'],
]

const RULES = [
  '先调用 get_index 拿 大业务→小业务→模块 的三层索引树，在树里选中目标模块后用 get_block 拉取，不要逐个全量拉取。',
  '索引树每个模块节点都带 completed 完成标记：迭代时只做 completed=false 的模块（也可用 get_index(incomplete_only=true) 直接过滤），不要重做已完成模块。',
  '实现前用 get_document / get_block 的版本参数 pin 住快照；实现完成后调用 ack_block 回执「已按 模块@版本 实现」。',
  '只能读到已发布版本；草稿与已归档内容不可见。',
  '没有任何修改文档的工具。发现文档有误或缺失时，用 submit_proposal 提交变更提案（唯一的写出口），经人审批发布后才生效；用 get_proposal 轮询提案状态。',
  '需要对比两个版本时调用 get_diff，按结构化 diff 增量调整实现。',
]

const KEY_PLACEHOLDER = 'agent-…（到「密钥管理」新建 agent key 后填入）'

const configJson = computed(() =>
  JSON.stringify(
    {
      mcpServers: {
        speclock: {
          command: 'python',
          args: ['-m', 'speclock.mcp_server'],
          env: {
            SPECLOCK_URL: window.location.origin,
            SPECLOCK_KEY: KEY_PLACEHOLDER,
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

你是一名开发 AI agent。SpecLock 是本项目的业务文档单一事实源：所有业务文档在这里维护并版本化。你将通过它的 MCP server 以 stdio 方式接入，只读获取已发布版本的文档（支持版本 pin 锁定快照）。你没有任何修改文档的工具；发现文档有误时通过提案通道提交建议，经人审批发布后才生效。

请按以下步骤自行完成接入。

## 1. 写入 MCP 配置

把下面的 JSON 合并到项目根目录的 \`.mcp.json\`（若已有 \`mcpServers\` 字段，只合并其中 \`speclock\` 一项），然后重启你的客户端使配置生效。MCP server 以 stdio 方式启动。

\`\`\`json
${configJson.value}
\`\`\`

## 2. 你可用的工具（${TOOLS.length} 个）

${TOOLS.map(([name, desc]) => `- \`${name}\`：${desc}`).join('\n')}

## 3. 使用规则

${RULES.map((r) => `- ${r.replace(/(\w[\w_]*)/g, (m) => (TOOLS.some(([t]) => t === m) ? `\`${m}\`` : m))}`).join('\n')}
`,
)

const activities = ref([])
const agentHint = ref('')
const loading = ref(true)
const error = ref('')
const copyState = ref('') // 'config' | 'brief' 最近复制了哪个
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

function fmtTime(iso) {
  return iso ? String(iso).replace('T', ' ').slice(0, 19) : '-'
}

function errText(e) {
  const d = e?.detail ?? e
  return typeof d === 'string' ? d : JSON.stringify(d, null, 2)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    ;[activities.value] = await Promise.all([
      api.get('/activity?limit=50&actor_prefix=agent'),
      // 顺带查已有 agent key，给配置占位一个参照
      api
        .get('/keys')
        .then((ks) => {
          const agent = ks.find((k) => k.prefix === 'agent')
          if (agent) agentHint.value = agent.hint
        })
        .catch(() => {}),
    ])
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
    <p class="page-eyebrow">AI Access</p>
    <h1 class="page-title">AI 接入</h1>

    <div class="tab-bar" role="tablist">
      <button
        type="button"
        class="tab"
        :class="{ 'is-active': tab === 'mcp' }"
        role="tab"
        :aria-selected="tab === 'mcp'"
        @click="setTab('mcp')"
      >
        接口契约 MCP
      </button>
      <button
        type="button"
        class="tab"
        :class="{ 'is-active': tab === 'meetings' }"
        role="tab"
        :aria-selected="tab === 'meetings'"
        @click="setTab('meetings')"
      >
        会议记录分享
      </button>
    </div>

    <template v-if="tab === 'mcp'">
    <p class="page-desc">
      本页面向开发 agent。点「复制接入说明」得到一份完整的 Markdown 接入指南，直接发给 agent，它会自行完成配置。
    </p>

    <div class="card intro-card">
      <button type="button" class="btn btn-primary" @click="copyText(brief, 'brief')">
        {{ copied && copyState === 'brief' ? '已复制到剪贴板 ✓' : '复制接入说明' }}
      </button>
      <span class="muted intro-hint">
        说明包含：接入方式、MCP 配置、{{ TOOLS.length }} 个工具清单、使用规则。
      </span>
    </div>

    <!-- 第 1 步：MCP 配置 -->
    <section class="section">
      <h2 class="section-title">第 1 步：写入 MCP 配置</h2>
      <div class="card section-card">
        <p class="step-text">
          把下面 JSON 合并到项目根目录的 <code>.mcp.json</code>（若已有
          <code>mcpServers</code> 字段，只合并其中 <code>speclock</code> 一项），然后重启客户端。
          MCP server 以 stdio 启动：<code>python -m speclock.mcp_server</code>。
        </p>
        <p class="step-text">
          把 <code>SPECLOCK_KEY</code> 替换为你的 agent key——到
          <RouterLink to="/keys">密钥管理</RouterLink> 页新建（仅此一次可见，系统只存哈希，丢失只能重新生成）<template v-if="agentHint">；当前已有一把 agent key：<code>{{ agentHint }}</code></template>。
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
        <p class="muted">
          暂无 AI 活动记录。AI 通过 MCP 或 REST 读取/提案后，这里会显示它读了什么。
        </p>
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
              <td class="mono muted key-cell">{{ a.actor }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    </template>

    <AiMeetingsView v-else />
  </div>
</template>

<style scoped>
.mcp-page {
  max-width: 860px;
}

.tab-bar {
  display: flex;
  gap: var(--sp-1);
  margin-top: var(--sp-4);
  border-bottom: 1px solid var(--hairline);
}

.tab {
  appearance: none;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 7px var(--sp-3);
  font: inherit;
  font-size: var(--text-sm);
  color: var(--ink-2);
  cursor: pointer;
  transition:
    color var(--dur) var(--ease),
    border-color var(--dur) var(--ease);
}

.tab:hover {
  color: var(--ink);
}

.tab.is-active {
  color: var(--contract);
  border-bottom-color: var(--contract);
  font-weight: 500;
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

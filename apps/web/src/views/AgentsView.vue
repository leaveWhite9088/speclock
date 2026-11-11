<script setup>
/**
 * AgentsView（/agents）—— Agent 与密钥（只读）：现在系统里有哪些钥匙、各是什么角色、
 * 手里有什么权力、最近有没有在用；以及角色 × 权限矩阵。创建 / 删除密钥不在这里：
 * 创建密钥是危险操作，由人用 CLI，或在人同意后由持有 admin key 的 Agent 经 MCP 完成。
 * 需要 key.manage 权限才能看。
 */
import { computed } from 'vue'
import { keyHint } from '../api/client.js'
import { resources } from '../api/resources.js'
import { useAsync } from '../composables/useAsync.js'
import { describeKeys, keySummary, permissionMatrix } from '../agents.js'
import PageHeader from '../components/PageHeader.vue'
import AsyncState from '../components/AsyncState.vue'
import TimeAgo from '../components/TimeAgo.vue'
import { useAutoRefresh } from '../composables/useAutoRefresh.js'

const { data, loading, error, reload } = useAsync(async () => {
  const [keys, roles, permissions, projects] = await Promise.all([
    resources.keys(),
    resources.roles(),
    resources.permissions(),
    resources.projects().catch(() => []),
  ])
  return { keys, roles, permissions, projects }
})

useAutoRefresh(reload)
const rows = computed(() => (data.value ? describeKeys({ ...data.value, me: keyHint() }) : []))
const matrix = computed(() => (data.value ? permissionMatrix(data.value) : { roles: [], rows: [] }))
const summary = computed(() => (data.value ? keySummary(rows.value) : ''))
</script>

<template>
  <div class="page agents-page">
    <PageHeader
      eyebrow="Agents"
      title="Agent 与密钥"
      desc="谁手里有 SpecLock 的钥匙、各自能做什么、最近有没有在用。这里只做展示；创建密钥是危险操作，要你明确同意。"
    />

    <AsyncState
      :loading="loading"
      :error="error"
      :empty="!rows.length"
      empty-title="还没有任何密钥"
      empty-text="用 speclock-cli key create 创建一把，或让持有 admin key 的 Agent 在你同意后创建。"
      @retry="reload"
    >
      <p class="summary">{{ summary }}</p>

      <section class="section">
        <h2 class="section-title">密钥</h2>
        <div class="card table-card">
          <table class="keys">
            <thead>
              <tr>
                <th>名称</th>
                <th>角色</th>
                <th>范围</th>
                <th>手里的权力</th>
                <th>最近活动</th>
                <th>近 7 天</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in rows" :key="r.id" :class="{ strong: r.strongPower }">
                <td>
                  <span class="name">{{ r.label || '（未命名）' }}<span v-if="r.isMe" class="me">网页在用</span></span>
                  <span class="hint mono muted">{{ r.hint }}</span>
                  <span v-if="r.keyFile" class="hint mono muted" title="key 保存在 .speclock/keys/ 里（网页看不到内容）">文件：{{ r.keyFile }}</span>
                  <span v-else-if="r.kind === '人'" class="hint muted">人类 key，由本人保管</span>
                </td>
                <td>
                  <span class="mono">{{ r.role || '—' }}</span>
                  <span class="kind muted">{{ r.kind }}</span>
                </td>
                <td>{{ r.project }}</td>
                <td>
                  <span v-for="t in r.power" :key="t.perm" class="power" :class="{ strong: t.strong }">{{ t.text }}</span>
                  <span v-if="!r.power.length" class="muted">—</span>
                </td>
                <td>
                  <span v-if="r.neverUsed" class="never">从未使用</span>
                  <TimeAgo v-else-if="r.lastActiveAt" :value="r.lastActiveAt" />
                  <span v-else class="muted">—</span>
                </td>
                <td class="muted num">
                  <template v-if="r.actions7d || r.reads7d">{{ r.actions7d }} 个动作<br />{{ r.reads7d }} 次读取</template>
                  <template v-else>—</template>
                </td>
                <td>
                  <RouterLink :to="`/activity?actor=${encodeURIComponent(r.hint)}`">查看活动</RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="section">
        <h2 class="section-title">角色与权限</h2>
        <p class="muted small">
          每个角色是一组权限。「人类专属」的权限（批准审核单、管理密钥、管理项目）不能给 Agent 类角色。
        </p>
        <div class="card table-card">
          <table class="matrix">
            <thead>
              <tr>
                <th>权限</th>
                <th v-for="role in matrix.roles" :key="role.name" class="role-col">
                  <span class="mono">{{ role.name }}</span>
                  <span class="muted small">{{ role.kind === 'human' ? '人' : 'Agent' }} · {{ role.keyCount }} 把</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in matrix.rows" :key="row.name">
                <td>
                  <span class="mono">{{ row.name }}</span>
                  <span v-if="row.humanOnly" class="human-only">人类专属</span>
                  <span class="muted small desc">{{ row.description }}</span>
                </td>
                <td v-for="(has, i) in row.cells" :key="i" class="cell">
                  <span v-if="has" class="yes" aria-label="有">✓</span>
                  <span v-else class="no muted" aria-label="没有">·</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </AsyncState>
  </div>
</template>

<style scoped>
.agents-page {
  max-width: 1100px;
}

.summary {
  margin-top: var(--sp-4);
  font-size: var(--text-md);
}

.section {
  margin-top: var(--sp-6);
}

.section-title {
  font-size: var(--text-md);
  font-weight: 600;
  margin-bottom: var(--sp-2);
}

.small {
  font-size: var(--text-xs);
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

th {
  text-align: left;
  font-weight: 500;
  color: var(--ink-2);
  font-size: var(--text-xs);
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--hairline);
  vertical-align: bottom;
}

td {
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--hairline);
  vertical-align: top;
}

tr:last-child td {
  border-bottom: none;
}

.name {
  display: block;
  font-weight: 500;
}

.hint {
  font-size: var(--text-xs);
}

.kind {
  margin-left: var(--sp-2);
  font-size: var(--text-xs);
}

.power {
  display: inline-block;
  margin: 0 var(--sp-1) var(--sp-1) 0;
  padding: 0 var(--sp-2);
  font-size: var(--text-xs);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--paper);
  color: var(--ink-2);
  white-space: nowrap;
}

.power.strong {
  border-color: var(--warning);
  background: color-mix(in srgb, var(--warning) 8%, var(--card));
  color: var(--warning);
}

tr.strong td:first-child {
  box-shadow: inset 3px 0 0 var(--warning);
}

.me {
  margin-left: var(--sp-2);
  padding: 0 var(--sp-2);
  font-size: var(--text-xs);
  font-weight: 400;
  border: 1px solid var(--contract);
  border-radius: var(--radius-sm);
  color: var(--contract);
}

.never {
  color: var(--warning);
}

.num {
  font-size: var(--text-xs);
  line-height: 1.5;
}

.role-col {
  text-align: center;
  white-space: nowrap;
}

.role-col span {
  display: block;
}

.cell {
  text-align: center;
}

.yes {
  color: var(--success);
  font-weight: 700;
}

.human-only {
  margin-left: var(--sp-2);
  padding: 0 var(--sp-2);
  font-size: var(--text-xs);
  border: 1px solid var(--warning);
  border-radius: var(--radius-sm);
  color: var(--warning);
}

.desc {
  display: block;
}
</style>

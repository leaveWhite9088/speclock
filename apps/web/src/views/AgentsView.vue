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
    <PageHeader title="Agent 与密钥">
      <p v-if="summary" class="summary">{{ summary }}</p>
    </PageHeader>

    <AsyncState :loading="loading" :error="error" :empty="!rows.length" empty-title="还没有任何密钥" @retry="reload">
      <ul class="list keys">
        <li v-for="r in rows" :key="r.id" class="key" :class="{ strong: r.strongPower }">
          <span class="dot" :class="r.neverUsed ? 'is-warn' : r.lastActiveAt ? 'is-accent' : ''"></span>
          <div class="key-main">
            <div class="key-head">
              <span class="key-name">{{ r.label || '（未命名）' }}</span>
              <span v-if="r.isMe" class="me">网页</span>
              <span class="role mono">{{ r.role || '—' }}</span>
            </div>
            <div class="key-sub">
              <span>{{ r.project }}</span>
              <span class="mono">{{ r.hint }}</span>
            </div>
            <p v-if="r.power.length" class="powers">
              <span v-for="t in r.power" :key="t.perm" class="power" :class="{ strong: t.strong }">{{ t.text }}</span>
            </p>
          </div>
          <div class="key-side">
            <span v-if="r.neverUsed" class="never">从未使用</span>
            <TimeAgo v-else-if="r.lastActiveAt" :value="r.lastActiveAt" />
            <span v-if="r.actions7d || r.reads7d" class="muted counts">{{ r.actions7d }} 动作 · {{ r.reads7d }} 读取</span>
            <RouterLink :to="`/activity?actor=${encodeURIComponent(r.hint)}`">活动</RouterLink>
          </div>
        </li>
      </ul>

      <details class="fold matrix-fold">
        <summary>角色与权限</summary>
        <div class="matrix-wrap">
          <table class="matrix">
            <thead>
              <tr>
                <th class="perm-col">权限</th>
                <th v-for="role in matrix.roles" :key="role.name" class="role-col">
                  <span class="mono">{{ role.name }}</span>
                  <span class="muted small">{{ role.keyCount }} 把</span>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in matrix.rows" :key="row.name">
                <td class="perm-col">
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
      </details>
    </AsyncState>
  </div>
</template>

<style scoped>
.summary {
  margin-top: var(--sp-1);
  color: var(--ink-2);
}

/* 每把密钥一行：状态点 · 名称 / 角色 / 范围 / 权力 · 右边最近活动 */
.keys {
  margin-top: var(--sp-5);
}

.key {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-1);
}

.key .dot {
  align-self: flex-start;
  margin-top: 9px;
}

.key-main {
  flex: 1;
  min-width: 0;
}

.key-head {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-2);
}

.key-name {
  font-weight: 600;
}

.role {
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.me {
  padding: 0 var(--sp-2);
  font-size: var(--text-xs);
  border-radius: 999px;
  background: var(--contract-wash);
  color: var(--contract);
}

.key-sub {
  display: flex;
  flex-wrap: wrap;
  gap: 0 var(--sp-3);
  font-size: var(--text-sm);
  color: var(--ink-2);
}

.key-sub .mono {
  font-size: var(--text-xs);
}

.powers {
  margin-top: var(--sp-1);
  font-size: var(--text-xs);
  line-height: 1.7;
  color: var(--ink-2);
}

.power:not(:last-child)::after {
  content: ' · ';
}

.power.strong {
  color: var(--warning);
}

.key.strong .key-name::after {
  content: '';
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-left: var(--sp-2);
  border-radius: 50%;
  background: var(--warning);
  vertical-align: middle;
}

.key-side {
  flex: none;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  font-size: var(--text-sm);
  white-space: nowrap;
}

.counts {
  font-size: var(--text-xs);
}

.never {
  color: var(--warning);
}

/* 窄屏：右侧信息放到名称下面一整行 */
@media (max-width: 560px) {
  .key {
    flex-wrap: wrap;
  }

  .key-main {
    flex-basis: calc(100% - 24px);
  }

  .key-side {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--sp-3);
    margin-left: calc(7px + var(--sp-3));
    white-space: normal;
  }
}

/* 角色 × 权限：默认收起；展开后表格在自己的容器里左右滑，第一列固定 */
.matrix-fold {
  margin-top: var(--sp-6);
}

.matrix-wrap {
  overflow-x: auto;
  margin-top: var(--sp-2);
  border-top: 1px solid var(--hairline);
}

.matrix {
  border-collapse: collapse;
  font-size: var(--text-sm);
  min-width: 100%;
}

.matrix th,
.matrix td {
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--hairline);
  vertical-align: top;
}

.matrix th {
  font-weight: 500;
  font-size: var(--text-xs);
  color: var(--ink-2);
  text-align: left;
}

.perm-col {
  position: sticky;
  left: 0;
  min-width: 190px;
  background: var(--paper);
}

.role-col {
  text-align: center !important;
  white-space: nowrap;
}

.role-col span {
  display: block;
}

.small {
  font-size: var(--text-xs);
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
  border-radius: 999px;
  background: var(--warning-wash);
  color: var(--warning);
}

.desc {
  display: block;
}
</style>

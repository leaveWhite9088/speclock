<script setup>
/**
 * CRListView（/change-requests）—— 审核单列表（只读展示）。
 * 审核单由 Agent 经 MCP 创建、提交、落地；人在对话里确认。本页只负责让人看清楚
 * “有哪些变更、到哪一步了”，不提供任何操作。
 */
import { computed, ref } from 'vue'
import { resources } from '../api/resources.js'
import { useAsync } from '../composables/useAsync.js'
import { CR_STATUS } from '../labels.js'
import { fmtTime } from '../time.js'
import CRStatusBadge from '../components/CRStatusBadge.vue'
import PageHeader from '../components/PageHeader.vue'
import AsyncState from '../components/AsyncState.vue'
import KeyChip from '../components/KeyChip.vue'
import { useAutoRefresh } from '../composables/useAutoRefresh.js'

const STATUS_OPTIONS = [['', '全部'], ...Object.entries(CR_STATUS)]

const status = ref('')
const { data, loading, error, reload } = useAsync(() => resources.crs.list(status.value), {
  watch: [status],
})
useAutoRefresh(reload)
const rows = computed(() => data.value || [])

const pendingCount = computed(() => rows.value.filter((r) => r.status === 'pending_review').length)

function coverage(r) {
  const total = (r.acceptance || []).length
  return `${(r.coverage?.covered || []).length}/${total}`
}

function when(r) {
  return fmtTime(r.applied_at || r.decided_at || r.submitted_at || r.created_at)
}
</script>

<template>
  <div class="page cr-list-page">
    <PageHeader
      eyebrow="Change Requests"
      title="审核单"
      desc="审核单是你和需求 Agent 之间的约定：只写业务意图——为什么变、变成什么样、验收条件。批准 / 驳回由你在对话里告诉 Agent，本页只做展示。"
    >
      <template #actions>
        <select v-model="status" class="input status-pick" aria-label="按状态筛选">
          <option v-for="[v, label] in STATUS_OPTIONS" :key="v" :value="v">{{ label }}</option>
        </select>
      </template>
    </PageHeader>

    <p v-if="pendingCount && !status" class="pending-hint">
      有 {{ pendingCount }} 个审核单正等你确认。
    </p>

    <AsyncState
      :loading="loading"
      :error="error"
      :empty="!rows.length"
      empty-title="这里还没有审核单"
      empty-text="让需求 Agent 把你的想法整理成一个审核单吧；它提交后会出现在这里，等你确认。"
      @retry="reload"
    >
    <div class="card table-card">
      <table class="cr-table">
        <thead>
          <tr>
            <th>编号</th>
            <th>标题</th>
            <th>状态</th>
            <th>验收覆盖</th>
            <th>Commit</th>
            <th>最近变化</th>
            <th>提交者</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td class="mono muted">#{{ r.id }}</td>
            <td>
              <RouterLink :to="`/change-requests/${r.id}`" class="cr-title">{{ r.title }}</RouterLink>
              <span v-if="r.kind === 'internal'" class="kind-tag" title="内部整理：Agent 自行判定，提交即生效">内部整理</span>
            </td>
            <td><CRStatusBadge :status="r.status" /></td>
            <td class="mono">{{ coverage(r) }}</td>
            <td class="mono">{{ r.commit_count }}</td>
            <td class="mono muted">{{ when(r) }}</td>
            <td class="muted"><KeyChip :hint="r.created_by" /></td>
          </tr>
        </tbody>
      </table>
    </div>
    </AsyncState>
  </div>
</template>

<style scoped>
.cr-list-page {
  max-width: 980px;
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
}

.status-pick {
  width: auto;
  min-width: 140px;
}

.pending-hint {
  margin: var(--sp-3) 0;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--radius);
  background: var(--contract-wash);
  color: var(--contract);
  font-size: var(--text-sm);
}

.state-card {
  margin-top: var(--sp-5);
  padding: var(--sp-6);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.table-card {
  margin-top: var(--sp-4);
  padding: 0;
  overflow-x: auto;
}

.cr-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.cr-table th,
.cr-table td {
  text-align: left;
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--hairline);
}

.cr-table th {
  color: var(--ink-2);
  font-weight: 500;
  white-space: nowrap;
}

.cr-table tr:last-child td {
  border-bottom: none;
}

.cr-title {
  font-weight: 500;
}
.kind-tag {
  margin-left: var(--sp-2);
  font-size: var(--text-xs);
  padding: 0 var(--sp-2);
  border: 1px solid var(--warning);
  color: var(--warning);
  border-radius: var(--radius-sm);
  white-space: nowrap;
}
</style>

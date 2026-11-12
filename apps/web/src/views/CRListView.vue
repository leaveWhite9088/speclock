<script setup>
/**
 * CRListView（/change-requests）—— 审核单列表（只读展示）。
 * 宽屏是自适应的表格（标题列吃掉剩余宽度，其他列贴着内容），窄屏每行折成「标题 + 一行元信息」。
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
    <PageHeader title="审核单" />

    <div class="chips" role="tablist" aria-label="按状态筛选">
      <button
        v-for="[v, label] in STATUS_OPTIONS"
        :key="v"
        type="button"
        class="chip"
        :class="{ on: status === v }"
        :aria-selected="status === v"
        role="tab"
        @click="status = v"
      >
        {{ label }}
      </button>
    </div>

    <AsyncState :loading="loading" :error="error" :empty="!rows.length" empty-title="没有审核单" @retry="reload">
      <table class="cr-table">
        <thead>
          <tr>
            <th>标题</th>
            <th>状态</th>
            <th>验收</th>
            <th>最近变化</th>
            <th>提交者</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td class="c-title">
              <RouterLink :to="`/change-requests/${r.id}`" class="cr-title">
                <span class="cr-id mono">#{{ r.id }}</span>
                {{ r.title }}
              </RouterLink>
              <span v-if="r.kind === 'internal'" class="kind-tag">内部整理</span>
            </td>
            <td class="c-fit"><CRStatusBadge :status="r.status" /></td>
            <td class="c-fit mono muted" data-label="验收">{{ coverage(r) }}</td>
            <td class="c-fit muted">{{ when(r) }}</td>
            <td class="c-fit muted"><KeyChip :hint="r.created_by" /></td>
          </tr>
        </tbody>
      </table>
    </AsyncState>
  </div>
</template>

<style scoped>
.cr-list-page {
  max-width: 1040px;
}

/* 自适应表格：table-layout 用 auto，标题列拿剩余宽度，其余列贴着内容 */
.cr-table {
  width: 100%;
  margin-top: var(--sp-3);
  border-collapse: collapse;
  table-layout: auto;
  font-size: var(--text-md);
}

.cr-table th,
.cr-table td {
  text-align: left;
  vertical-align: baseline;
  padding: var(--sp-3) var(--sp-3);
  border-top: 1px solid var(--hairline);
}

.cr-table th {
  border-top: none;
  padding-top: var(--sp-1);
  padding-bottom: var(--sp-1);
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--ink-2);
  white-space: nowrap;
}

.cr-table tbody tr:last-child td {
  border-bottom: 1px solid var(--hairline);
}

.cr-table tbody tr:hover {
  background: var(--side);
}

.c-title {
  width: 100%;
  min-width: 14em;
}

.c-fit {
  width: 1%;
  white-space: nowrap;
  font-size: var(--text-sm);
}

.cr-title {
  color: var(--ink);
  font-weight: 500;
}

.cr-title:hover {
  color: var(--contract);
}

.cr-id {
  margin-right: var(--sp-1);
  font-size: var(--text-xs);
  font-weight: 400;
  color: var(--ink-2);
}

.kind-tag {
  margin-left: var(--sp-2);
  font-size: var(--text-xs);
  padding: 0 var(--sp-2);
  border-radius: 999px;
  background: var(--warning-wash);
  color: var(--warning);
  white-space: nowrap;
}

/* 窄屏：不要表格了。每行 = 标题一行 + 元信息一行（状态 · 验收 · 时间 · 提交者） */
@container (max-width: 640px) {
  .cr-table,
  .cr-table tbody {
    display: block;
  }

  .cr-table thead {
    display: none;
  }

  .cr-table tr {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--sp-1) var(--sp-3);
    padding: var(--sp-3) var(--sp-1);
    border-top: 1px solid var(--hairline);
  }

  .cr-table tbody tr:last-child {
    border-bottom: 1px solid var(--hairline);
  }

  .cr-table td,
  .cr-table tbody tr:last-child td {
    display: block;
    padding: 0;
    border: none;
  }

  .c-title {
    flex: 1 1 100%;
    min-width: 0;
    width: auto;
  }

  .c-fit {
    width: auto;
    font-size: var(--text-sm);
  }
}
</style>

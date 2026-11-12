<script setup>
/**
 * WorkView（/work）—— 待办看板：每个已发布模块版本的执行记录。纯展示：
 * 领取 / 实现 / 验收都由 Agent 经 MCP（或 REST）完成。
 */
import { ref, computed, watch } from 'vue'
import { resources } from '../api/resources.js'
import { useAsync } from '../composables/useAsync.js'
import { errText } from '../errors.js'
import { EXEC_EVENT, EXEC_STATUS, label } from '../labels.js'
import { fmtTime } from '../time.js'
import ExecStatusBadge from '../components/ExecStatusBadge.vue'
import PageHeader from '../components/PageHeader.vue'
import AsyncState from '../components/AsyncState.vue'
import KeyChip from '../components/KeyChip.vue'
import { useAutoRefresh } from '../composables/useAutoRefresh.js'

const FILTERS = [
  ['', '全部（除已被取代）'],
  ...Object.entries(EXEC_STATUS),
]

const status = ref('')
const opened = ref({}) // work id -> 详情（含事件）
const openError = ref('')

const { data, loading, error: pageError, reload: load } = useAsync(
  async () => {
    const [list, all] = await Promise.all([
      resources.work.list({ status: status.value }),
      resources.work.list(),
    ])
    const counts = {}
    for (const r of all) counts[r.status] = (counts[r.status] || 0) + 1
    return { rows: list, counts }
  },
  { watch: [status] },
)
useAutoRefresh(load)
const rows = computed(() => data.value?.rows || [])
const counts = computed(() => data.value?.counts || {})

async function toggle(r) {
  openError.value = ''
  if (opened.value[r.id]) {
    const { [r.id]: _drop, ...rest } = opened.value
    opened.value = rest
    return
  }
  try {
    opened.value = { ...opened.value, [r.id]: await resources.work.get(r.id) }
  } catch (e) {
    openError.value = errText(e)
  }
}

function pick(s) {
  status.value = s
  opened.value = {}
}

const total = computed(() => Object.values(counts.value).reduce((a, b) => a + b, 0))
</script>

<template>
  <div class="page work-page">
    <PageHeader title="待办" />

    <div class="chips" role="tablist" aria-label="按状态筛选">
      <button
        v-for="[v, label] in FILTERS"
        :key="v"
        type="button"
        class="chip"
        :class="{ on: status === v }"
        role="tab"
        :aria-selected="status === v"
        @click="pick(v)"
      >
        {{ label }}<span v-if="v ? counts[v] : total" class="n">{{ v ? counts[v] : total }}</span>
      </button>
    </div>

    <p v-if="openError" class="error-text" role="alert">{{ openError }}</p>

    <AsyncState :loading="loading" :error="pageError" :empty="!rows.length" empty-title="没有记录" @retry="load">
      <ul class="list items">
        <li v-for="r in rows" :key="r.id" class="item">
          <div class="item-line">
            <RouterLink class="item-block" :to="`/blocks/${r.block_id}?version=${r.version}`">
              {{ r.block_title }} <span class="mono muted ver">v{{ r.version }}</span>
            </RouterLink>
            <ExecStatusBadge :status="r.status" />
          </div>
          <p class="item-sub">
            <span>{{ r.business }} / {{ r.capability_title }}</span>
            <span v-if="r.claimed_by"><KeyChip :hint="r.claimed_by" /></span>
            <span>{{ fmtTime(r.updated_at) }}</span>
            <a href="#" class="item-toggle" @click.prevent="toggle(r)">{{ opened[r.id] ? '收起' : '历史' }}</a>
          </p>
          <p v-if="r.reason && ['blocked', 'failed'].includes(r.status)" class="item-reason">{{ r.reason }}</p>
          <ol v-if="opened[r.id]" class="events">
            <li v-for="(e, i) in opened[r.id].events" :key="i">
              <span class="mono muted">{{ fmtTime(e.created_at) }}</span>
              <span class="ev-name">{{ label(EXEC_EVENT, e.event) }}</span>
              <span class="muted">{{ label(EXEC_STATUS, e.from) }} → {{ label(EXEC_STATUS, e.to) }}</span>
              <span class="muted"><KeyChip :hint="e.actor" /></span>
              <span v-if="e.note" class="ev-note">{{ e.note }}</span>
            </li>
          </ol>
        </li>
      </ul>
    </AsyncState>
  </div>
</template>

<style scoped>
.items {
  margin-top: var(--sp-3);
}

.item {
  padding: var(--sp-3) var(--sp-1);
}

.item-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
}

.item-block {
  min-width: 0;
  color: var(--ink);
  font-weight: 500;
}

.item-block:hover {
  color: var(--contract);
}

.ver {
  font-size: var(--text-xs);
  font-weight: 400;
}

.item-sub {
  display: flex;
  flex-wrap: wrap;
  gap: 0 var(--sp-3);
  margin-top: 2px;
  font-size: var(--text-sm);
  color: var(--ink-2);
}

.item-reason {
  margin-top: var(--sp-1);
  font-size: var(--text-md);
}

.events {
  margin: var(--sp-2) 0 0;
  padding-left: var(--sp-4);
  border-left: 2px solid var(--hairline);
  font-size: var(--text-sm);
}

.events li {
  display: flex;
  gap: var(--sp-3);
  flex-wrap: wrap;
  padding: 2px 0;
}

.ev-name {
  font-weight: 500;
}
</style>

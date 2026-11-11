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
    <PageHeader
      eyebrow="Execution"
      title="待办"
      desc="每个已发布的模块版本都会自动产生一条执行记录：执行 Agent 领取并实现，测试 Agent 独立验收。新版本发布后，旧版本上没做完的记录会被取代。这里只做展示。"
    />

    <p v-if="total" class="stats-line muted">
      共 {{ total }} 条 ·
      <span v-for="(n, s) in counts" :key="s" class="stat"><ExecStatusBadge :status="s" /> {{ n }}</span>
    </p>

    <div class="filter-row">
      <button
        v-for="[v, label] in FILTERS"
        :key="v"
        type="button"
        class="btn btn-mini"
        :class="{ 'is-on': status === v }"
        @click="pick(v)"
      >
        {{ label }}
      </button>
    </div>

    <p v-if="openError" class="error-text" role="alert">{{ openError }}</p>

    <AsyncState
      :loading="loading"
      :error="pageError"
      :empty="!rows.length"
      empty-title="这里还没有记录"
      empty-text="模块经审核单 Commit 发布后，会自动出现一条「待领取」。"
      @retry="load"
    >
    <div class="card list">
      <div v-for="r in rows" :key="r.id" class="item">
        <div class="item-head">
          <ExecStatusBadge :status="r.status" />
          <RouterLink class="item-block" :to="`/blocks/${r.block_id}?version=${r.version}`">
            {{ r.block_title }}
          </RouterLink>
          <span class="mono muted">v{{ r.version }}</span>
          <span class="muted item-path">{{ r.business }} / {{ r.capability_title }}</span>
          <span v-if="r.claimed_by" class="muted item-who">领取：<KeyChip :hint="r.claimed_by" /></span>
          <span class="muted mono item-time">{{ fmtTime(r.updated_at) }}</span>
          <a href="#" class="item-toggle" @click.prevent="toggle(r)">
            {{ opened[r.id] ? '收起' : '历史' }}
          </a>
        </div>
        <p v-if="r.reason && ['blocked', 'failed'].includes(r.status)" class="item-reason">
          {{ r.reason }}
        </p>
        <ol v-if="opened[r.id]" class="events">
          <li v-for="(e, i) in opened[r.id].events" :key="i">
            <span class="mono muted">{{ fmtTime(e.created_at) }}</span>
            <span class="ev-name">{{ label(EXEC_EVENT, e.event) }}</span>
            <span class="muted">{{ label(EXEC_STATUS, e.from) }} → {{ label(EXEC_STATUS, e.to) }}</span>
            <span class="muted"><KeyChip :hint="e.actor" /></span>
            <span v-if="e.note" class="ev-note">{{ e.note }}</span>
          </li>
        </ol>
      </div>
    </div>
    </AsyncState>
  </div>
</template>

<style scoped>
.work-page {
  max-width: 960px;
}

.stats-line {
  margin-top: var(--sp-3);
  font-size: var(--text-xs);
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  align-items: center;
}

.stat {
  display: inline-flex;
  gap: var(--sp-1);
  align-items: center;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin: var(--sp-4) 0;
}

.btn.is-on {
  border-color: var(--contract);
  color: var(--contract);
  background: var(--contract-wash);
}

.state-card {
  padding: var(--sp-5);
}

.list {
  padding: var(--sp-2) var(--sp-5);
}

.item {
  padding: var(--sp-3) 0;
  border-bottom: 1px solid var(--hairline);
}

.item:last-child {
  border-bottom: none;
}

.item-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  font-size: var(--text-sm);
}

.item-block {
  font-weight: 500;
}

.item-path,
.item-who,
.item-time {
  font-size: var(--text-xs);
}

.item-time {
  margin-left: auto;
}

.item-reason {
  margin: var(--sp-2) 0 0;
  font-size: var(--text-sm);
  color: var(--ink-2);
}

.events {
  margin: var(--sp-2) 0 0;
  padding-left: var(--sp-5);
  font-size: var(--text-xs);
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

<script setup>
/**
 * WorkView（/work）—— 待办看板：每个已发布模块版本的执行记录。纯展示：
 * 领取 / 实现 / 验收都由 Agent 经 MCP（或 REST）完成。
 */
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/client.js'
import { useKeyNames } from '../api/keyNames.js'
import { fmtTime } from '../time.js'
import ExecStatusBadge from '../components/ExecStatusBadge.vue'

const { keyName } = useKeyNames()

const FILTERS = [
  ['', '全部（除已被取代）'],
  ['pending', '待领取'],
  ['in_progress', '进行中'],
  ['blocked', '被阻塞'],
  ['failed', '失败'],
  ['implemented', '待验收'],
  ['verified', '已验收'],
  ['superseded', '已被取代'],
]

const status = ref('')
const rows = ref([])
const loading = ref(true)
const pageError = ref('')
const opened = ref({}) // work id -> 详情（含事件）
const counts = ref({})

function errText(e) {
  const d = e && e.detail
  if (!d) return '请求失败，请检查网络后重试。'
  return typeof d === 'string' ? d : d.error || JSON.stringify(d)
}

async function load() {
  loading.value = true
  pageError.value = ''
  try {
    const [list, all] = await Promise.all([
      api.get(status.value ? `/work?status=${status.value}` : '/work'),
      api.get('/work'),
    ])
    rows.value = list
    const c = {}
    for (const r of all) c[r.status] = (c[r.status] || 0) + 1
    counts.value = c
  } catch (e) {
    pageError.value = errText(e)
  } finally {
    loading.value = false
  }
}

async function toggle(r) {
  if (opened.value[r.id]) {
    const { [r.id]: _drop, ...rest } = opened.value
    opened.value = rest
    return
  }
  try {
    opened.value = { ...opened.value, [r.id]: await api.get(`/work/${r.id}`) }
  } catch (e) {
    pageError.value = errText(e)
  }
}

function pick(s) {
  status.value = s
  opened.value = {}
  load()
}

const total = computed(() => Object.values(counts.value).reduce((a, b) => a + b, 0))

onMounted(load)
</script>

<template>
  <div class="page work-page">
    <p class="page-eyebrow">Execution</p>
    <h1 class="page-title">待办</h1>
    <p class="page-desc">
      每个已发布的模块版本都会自动产生一条执行记录：执行 Agent 领取并实现，测试 Agent 独立验收。
      新版本发布后，旧版本上没做完的记录会被取代。这里只做展示。
    </p>

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

    <p v-if="pageError" class="error-text" role="alert">{{ pageError }}</p>
    <div v-if="loading" class="muted">正在加载…</div>

    <div v-else-if="!rows.length" class="card state-card">
      <p class="muted">
        这里还没有记录。模块经审核单 Commit 发布后，会自动出现一条「待领取」。
      </p>
    </div>

    <div v-else class="card list">
      <div v-for="r in rows" :key="r.id" class="item">
        <div class="item-head">
          <ExecStatusBadge :status="r.status" />
          <RouterLink class="item-block" :to="`/blocks/${r.block_id}?version=${r.version}`">
            {{ r.block_title }}
          </RouterLink>
          <span class="mono muted">v{{ r.version }}</span>
          <span class="muted item-path">{{ r.business }} / {{ r.capability_title }}</span>
          <span v-if="r.claimed_by" class="muted item-who">领取：{{ keyName(r.claimed_by) }}</span>
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
            <span class="ev-name">{{ e.event }}</span>
            <span class="muted">{{ e.from || '—' }} → {{ e.to }}</span>
            <span class="muted">{{ keyName(e.actor) }}</span>
            <span v-if="e.note" class="ev-note">{{ e.note }}</span>
          </li>
        </ol>
      </div>
    </div>
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

<script setup>
// 「已完成」回执看板：待回执清单（当前已发布版本未 completed 的模块，按大业务
// 分组、按等待天数倒序）+ 最近回执条带。完成状态只由后端 ack 驱动，页面只读。
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client.js'
import { useKeyNames } from '../api/keyNames.js'
import VersionChip from '../components/VersionChip.vue'
import AcksModal from '../components/AcksModal.vue'

const { keyName } = useKeyNames()

const loading = ref(true)
const error = ref('')
const tree = ref([])
const acks = ref([])
const acksModal = ref(null) // {title, acks, blockId, version, context, loading}

function fmtTime(iso) {
  return iso ? String(iso).replace('T', ' ').slice(0, 19) : '-'
}

function errText(e) {
  const d = e?.detail ?? e
  return typeof d === 'string' ? d : JSON.stringify(d, null, 2)
}

// 计数口径：排除 archived 与从未发布过的 draft 模块
function countable(b) {
  return b.status !== 'archived' && b.current_published_version
}

function waitDays(publishedAt) {
  if (!publishedAt) return 0
  return Math.max(0, (Date.now() - new Date(publishedAt)) / 864e5)
}

function waitLabel(days) {
  return days < 1 ? '今天发布' : `已等待 ${Math.floor(days)} 天`
}

const stats = computed(() => {
  let total = 0
  let done = 0
  for (const p of tree.value) {
    for (const d of p.domains) {
      for (const doc of d.documents) {
        for (const b of doc.blocks || []) {
          if (!countable(b)) continue
          total += 1
          if (b.completed) done += 1
        }
      }
    }
  }
  return { total, done, pending: total - done }
})

const pendingByDomain = computed(() => {
  const out = []
  for (const p of tree.value) {
    for (const d of p.domains) {
      const items = []
      for (const doc of d.documents) {
        for (const b of doc.blocks || []) {
          if (!countable(b) || b.completed) continue
          items.push({
            id: b.id,
            title: b.title,
            docTitle: doc.title,
            version: b.current_published_version,
            publishedAt: b.current_published_at,
            days: waitDays(b.current_published_at),
          })
        }
      }
      if (items.length) {
        items.sort((x, y) => y.days - x.days)
        out.push({ id: d.id, name: d.name, project: p.name, items })
      }
    }
  }
  return out
})

const recentAcks = computed(() => acks.value.slice(0, 10))

const expandedTasks = ref(new Set())
function toggleTask(id) {
  const s = new Set(expandedTasks.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  expandedTasks.value = s
}

async function openAck(a) {
  acksModal.value = {
    title: `${a.block_title}（v${a.version}）回执`,
    acks: [a],
    blockId: a.block_id,
    version: a.version,
    context: null,
    loading: true,
  }
  try {
    const vs = await api.get(`/blocks/${a.block_id}/versions`)
    const idx = vs.findIndex((v) => v.version === a.version)
    if (idx >= 0 && acksModal.value?.version === a.version) {
      acksModal.value = {
        ...acksModal.value,
        loading: false,
        context: {
          ...vs[idx],
          block_id: a.block_id,
          current_version: vs.at(-1)?.version,
          prev_version: idx > 0 ? vs[idx - 1].version : null,
        },
      }
      return
    }
  } catch {
    /* 版本上下文取不到（如已作废）时仅展示回执记录与模块页链接 */
  }
  if (acksModal.value?.version === a.version) {
    acksModal.value = { ...acksModal.value, loading: false }
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [t, a] = await Promise.all([api.get('/tree'), api.get('/acks')])
    tree.value = t
    acks.value = a
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page acks-page">
    <p class="page-eyebrow">Acks</p>
    <h1 class="page-title">「已完成」回执看板</h1>
    <p class="page-desc">
      待回执清单：当前已发布版本还没有回执的模块，按等待时长倒序。AI 实现完一个
      模块版本后调用 ack_block 留下回执，回执当前最新发布版本即把模块标记为已完成。
    </p>

    <p v-if="loading" class="muted">加载中…</p>

    <div v-else-if="error" class="card state-card">
      <p class="error-text">{{ error }}</p>
      <button type="button" class="btn" @click="load">重试</button>
    </div>

    <template v-else>
      <p class="muted stats-line">
        全部 {{ stats.total }} 个模块 · {{ stats.pending }} 个待回执 ·
        {{ stats.done }} 个已完成（口径：排除已归档与从未发布过的草稿模块）
      </p>

      <p v-if="!pendingByDomain.length" class="card state-card muted">
        全部模块当前版本均已回执。
      </p>

      <section v-for="d in pendingByDomain" :key="d.id" class="card domain-card">
        <header class="domain-head">
          <span class="domain-name">{{ d.name }}</span>
          <span class="muted domain-project">{{ d.project }}</span>
          <span class="muted domain-count">{{ d.items.length }} 个待回执</span>
        </header>
        <ul class="pending-list">
          <li v-for="b in d.items" :key="b.id" class="pending-item">
            <span class="bid mono">#{{ b.id }}</span>
            <RouterLink :to="`/blocks/${b.id}`" class="pending-block">{{
              b.title
            }}</RouterLink>
            <span class="muted pending-doc">{{ b.docTitle }}</span>
            <VersionChip :version="b.version" />
            <span class="muted pending-time">{{ fmtTime(b.publishedAt) }}</span>
            <span class="wait-chip" :class="{ 'is-long': b.days >= 3 }">
              {{ waitLabel(b.days) }}
            </span>
          </li>
        </ul>
      </section>

      <section class="card recent-card">
        <h2 class="recent-title">最近回执</h2>
        <p v-if="!recentAcks.length" class="muted">
          还没有回执。AI 通过 MCP 或 REST 调用 ack_block 声明「已按 模块@版本 实现」后，记录会出现在这里。
        </p>
        <ul v-else class="recent-list">
          <li class="recent-item recent-item-head">
            <span>模块</span>
            <span>版本</span>
            <span>回执人</span>
            <span>任务说明</span>
            <span>时间</span>
            <span></span>
          </li>
          <li v-for="a in recentAcks" :key="a.id" class="recent-item">
            <span class="recent-block">
              <span class="bid mono">#{{ a.block_id }}</span>
              <RouterLink :to="`/blocks/${a.block_id}`" class="recent-block-link">{{
                a.block_title
              }}</RouterLink>
            </span>
            <VersionChip :version="a.version" />
            <span class="mono recent-key">{{ keyName(a.agent_key) }}</span>
            <span
              class="muted recent-task"
              :class="{ expanded: expandedTasks.has(a.id) }"
              :title="a.task_desc ? '点击展开/收起' : ''"
              @click="toggleTask(a.id)"
            >{{ a.task_desc || '（未填写）' }}</span>
            <span class="muted recent-time">{{ fmtTime(a.created_at) }}</span>
            <a href="#" class="recent-open" @click.prevent="openAck(a)">查看回执</a>
          </li>
        </ul>
      </section>
    </template>

    <AcksModal
      v-if="acksModal"
      :title="acksModal.title"
      :context="acksModal.context"
      :acks="acksModal.acks"
      :loading="acksModal.loading"
      :block-id="acksModal.blockId"
      @close="acksModal = null"
    />
  </div>
</template>

<style scoped>
.acks-page {
  max-width: 960px;
}

.state-card {
  margin-top: var(--sp-4);
  padding: var(--sp-5);
}

.stats-line {
  margin-top: var(--sp-4);
  font-size: var(--text-xs);
}

/* ---------- 待回执清单 ---------- */

.domain-card {
  margin-top: var(--sp-4);
  padding: var(--sp-4) var(--sp-5);
}

.domain-head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--hairline);
}

.domain-name {
  font-weight: 600;
  font-size: var(--text-md);
}

.domain-project {
  font-size: var(--text-xs);
}

.domain-count {
  margin-left: auto;
  font-size: var(--text-xs);
  white-space: nowrap;
}

.pending-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.pending-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--hairline);
  font-size: var(--text-sm);
  flex-wrap: wrap;
}

.pending-item:last-child {
  border-bottom: none;
}

.pending-block {
  font-weight: 500;
}

.pending-doc {
  font-size: var(--text-xs);
}

.pending-time {
  font-size: var(--text-xs);
  white-space: nowrap;
}

.wait-chip {
  margin-left: auto;
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--warning);
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 7%, var(--card));
  white-space: nowrap;
}

.wait-chip.is-long {
  border-color: var(--danger);
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 7%, var(--card));
}

/* ---------- 最近回执 ---------- */

.recent-card {
  margin-top: var(--sp-4);
  padding: var(--sp-4) var(--sp-5);
}

.recent-title {
  font-size: var(--text-md);
  font-weight: 600;
}

.recent-list {
  margin: var(--sp-2) 0 0;
  padding: 0;
  list-style: none;
}

.recent-item {
  display: grid;
  grid-template-columns: 190px 76px 104px minmax(0, 1fr) 150px 60px;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--hairline);
  font-size: var(--text-sm);
}

.recent-item-head {
  font-size: var(--text-xs);
  color: var(--ink-2);
  padding-bottom: var(--sp-1);
}

.recent-item:last-child {
  border-bottom: none;
}

.recent-block {
  display: flex;
  align-items: baseline;
  gap: var(--sp-1);
  min-width: 0;
  overflow: hidden;
}

.recent-block-link {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-key {
  font-size: var(--text-xs);
  color: var(--ink-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-task {
  font-size: var(--text-xs);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.recent-task.expanded {
  white-space: pre-wrap;
  word-break: break-word;
}

.recent-open {
  font-size: var(--text-xs);
  white-space: nowrap;
}

.recent-time {
  font-size: var(--text-xs);
  white-space: nowrap;
}
</style>

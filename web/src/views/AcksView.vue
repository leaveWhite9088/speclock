<script setup>
// 「已完成」回执总览：全项目进度统计 + 按 大业务→文档→模块 的进度卡片
// + 最近回执条带。模块完成状态只由后端 ack 驱动，页面只读展示。
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client.js'
import VersionChip from '../components/VersionChip.vue'
import AcksModal from '../components/AcksModal.vue'

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
function countable(blocks) {
  return blocks.filter((b) => b.status !== 'archived' && b.current_published_version)
}

function blockState(b) {
  if (b.completed) return 'done'
  if (b.status !== 'archived' && b.current_published_version) return 'pending'
  return 'draft'
}

const domains = computed(() => {
  const out = []
  for (const p of tree.value) {
    for (const d of p.domains) {
      const docs = []
      let total = 0
      let done = 0
      for (const doc of d.documents) {
        const blocks = countable(doc.blocks || [])
        const docDone = blocks.filter((b) => b.completed).length
        total += blocks.length
        done += docDone
        docs.push({
          id: doc.id,
          title: doc.title,
          blocks,
          total: blocks.length,
          done: docDone,
        })
      }
      out.push({ id: d.id, name: d.name, project: p.name, docs, total, done })
    }
  }
  return out
})

const overall = computed(() => ({
  total: domains.value.reduce((s, d) => s + d.total, 0),
  done: domains.value.reduce((s, d) => s + d.done, 0),
}))

const recentAcks = computed(() => acks.value.slice(0, 10))

function pct(done, total) {
  return total ? Math.round((done / total) * 100) : 0
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
      全项目模块完成进度总览：AI 实现完一个模块版本后调用 ack_block 留下回执，
      回执当前最新发布版本即把模块标记为已完成。按 大业务→文档→模块 逐层展开，
      底部是最近的回执记录。
    </p>

    <p v-if="loading" class="muted">加载中…</p>

    <div v-else-if="error" class="card state-card">
      <p class="error-text">{{ error }}</p>
      <button type="button" class="btn" @click="load">重试</button>
    </div>

    <template v-else>
      <section class="card overall-card">
        <p class="overall-num">
          全项目已完成 <strong>{{ overall.done }}/{{ overall.total }}</strong>
          <span class="muted">（{{ pct(overall.done, overall.total) }}%）</span>
        </p>
        <div class="bar">
          <div
            class="bar-fill"
            :style="{ width: `${pct(overall.done, overall.total)}%` }"
          ></div>
        </div>
        <p class="muted overall-note">
          计数口径：排除已归档与从未发布过的草稿模块。
        </p>
      </section>

      <p v-if="!domains.length" class="muted">还没有任何大业务。</p>

      <section v-for="d in domains" :key="d.id" class="card domain-card">
        <header class="domain-head">
          <span class="domain-name">{{ d.name }}</span>
          <span class="muted domain-project">{{ d.project }}</span>
          <span class="domain-count">
            {{ d.done }}/{{ d.total }}（{{ pct(d.done, d.total) }}%）
          </span>
        </header>
        <div class="bar">
          <div class="bar-fill" :style="{ width: `${pct(d.done, d.total)}%` }"></div>
        </div>

        <div v-for="doc in d.docs" :key="doc.id" class="doc-row">
          <div class="doc-line">
            <span class="doc-title">{{ doc.title }}</span>
            <div class="bar bar-mini">
              <div
                class="bar-fill"
                :style="{ width: `${pct(doc.done, doc.total)}%` }"
              ></div>
            </div>
            <span class="muted doc-count">{{ doc.done }}/{{ doc.total }}</span>
          </div>
          <div class="block-chips">
            <RouterLink
              v-for="b in doc.blocks"
              :key="b.id"
              :to="`/blocks/${b.id}`"
              class="block-chip"
              :class="`is-${blockState(b)}`"
              :title="b.title"
            >
              {{ b.title }}
            </RouterLink>
            <span v-if="!doc.blocks.length" class="muted chip-empty">
              无可计数模块
            </span>
          </div>
        </div>
      </section>

      <section class="card recent-card">
        <h2 class="recent-title">最近回执</h2>
        <p v-if="!recentAcks.length" class="muted">
          还没有回执。AI 通过 MCP 或 REST 调用 ack_block 声明「已按 模块@版本 实现」后，记录会出现在这里。
        </p>
        <ul v-else class="recent-list">
          <li v-for="a in recentAcks" :key="a.id" class="recent-item">
            <RouterLink :to="`/blocks/${a.block_id}`" class="recent-block">{{
              a.block_title
            }}</RouterLink>
            <VersionChip :version="a.version" />
            <span class="mono recent-key">{{ a.agent_key }}</span>
            <span v-if="a.task_desc" class="muted recent-task">{{ a.task_desc }}</span>
            <a href="#" class="recent-open" @click.prevent="openAck(a)">查看回执</a>
            <span class="muted recent-time">{{ fmtTime(a.created_at) }}</span>
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
  margin-top: var(--sp-5);
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

/* ---------- 总统计 ---------- */

.overall-card {
  margin-top: var(--sp-5);
  padding: var(--sp-4) var(--sp-5);
}

.overall-num {
  font-size: var(--text-md);
}

.overall-num strong {
  font-size: var(--text-lg);
}

.overall-note {
  margin-top: var(--sp-2);
  font-size: var(--text-xs);
}

/* ---------- 进度条 ---------- */

.bar {
  margin-top: var(--sp-2);
  height: 6px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--ink-2) 12%, var(--card));
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: var(--contract);
  border-radius: var(--radius-sm);
  transition: width var(--dur) var(--ease);
}

.bar-mini {
  margin-top: 0;
  flex: 1;
  height: 4px;
}

/* ---------- 大业务卡片 ---------- */

.domain-card {
  margin-top: var(--sp-4);
  padding: var(--sp-4) var(--sp-5);
}

.domain-head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
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
  font-size: var(--text-sm);
  color: var(--ink-2);
  white-space: nowrap;
}

.doc-row {
  margin-top: var(--sp-3);
  padding-top: var(--sp-3);
  border-top: 1px solid var(--hairline);
}

.doc-line {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.doc-title {
  font-size: var(--text-sm);
  font-weight: 500;
  min-width: 0;
}

.doc-count {
  font-size: var(--text-xs);
  white-space: nowrap;
}

/* ---------- 模块状态徽标 ---------- */

.block-chips {
  margin-top: var(--sp-2);
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.block-chip {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--hairline);
  color: var(--ink-2);
  text-decoration: none;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.block-chip.is-done {
  color: var(--success);
  border-color: var(--success);
  background: color-mix(in srgb, var(--success) 7%, var(--card));
}

.block-chip.is-pending {
  color: var(--warning);
  border-color: var(--warning);
  background: color-mix(in srgb, var(--warning) 7%, var(--card));
}

.block-chip.is-draft {
  color: var(--ink-2);
  background: color-mix(in srgb, var(--ink-2) 5%, var(--card));
}

.chip-empty {
  font-size: var(--text-xs);
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
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--hairline);
  font-size: var(--text-sm);
  flex-wrap: wrap;
}

.recent-item:last-child {
  border-bottom: none;
}

.recent-block {
  font-weight: 500;
}

.recent-key {
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.recent-task {
  font-size: var(--text-xs);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-time {
  margin-left: auto;
  font-size: var(--text-xs);
  white-space: nowrap;
}

.recent-open {
  font-size: var(--text-xs);
  white-space: nowrap;
}
</style>

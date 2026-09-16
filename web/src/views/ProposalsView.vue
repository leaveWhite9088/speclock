<script setup>
// 提案收件箱：按状态过滤，待处理提案可批准（应用到草稿并发布）或拒绝（需填理由）。
import { computed, onMounted, ref } from 'vue'
import { marked } from 'marked'
import { api } from '../api/client.js'
import VersionChip from '../components/VersionChip.vue'

const TABS = [
  { key: 'submitted', label: '待处理' },
  { key: 'published', label: '已发布' },
  { key: 'rejected', label: '已拒绝' },
]

const EMPTY_TEXT = {
  submitted: '没有待处理的提案。AI 通过 submit_proposal 提交的变更建议会出现在这里。',
  published: '还没有已发布的提案。批准待处理提案后，它会带着发布版本号归档到这里。',
  rejected: '没有已拒绝的提案。',
}

const activeTab = ref('submitted')
const loading = ref(true)
const error = ref('')
const proposals = ref([])
const notes = ref({}) // proposalId -> 审批意见
const busy = ref({}) // proposalId -> bool
const cardError = ref({}) // proposalId -> string
const flash = ref('')

const emptyText = computed(() => EMPTY_TEXT[activeTab.value])

function fmtTime(iso) {
  return iso ? String(iso).replace('T', ' ').slice(0, 19) : '-'
}

function errText(e) {
  const d = e?.detail ?? e
  if (typeof d === 'string') return d
  if (d && Array.isArray(d.missing)) {
    return `${d.error || '操作被拒绝'}：${d.missing.join('；')}`
  }
  return JSON.stringify(d, null, 2)
}

function renderMd(text) {
  return marked.parse(text || '')
}

function proposedApis(p) {
  const apis = p.proposed_apis
  if (!apis) return null
  return typeof apis === 'string' ? apis : JSON.stringify(apis, null, 2)
}

function switchTab(key) {
  if (activeTab.value === key) return
  activeTab.value = key
  flash.value = ''
  load()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    proposals.value = await api.get(`/proposals?status=${activeTab.value}`)
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

async function resolve(p, action) {
  const note = (notes.value[p.id] || '').trim()
  if (action === 'reject' && !note) {
    cardError.value = { ...cardError.value, [p.id]: '拒绝需要填写理由——告诉提交方为什么。' }
    return
  }
  busy.value = { ...busy.value, [p.id]: true }
  cardError.value = { ...cardError.value, [p.id]: '' }
  try {
    const r = await api.post(`/proposals/${p.id}/resolve`, {
      action,
      resolution_note: note,
    })
    flash.value =
      action === 'approve'
        ? `提案 #${p.id} 已批准并发布为 v${r.published_version}（文档版本 v${r.document_version}）。`
        : `提案 #${p.id} 已拒绝。`
    await load()
  } catch (e) {
    cardError.value = { ...cardError.value, [p.id]: errText(e) }
  } finally {
    busy.value = { ...busy.value, [p.id]: false }
  }
}

onMounted(load)
</script>

<template>
  <div class="page proposals-page">
    <p class="page-eyebrow">Proposals</p>
    <h1 class="page-title">提案收件箱</h1>
    <p class="page-desc">
      提案是 AI 唯一的写出口。批准后提案内容会应用到模块草稿并立即发布；拒绝需填写理由。
    </p>

    <div class="tabs" role="tablist">
      <button
        v-for="t in TABS"
        :key="t.key"
        type="button"
        role="tab"
        class="tab"
        :class="{ 'is-active': activeTab === t.key }"
        :aria-selected="activeTab === t.key"
        @click="switchTab(t.key)"
      >
        {{ t.label }}
      </button>
    </div>

    <p v-if="flash" class="flash">{{ flash }}</p>

    <p v-if="loading" class="muted">加载中…</p>

    <div v-else-if="error" class="card state-card">
      <p class="error-text">{{ error }}</p>
      <button type="button" class="btn" @click="load">重试</button>
    </div>

    <div v-else-if="!proposals.length" class="card state-card">
      <p class="muted">{{ emptyText }}</p>
    </div>

    <div v-else class="proposal-list">
      <article v-for="p in proposals" :key="p.id" class="card proposal-card">
        <header class="p-head">
          <span class="p-id mono">#{{ p.id }}</span>
          <RouterLink :to="`/blocks/${p.block_id}`" class="p-block">{{
            p.block_title
          }}</RouterLink>
          <span class="p-status" :class="`is-${p.status}`">
            {{ { submitted: '待处理', published: '已发布', rejected: '已拒绝' }[p.status] || p.status }}
          </span>
          <VersionChip
            v-if="p.published_version"
            :version="p.published_version"
          />
          <span class="p-author">{{ p.author_type === 'agent' ? 'AI 提交' : '人工提交' }}</span>
          <span class="muted p-time">{{ fmtTime(p.created_at) }}</span>
        </header>

        <dl class="p-body">
          <div class="p-field">
            <dt>问题</dt>
            <dd>{{ p.description }}</dd>
          </div>
          <div class="p-field">
            <dt>建议</dt>
            <dd>{{ p.suggestion }}</dd>
          </div>
          <div v-if="p.scenario" class="p-field">
            <dt>场景</dt>
            <dd class="muted">{{ p.scenario }}</dd>
          </div>
        </dl>

        <div v-if="p.proposed_content_md" class="p-proposed">
          <p class="p-proposed-label">建议改写后的内容预览</p>
          <!-- markdown 渲染结果包在容器内，样式由下方 :deep 控制 -->
          <div class="md-body" v-html="renderMd(p.proposed_content_md)"></div>
        </div>
        <details v-if="proposedApis(p)" class="p-apis">
          <summary>建议的 API 列表（结构化）</summary>
          <pre class="mono">{{ proposedApis(p) }}</pre>
        </details>

        <template v-if="p.status === 'submitted'">
          <div class="p-actions">
            <input
              v-model="notes[p.id]"
              class="input p-note"
              type="text"
              placeholder="审批意见（批准可选填，拒绝必填）"
            />
            <button
              type="button"
              class="btn btn-primary"
              :disabled="busy[p.id]"
              @click="resolve(p, 'approve')"
            >
              {{ busy[p.id] ? '处理中…' : '批准并发布' }}
            </button>
            <button
              type="button"
              class="btn btn-danger"
              :disabled="busy[p.id]"
              @click="resolve(p, 'reject')"
            >
              拒绝
            </button>
          </div>
          <p v-if="cardError[p.id]" class="error-text p-error">{{ cardError[p.id] }}</p>
        </template>
        <p v-else class="p-resolution muted">
          审批意见：{{ p.resolution_note || '（未填写）' }}
        </p>
      </article>
    </div>
  </div>
</template>

<style scoped>
.proposals-page {
  max-width: 860px;
}

.state-card {
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

/* ---------- 状态 tab ---------- */

.tabs {
  display: flex;
  gap: var(--sp-1);
  margin-top: var(--sp-5);
  border-bottom: 1px solid var(--hairline);
}

.tab {
  appearance: none;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: var(--sp-2) var(--sp-3);
  font: inherit;
  font-size: var(--text-sm);
  color: var(--ink-2);
  cursor: pointer;
  margin-bottom: -1px;
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

.flash {
  margin-top: var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  border: 1px solid var(--success);
  border-radius: var(--radius);
  color: var(--success);
  background: color-mix(in srgb, var(--success) 6%, var(--card));
  font-size: var(--text-sm);
}

/* ---------- 提案卡片 ---------- */

.proposal-list {
  margin-top: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.proposal-card {
  padding: var(--sp-4) var(--sp-5);
}

.p-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  padding-bottom: var(--sp-3);
  border-bottom: 1px solid var(--hairline);
}

.p-id {
  color: var(--ink-2);
  font-size: var(--text-sm);
}

.p-block {
  font-weight: 600;
  font-size: var(--text-md);
}

.p-status {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--hairline);
  color: var(--ink-2);
  white-space: nowrap;
}

.p-status.is-submitted {
  color: var(--warning);
  border-color: var(--warning);
  background: color-mix(in srgb, var(--warning) 7%, var(--card));
}

.p-status.is-published {
  color: var(--success);
  border-color: var(--success);
}

.p-status.is-rejected {
  color: var(--danger);
  border-color: var(--danger);
}

.p-author {
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.p-time {
  margin-left: auto;
  font-size: var(--text-xs);
}

.p-body {
  margin: var(--sp-3) 0 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.p-field {
  display: flex;
  gap: var(--sp-3);
  font-size: var(--text-sm);
}

.p-field dt {
  flex: 0 0 3em;
  font-weight: 600;
  color: var(--ink-2);
}

.p-field dd {
  margin: 0;
  min-width: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ---------- proposed 内容预览 ---------- */

.p-proposed {
  margin-top: var(--sp-3);
}

.p-proposed-label {
  font-size: var(--text-xs);
  color: var(--ink-2);
  margin-bottom: var(--sp-2);
}

.md-body {
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  background: var(--paper);
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--text-sm);
  max-height: 320px;
  overflow: auto;
}

.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3) {
  font-size: var(--text-md);
  margin: var(--sp-3) 0 var(--sp-2);
}

.md-body :deep(p) {
  margin: var(--sp-2) 0;
}

.md-body :deep(ul),
.md-body :deep(ol) {
  padding-left: var(--sp-5);
  list-style: disc;
}

.md-body :deep(ol) {
  list-style: decimal;
}

.md-body :deep(pre) {
  background: var(--card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  padding: var(--sp-2) var(--sp-3);
  overflow-x: auto;
  font-size: var(--text-xs);
}

.md-body :deep(code) {
  font-size: var(--text-xs);
}

.p-apis {
  margin-top: var(--sp-3);
  font-size: var(--text-sm);
}

.p-apis summary {
  cursor: pointer;
  color: var(--ink-2);
}

.p-apis pre {
  margin-top: var(--sp-2);
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  padding: var(--sp-3);
  overflow-x: auto;
  font-size: var(--text-xs);
}

/* ---------- 审批操作 ---------- */

.p-actions {
  margin-top: var(--sp-4);
  display: flex;
  gap: var(--sp-2);
  align-items: center;
}

.p-note {
  flex: 1;
  min-width: 200px;
}

.p-error {
  margin-top: var(--sp-2);
}

.p-resolution {
  margin-top: var(--sp-3);
  padding-top: var(--sp-3);
  border-top: 1px solid var(--hairline);
  font-size: var(--text-sm);
}

@media (max-width: 640px) {
  .p-actions {
    flex-wrap: wrap;
  }

  .p-note {
    flex-basis: 100%;
  }
}
</style>

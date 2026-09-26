<script setup>
// 提案收件箱：按状态过滤，待处理提案可批准（应用到草稿并发布）或拒绝（需填理由）。
import { computed, onMounted, ref } from 'vue'
import { marked } from 'marked'
import { api } from '../api/client.js'
import VersionChip from '../components/VersionChip.vue'
import BlockTextDiff from '../components/BlockTextDiff.vue'

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

function apiOps(p) {
  return p.proposed_api_ops?.length ? p.proposed_api_ops : p.proposed_apis_view || []
}

function isEmptyPayload(p) {
  return (
    !p.proposed_content_md &&
    !p.proposed_api_ops?.length &&
    !p.proposed_apis?.length &&
    !p.proposed_rule_ops?.length
  )
}

function entryText(e) {
  if (!e) return ''
  const parts = [e.name]
  if (e.desc) parts.push(e.desc)
  const req = (e.request || []).map((f) => f.name).join(', ')
  const res = (e.response || []).map((f) => f.name).join(', ')
  if (req) parts.push(`请求: ${req}`)
  if (res) parts.push(`响应: ${res}`)
  return parts.join(' · ')
}

function contractChanges(op) {
  const c = op.changes?.contract
  if (!c) return []
  return [...(c.added || []), ...(c.modified || []), ...(c.removed || [])]
}

function textChanges(op) {
  return op.changes?.text || []
}

function hasChanges(op) {
  return contractChanges(op).length > 0 || textChanges(op).length > 0
}

function ruleOpKindLabel(op) {
  return { added: '新增规则', modified: '规则变更', unchanged: '无差异', removed: '删除规则' }[
    op.kind
  ]
}

function ruleOpKindClass(op) {
  return {
    added: 'is-upsert',
    modified: 'is-modified',
    unchanged: '',
    removed: 'is-delete',
  }[op.kind]
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
  if (
    action === 'approve' &&
    isEmptyPayload(p) &&
    !window.confirm(
      `提案 #${p.id} 不含任何内容变更（无改写正文、无 API/规则变更），` +
        '发布将只记录说明并 bump 版本号，正文/接口/规则零变化。确定批准并发布？'
    )
  ) {
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

        <p
          v-if="isEmptyPayload(p)"
          class="p-empty-warning"
          :class="{ 'is-note-only': p.note_only }"
        >
          <template v-if="p.note_only">
            纯说明提案（note_only）：不含内容变更，发布将只记录说明并 bump 版本号。
          </template>
          <template v-else>
            ⚠ 此提案不含内容变更（无改写正文、无 API/规则变更），批准发布将只记录说明并
            bump 版本号，正文/接口/规则零变化。
          </template>
        </p>

        <div v-if="p.proposed_content_md" class="p-proposed">
          <p class="p-proposed-label">建议改写后的内容预览</p>
          <!-- markdown 渲染结果包在容器内，样式由下方 :deep 控制 -->
          <div class="md-body" v-html="renderMd(p.proposed_content_md)"></div>
          <details v-if="p.content_diff" class="p-op-detail p-content-diff">
            <summary>与当前正文的文本差异</summary>
            <BlockTextDiff :text="p.content_diff" />
          </details>
        </div>
        <div v-if="apiOps(p).length" class="p-ops">
          <p class="p-proposed-label">
            <template v-if="p.proposed_api_ops && p.proposed_api_ops.length">
              建议的 API 变更（delta，基于 {{ p.base_version ? `v${p.base_version}` : '未发布版本' }}）
            </template>
            <template v-else>
              建议的 API 变更（整体替换，按 API 分拆{{ p.base_version ? `，对照 v${p.base_version}` : '' }}）
            </template>
          </p>
          <ul class="p-op-list">
            <li v-for="(op, i) in apiOps(p)" :key="i" class="p-op">
              <div class="p-op-head">
                <span class="p-op-badge" :class="`is-${op.op}`">
                  {{ op.op === 'upsert' ? '更新' : '删除' }}
                </span>
                <span class="mono p-op-api">{{ op.api }}</span>
              </div>

              <template v-if="op.op === 'delete'">
                <p class="p-op-note muted">将删除以下当前定义：</p>
                <p v-if="op.current_entry" class="p-op-summary muted">
                  {{ entryText(op.current_entry) }}
                </p>
                <details v-if="op.current_entry" class="p-op-detail">
                  <summary>当前定义 JSON</summary>
                  <pre class="mono">{{ JSON.stringify(op.current_entry, null, 2) }}</pre>
                </details>
              </template>

              <template v-else>
                <div class="p-op-compare">
                  <div class="p-op-side">
                    <p class="p-op-side-label">当前定义</p>
                    <template v-if="op.current_entry">
                      <p class="p-op-summary muted">{{ entryText(op.current_entry) }}</p>
                      <details class="p-op-detail">
                        <summary>字段详情</summary>
                        <pre class="mono">{{ JSON.stringify(op.current_entry, null, 2) }}</pre>
                      </details>
                    </template>
                    <p v-else class="p-op-new muted">新增 API（当前不存在）</p>
                  </div>
                  <div class="p-op-side">
                    <p class="p-op-side-label">提案定义</p>
                    <p class="p-op-summary muted">{{ entryText(op.entry) }}</p>
                    <details class="p-op-detail">
                      <summary>字段详情</summary>
                      <pre class="mono">{{ JSON.stringify(op.entry, null, 2) }}</pre>
                    </details>
                  </div>
                </div>

                <div class="p-op-changes">
                  <p class="p-op-side-label">变更摘要</p>
                  <template v-if="hasChanges(op)">
                    <div v-if="contractChanges(op).length" class="p-change-group">
                      <p class="p-change-title">契约变更</p>
                      <ul>
                        <li v-for="(c, j) in contractChanges(op)" :key="j" class="mono">
                          {{ c }}
                        </li>
                      </ul>
                    </div>
                    <div v-if="textChanges(op).length" class="p-change-group">
                      <p class="p-change-title">文案变更</p>
                      <ul>
                        <li v-for="(c, j) in textChanges(op)" :key="j">
                          <span class="mono">{{ c.path }}</span>：{{ c.old ?? '（无）' }} →
                          {{ c.new ?? '（无）' }}
                        </li>
                      </ul>
                    </div>
                  </template>
                  <p v-else class="muted p-op-nochange">无差异</p>
                </div>
              </template>
            </li>
          </ul>
        </div>

        <div v-if="p.proposed_rule_ops && p.proposed_rule_ops.length" class="p-ops">
          <p class="p-proposed-label">
            建议的规则变更（delta，基于 {{ p.base_version ? `v${p.base_version}` : '未发布版本' }}）
          </p>
          <ul class="p-op-list">
            <li v-for="(op, i) in p.proposed_rule_ops" :key="i" class="p-op">
              <div class="p-op-head">
                <span class="p-op-badge" :class="`is-${op.op}`">
                  {{ op.op === 'upsert' ? '更新' : '删除' }}
                </span>
                <span class="p-op-rule">{{ op.name }}</span>
                <span class="p-op-badge" :class="ruleOpKindClass(op)">
                  {{ ruleOpKindLabel(op) }}
                </span>
              </div>

              <template v-if="op.op === 'delete'">
                <p class="p-op-note muted">将删除以下当前规则：</p>
                <p v-if="op.current_entry" class="p-op-summary muted">
                  {{ op.current_entry.detail }}
                </p>
                <p v-else class="p-op-summary muted">（当前草稿中已不存在该规则）</p>
              </template>

              <template v-else>
                <div class="p-op-compare">
                  <div class="p-op-side">
                    <p class="p-op-side-label">当前详述</p>
                    <p v-if="op.current_entry" class="p-op-summary muted">
                      {{ op.current_entry.detail }}
                    </p>
                    <p v-else class="p-op-new muted">新增规则（当前不存在）</p>
                  </div>
                  <div class="p-op-side">
                    <p class="p-op-side-label">提案详述</p>
                    <p class="p-op-summary muted">{{ op.entry.detail }}</p>
                  </div>
                </div>

                <div v-if="op.detail_diff" class="p-op-changes">
                  <p class="p-op-side-label">详述文本差异</p>
                  <BlockTextDiff :text="op.detail_diff" />
                </div>
              </template>
            </li>
          </ul>
        </div>

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

.p-empty-warning {
  margin: var(--sp-3) 0 0;
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid var(--danger);
  border-radius: var(--radius-sm);
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 6%, var(--card));
  font-size: var(--text-sm);
}

.p-empty-warning.is-note-only {
  border-color: var(--warning);
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 6%, var(--card));
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

/* ---------- delta 变更列表 ---------- */

.p-ops {
  margin-top: var(--sp-3);
}

.p-op-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.p-op {
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--paper);
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--text-sm);
}

.p-op-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.p-op-badge {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--hairline);
  white-space: nowrap;
}

.p-op-badge.is-upsert {
  color: var(--contract);
  border-color: var(--contract);
  background: color-mix(in srgb, var(--contract) 7%, var(--card));
}

.p-op-badge.is-delete {
  color: var(--danger);
  border-color: var(--danger);
  background: color-mix(in srgb, var(--danger) 7%, var(--card));
}

.p-op-badge.is-modified {
  color: var(--warning);
  border-color: var(--warning);
  background: color-mix(in srgb, var(--warning) 7%, var(--card));
}

.p-op-rule {
  font-weight: 600;
  font-size: var(--text-sm);
}

.p-content-diff {
  margin-top: var(--sp-2);
}

.p-op-api {
  font-size: var(--text-xs);
}

.p-op-summary {
  margin: var(--sp-1) 0 0;
  font-size: var(--text-xs);
}

.p-op-note {
  margin: var(--sp-2) 0 0;
  font-size: var(--text-xs);
}

.p-op-compare {
  margin-top: var(--sp-2);
  display: flex;
  gap: var(--sp-3);
}

.p-op-side {
  flex: 1;
  min-width: 0;
}

.p-op-side-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ink-2);
  margin-bottom: var(--sp-1);
}

.p-op-new {
  font-size: var(--text-xs);
}

.p-op-changes {
  margin-top: var(--sp-2);
  padding-top: var(--sp-2);
  border-top: 1px solid var(--hairline);
}

.p-change-group {
  margin-top: var(--sp-1);
}

.p-change-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ink-2);
}

.p-change-group ul {
  margin: var(--sp-1) 0 0;
  padding-left: var(--sp-4);
  list-style: disc;
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.p-change-group li {
  margin: 1px 0;
  word-break: break-all;
}

.p-op-nochange {
  font-size: var(--text-xs);
}

@media (max-width: 640px) {
  .p-op-compare {
    flex-direction: column;
  }
}

.p-op-detail {
  margin-top: var(--sp-1);
}

.p-op-detail summary {
  cursor: pointer;
  color: var(--ink-2);
  font-size: var(--text-xs);
}

.p-op-detail pre {
  margin-top: var(--sp-1);
  background: var(--card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  padding: var(--sp-2) var(--sp-3);
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

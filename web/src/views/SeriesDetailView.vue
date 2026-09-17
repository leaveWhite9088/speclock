<script setup>
/**
 * SeriesDetailView（/meetings/series/:id）—— 业务线详情 + 汇总文档：
 * 哈希码分享（展示/复制/重新生成 + curl 示例）；「从会议刷新汇总」；
 * 两个 Tab（总精准需求 / 总业务事实）= 条目卡片列表（来源徽标：
 * 会议名 · 原编号 或「业务级增加」）+ 逐条编辑（quotes 只读）+ 增删，
 * 保存后展示联动结果（哪条联动了哪个源文件、源文件 bump 到什么版本）；
 * 导出 + 版本历史 + 两版本 diff。
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api, downloadFile } from '../api/client.js'
import MeetingBreadcrumb from '../components/MeetingBreadcrumb.vue'
import VersionChip from '../components/VersionChip.vue'
import BlockTextDiff from '../components/BlockTextDiff.vue'
import {
  ADDABLE_TYPES,
  CHUNK_TYPE_LABELS,
  FIELD_LABELS,
  ITEM_FIELDS,
  STATUS_LABELS,
  STATUS_OPTIONS,
  errText,
  fmtTime,
} from '../meetingMeta.js'

const route = useRoute()
const sid = route.params.id

const series = ref(null)
const loading = ref(true)
const loadError = ref('')

const tokenCopied = ref(false)
const curlCopied = ref(false)
const regenerating = ref(false)

const refreshing = ref(false)
const refreshMsg = ref('')

const activeKind = ref('requirements')
const doc = ref(null) // 当前 Tab 文档详情
const docLoading = ref(false)

const draftItems = ref([])
const saving = ref(false)
const saveError = ref('')
const saveResult = ref(null) // { version, bump, links }
const newType = ref('req')

const fromV = ref('')
const toV = ref('')
const diffText = ref('')
const diffError = ref('')

const vFocus = { mounted: (el) => el.focus() }

const shareUrl = computed(() =>
  series.value?.share_token
    ? `${window.location.origin}/api/share/${series.value.share_token}`
    : '',
)
const curlCmd = computed(() => (shareUrl.value ? `curl "${shareUrl.value}"` : ''))

const activeDocMeta = computed(
  () => series.value?.docs.find((d) => d.kind === activeKind.value) || null,
)

async function copyText(text, which) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  if (which === 'token') tokenCopied.value = true
  else curlCopied.value = true
  setTimeout(() => {
    tokenCopied.value = false
    curlCopied.value = false
  }, 1500)
}

function toDraft(i) {
  const fields = { ...i.fields }
  delete fields.quotes // quotes 只读展示，不提交（后端按 ref_id 继承）
  return {
    ref_id: i.ref_id,
    chunk_type: i.chunk_type,
    section: i.section,
    fields,
    quotes: i.fields.quotes || [],
    origin_label: i.origin_label,
    isNew: false,
  }
}

async function loadDoc() {
    const meta = activeDocMeta.value
    doc.value = null
    if (!meta) return
    docLoading.value = true
    try {
      doc.value = await api.get(`/series-docs/${meta.id}`)
      draftItems.value = doc.value.items.map(toDraft)
      newType.value = ADDABLE_TYPES[doc.value.kind]?.[0] || 'req'
      const vs = doc.value.versions
      fromV.value = vs.at(-2)?.version || ''
      toV.value = vs.at(-1)?.version || ''
      diffText.value = ''
    } catch (e) {
      loadError.value = errText(e)
    } finally {
      docLoading.value = false
    }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    series.value = await api.get(`/meeting-series/${sid}`)
    await loadDoc()
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function setTab(kind) {
  if (activeKind.value === kind) return
  activeKind.value = kind
  saveResult.value = null
  saveError.value = ''
  loadDoc()
}

async function regenerate() {
  if (!window.confirm('重新生成后旧哈希码立即失效，已发给 AI 的链接都会 404。确定继续？'))
    return
  regenerating.value = true
  try {
    const res = await api.post(`/meeting-series/${sid}/share-token/regenerate`)
    series.value.share_token = res.share_token
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    regenerating.value = false
  }
}

async function refresh() {
  refreshing.value = true
  refreshMsg.value = ''
  try {
    const res = await api.post(`/meeting-series/${sid}/refresh-docs`)
    const parts = res.docs.map(
      (d) => `${d.kind === 'requirements' ? '总精准需求' : '总业务事实'} +${d.added} 条`,
    )
    refreshMsg.value = `刷新完成：${parts.join('，')}`
    await load()
  } catch (e) {
    refreshMsg.value = errText(e)
  } finally {
    refreshing.value = false
  }
}

function removeDraft(i) {
  draftItems.value.splice(i, 1)
}

function addDraft() {
  const last = draftItems.value.filter((c) => c.chunk_type !== 'prose').at(-1)
  draftItems.value.push({
    ref_id: null,
    chunk_type: newType.value,
    section: last ? last.section : '',
    fields: {},
    quotes: [],
    origin_label: '业务级增加',
    isNew: true,
  })
}

async function saveItems() {
  saving.value = true
  saveError.value = ''
  saveResult.value = null
  try {
    const res = await api.put(`/series-docs/${doc.value.id}/items`, {
      items: draftItems.value.map((c) => ({
        ref_id: c.ref_id,
        chunk_type: c.chunk_type,
        section: c.section,
        fields: c.fields,
      })),
    })
    saveResult.value = res
    await load()
  } catch (e) {
    saveError.value = errText(e)
  } finally {
    saving.value = false
  }
}

async function runDiff() {
  diffText.value = ''
  diffError.value = ''
  if (!fromV.value || !toV.value || fromV.value === toV.value) return
  try {
    const res = await api.get(
      `/series-docs/${doc.value.id}/diff?from=${encodeURIComponent(fromV.value)}&to=${encodeURIComponent(toV.value)}`,
    )
    diffText.value = res.diff
  } catch (e) {
    diffError.value = errText(e)
  }
}

async function exportDoc() {
  try {
    await downloadFile(`/series-docs/${doc.value.id}/export`)
  } catch (e) {
    loadError.value = errText(e)
  }
}

const LINK_ACTION_LABELS = { added: '新增', updated: '联动更新', deleted: '联动删除' }
</script>

<template>
  <div class="page series-page">
    <div v-if="loading" class="muted">正在加载…</div>

    <div v-else-if="loadError && !series" class="card load-fail">
      <p class="error-text" role="alert">{{ loadError }}</p>
      <button type="button" class="btn" @click="load">重新加载</button>
    </div>

    <template v-else-if="series">
      <MeetingBreadcrumb
        :items="[{ label: '会议记录', to: '/meetings' }, { label: series.name }]"
      />
      <div class="head">
        <h1 class="page-title">{{ series.name }}</h1>
        <button type="button" class="btn btn-primary" :disabled="refreshing" @click="refresh">
          {{ refreshing ? '刷新中…' : '从会议刷新汇总' }}
        </button>
      </div>
      <p class="page-desc">
        业务线下 {{ series.meetings.length }} 个会议。汇总文档由各会议的精准需求 / 业务事实
        条目合并而成；在这里改 / 删有来源的条目会联动源会议文件。
      </p>
      <p v-if="refreshMsg" class="muted refresh-msg" role="status">{{ refreshMsg }}</p>

      <!-- 哈希码分享 -->
      <section class="section">
        <h2 class="section-title">哈希码分享</h2>
        <div class="card section-card">
          <div class="token-row">
            <code class="mono token">{{ series.share_token }}</code>
            <button type="button" class="btn" @click="copyText(series.share_token, 'token')">
              {{ tokenCopied ? '已复制 ✓' : '复制' }}
            </button>
            <button type="button" class="btn btn-danger" :disabled="regenerating" @click="regenerate">
              {{ regenerating ? '生成中…' : '重新生成' }}
            </button>
          </div>
          <pre class="code-pre mono">{{ curlCmd }}</pre>
          <button type="button" class="btn" @click="copyText(curlCmd, 'curl')">
            {{ curlCopied ? '已复制到剪贴板 ✓' : '复制 curl 命令' }}
          </button>
          <p class="muted hint">
            拿到链接的人可只读访问两个汇总文档（条目带来源行）；「AI 接入 › 会议记录分享」页可生成提示词模板。
          </p>
        </div>
      </section>

      <!-- 汇总文档 Tab -->
      <section class="section">
        <div class="tab-bar" role="tablist">
          <button
            v-for="k in ['requirements', 'facts']"
            :key="k"
            type="button"
            class="tab"
            :class="{ 'is-active': activeKind === k }"
            role="tab"
            :aria-selected="activeKind === k"
            @click="setTab(k)"
          >
            {{ k === 'requirements' ? '总精准需求' : '总业务事实' }}
            <template v-if="series.docs.find((d) => d.kind === k)">
              （{{ series.docs.find((d) => d.kind === k).item_count }} 条 · v{{ series.docs.find((d) => d.kind === k).current_version }}）
            </template>
          </button>
        </div>

        <div v-if="!activeDocMeta" class="card empty">
          <p class="muted">还没有汇总文档。点右上角「从会议刷新汇总」生成。</p>
        </div>
        <div v-else-if="docLoading" class="muted loading-doc">正在加载文档…</div>

        <template v-else-if="doc">
          <div v-if="saveResult" class="card save-banner" role="status">
            <span>
              已保存：{{ saveResult.bump.toUpperCase() }} →
            </span>
            <VersionChip :version="saveResult.version" />
          </div>
          <div v-if="saveResult?.links?.length" class="card links-card">
            <p class="links-title">联动结果：</p>
            <ul class="links-list">
              <li v-for="(l, i) in saveResult.links" :key="i" class="link-row">
                <span class="mono">{{ l.ref_id }}</span>
                <span class="link-action">{{ LINK_ACTION_LABELS[l.action] || l.action }}</span>
                <span class="muted">{{ l.origin }}</span>
                <span v-if="l.source_file" class="muted">
                  → <span class="mono">{{ l.source_file }}</span>
                  <template v-if="l.source_version"> v{{ l.source_version }}</template>
                </span>
                <span v-else-if="l.action !== 'added'" class="muted">→ 源已不存在，仅改汇总文档</span>
              </li>
            </ul>
          </div>
          <p v-if="saveError" class="error-text" role="alert">{{ saveError }}</p>

          <div class="chunk-list">
            <div
              v-for="(c, i) in draftItems"
              :key="i"
              class="card chunk-card"
              :class="{ 'is-prose': c.chunk_type === 'prose', 'is-new': c.isNew }"
            >
              <template v-if="c.chunk_type === 'prose'">
                <div class="chunk-head">
                  <span class="chunk-badge prose-badge">散文节</span>
                  <span class="muted mono chunk-section">{{ c.section }}</span>
                </div>
                <pre class="prose-pre mono">{{ c.fields.raw }}</pre>
              </template>

              <template v-else>
                <div class="chunk-head">
                  <span class="chunk-badge">{{ CHUNK_TYPE_LABELS[c.chunk_type] }}</span>
                  <span class="mono ref-id">{{ c.ref_id || '（保存时分配编号）' }}</span>
                  <span
                    class="origin-badge"
                    :class="{ 'is-business': c.origin_label === '业务级增加' }"
                  >
                    {{ c.origin_label }}
                  </span>
                  <span class="muted mono chunk-section">{{ c.section }}</span>
                  <button type="button" class="btn btn-danger btn-del" @click="removeDraft(i)">
                    删除条目
                  </button>
                </div>

                <div class="field-grid">
                  <template v-for="key in ITEM_FIELDS[c.chunk_type]" :key="key">
                    <label class="label field-label">{{ FIELD_LABELS[key] }}</label>
                    <select v-if="key === 'status'" class="input" v-model="c.fields.status">
                      <option value="">（未设置）</option>
                      <option v-for="s in STATUS_OPTIONS" :key="s" :value="s">
                        {{ STATUS_LABELS[s] }}
                      </option>
                    </select>
                    <textarea
                      v-else-if="key === 'statement' || key === 'question'"
                      class="input field-textarea"
                      rows="2"
                      v-model="c.fields[key]"
                    ></textarea>
                    <input v-else class="input" v-model="c.fields[key]" />
                  </template>
                  <label class="label field-label">所属分节</label>
                  <input class="input" v-model="c.section" />
                </div>

                <div v-if="c.quotes.length" class="quotes">
                  <p class="muted quotes-title">原文引用（只读）：</p>
                  <ul class="quote-list">
                    <li v-for="(q, qi) in c.quotes" :key="qi" class="quote-item">
                      <span class="quote-text">"{{ q.quote }}"</span>
                      <span class="muted mono quote-meta">{{ q.at }} · {{ q.speaker }}</span>
                    </li>
                  </ul>
                </div>
              </template>
            </div>
          </div>

          <div class="card add-bar">
            <select class="input add-type" v-model="newType">
              <option v-for="t in ADDABLE_TYPES[doc.kind]" :key="t" :value="t">
                {{ CHUNK_TYPE_LABELS[t] }}（{{ { req: 'REQ', con: 'CON', act: 'ACT', q: 'Q', fact: 'FACT' }[t] }}-）
              </option>
            </select>
            <button type="button" class="btn" @click="addDraft">新增条目（业务级）</button>
            <span class="muted add-hint">
              改 / 删有来源的条目会联动源会议文件（改 → 源 PATCH，删 → 源 MAJOR）
            </span>
            <button type="button" class="btn" @click="exportDoc">导出 Markdown</button>
            <button
              type="button"
              class="btn btn-primary save-btn"
              :disabled="saving"
              @click="saveItems"
            >
              {{ saving ? '保存中…' : '保存全部修改' }}
            </button>
          </div>

          <!-- 版本历史 + diff -->
          <section class="section">
            <h2 class="section-title">版本历史（{{ doc.versions.length }}）</h2>
            <div class="card section-card">
              <ul class="ver-list">
                <li v-for="v in doc.versions" :key="v.version" class="ver-row">
                  <VersionChip :version="v.version" />
                  <span class="ver-bump mono">{{ v.source === 'refresh' ? '刷新' : v.bump }}</span>
                  <span class="muted ver-note">{{ v.change_note || '—' }}</span>
                  <span class="muted ver-meta">{{ v.created_by }} · {{ fmtTime(v.created_at) }}</span>
                </li>
              </ul>
              <div v-if="doc.versions.length >= 2" class="diff-bar">
                <label class="sel">
                  <span class="sel-label mono">from</span>
                  <select class="input" v-model="fromV">
                    <option v-for="v in doc.versions" :key="v.version" :value="v.version">
                      v{{ v.version }}
                    </option>
                  </select>
                </label>
                <span class="arrow mono">→</span>
                <label class="sel">
                  <span class="sel-label mono">to</span>
                  <select class="input" v-model="toV">
                    <option v-for="v in doc.versions" :key="v.version" :value="v.version">
                      v{{ v.version }}
                    </option>
                  </select>
                </label>
                <button
                  type="button"
                  class="btn"
                  :disabled="!fromV || !toV || fromV === toV"
                  @click="runDiff"
                >
                  对比
                </button>
              </div>
              <p v-if="diffError" class="error-text" role="alert">{{ diffError }}</p>
              <BlockTextDiff v-if="diffText" :text="diffText" />
            </div>
          </section>
        </template>
      </section>

      <p v-if="loadError" class="error-text" role="alert">{{ loadError }}</p>
    </template>
  </div>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
}

.refresh-msg {
  margin-top: var(--sp-2);
  font-size: var(--text-sm);
}

.section {
  margin-top: var(--sp-5);
}

.section-title {
  font-size: var(--text-lg);
  font-weight: 600;
  margin-bottom: var(--sp-3);
}

.section-card {
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.token-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.token {
  font-size: var(--text-xs);
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  padding: 4px var(--sp-2);
  word-break: break-all;
}

.code-pre {
  margin: 0;
  width: 100%;
  padding: var(--sp-3) var(--sp-4);
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  font-size: var(--text-xs);
  white-space: pre-wrap;
  word-break: break-all;
}

.hint {
  font-size: var(--text-xs);
}

.empty {
  margin-top: var(--sp-3);
  padding: var(--sp-5);
  border-style: dashed;
}

.loading-doc {
  margin-top: var(--sp-4);
}

/* ---------- Tab（与 McpView 同款） ---------- */

.tab-bar {
  display: flex;
  gap: var(--sp-1);
  border-bottom: 1px solid var(--hairline);
  margin-bottom: var(--sp-4);
}

.tab {
  appearance: none;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: 7px var(--sp-3);
  font: inherit;
  font-size: var(--text-sm);
  color: var(--ink-2);
  cursor: pointer;
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

/* ---------- 条目卡片（与 MeetingFileView 同款） ---------- */

.save-banner {
  margin-bottom: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-sm);
  border-color: var(--success);
}

.links-card {
  margin-bottom: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
}

.links-title {
  font-size: var(--text-sm);
  font-weight: 500;
}

.links-list {
  margin-top: var(--sp-2);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.link-row {
  font-size: var(--text-xs);
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.link-action {
  color: var(--contract);
}

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.chunk-card {
  padding: var(--sp-3) var(--sp-4);
}

.chunk-card.is-prose {
  background: var(--paper);
}

.chunk-card.is-new {
  border-style: dashed;
  border-color: var(--contract);
}

.chunk-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
  flex-wrap: wrap;
}

.chunk-badge {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border: 1px solid var(--contract);
  border-radius: var(--radius-sm);
  color: var(--contract);
  background: var(--contract-wash);
  white-space: nowrap;
}

.prose-badge {
  border-color: var(--hairline);
  color: var(--ink-2);
  background: var(--card);
}

.ref-id {
  font-size: var(--text-sm);
  font-weight: 600;
}

.origin-badge {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--paper);
  color: var(--ink-2);
  white-space: nowrap;
}

.origin-badge.is-business {
  color: var(--warning);
  border-color: var(--warning);
}

.chunk-section {
  font-size: var(--text-xs);
}

.btn-del {
  margin-left: auto;
  font-size: var(--text-xs);
  padding: 3px var(--sp-3);
}

.prose-pre {
  font-size: var(--text-xs);
  color: var(--ink-2);
  white-space: pre-wrap;
  margin: 0;
}

.field-grid {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: var(--sp-2) var(--sp-3);
  align-items: center;
}

.field-label {
  margin-bottom: 0;
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.field-textarea {
  resize: vertical;
}

.quotes {
  margin-top: var(--sp-3);
  border-top: 1px solid var(--hairline);
  padding-top: var(--sp-2);
}

.quotes-title {
  font-size: var(--text-xs);
}

.quote-list {
  margin-top: var(--sp-1);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.quote-item {
  font-size: var(--text-xs);
  display: flex;
  flex-direction: column;
}

.quote-meta {
  color: var(--ink-2);
}

.add-bar {
  margin-top: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.add-type {
  width: auto;
}

.add-hint {
  font-size: var(--text-xs);
}

.save-btn {
  margin-left: auto;
}

/* ---------- 版本历史 ---------- */

.ver-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.ver-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-sm);
  flex-wrap: wrap;
}

.ver-bump {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--paper);
}

.ver-note,
.ver-meta {
  font-size: var(--text-xs);
}

.ver-meta {
  margin-left: auto;
}

.diff-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  border-top: 1px solid var(--hairline);
  padding-top: var(--sp-3);
  width: 100%;
}

.sel {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
}

.sel-label {
  font-size: var(--text-xs);
  color: var(--ink-2);
  letter-spacing: 0.06em;
}

.sel .input {
  width: auto;
  padding: 4px var(--sp-2);
}

.arrow {
  color: var(--ink-2);
}
</style>

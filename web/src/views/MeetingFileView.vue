<script setup>
/**
 * MeetingFileView（/meetings/:id/files/:fileId）—— 文件详情：
 * 切块文件（精准需求/业务事实）= 块卡片列表 + 逐块编辑（quotes 只读）+ 增删条目，
 * 保存时展示后端自动算的 bump 与新版本号；非切块文件 = Markdown 预览 + 整篇
 * textarea 编辑 + 手选 bump。底部版本列表 + 两版本 diff + 导出。
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api, downloadFile } from '../api/client.js'
import VersionChip from '../components/VersionChip.vue'
import BlockTextDiff from '../components/BlockTextDiff.vue'
import MeetingBreadcrumb from '../components/MeetingBreadcrumb.vue'
import {
  ADDABLE_TYPES,
  CHUNK_TYPE_LABELS,
  FIELD_LABELS,
  ITEM_FIELDS,
  PARSE_LABELS,
  STATUS_LABELS,
  STATUS_OPTIONS,
  errText,
  fmtTime,
} from '../meetingMeta.js'

const route = useRoute()
const mid = route.params.id
const fid = route.params.fileId

const file = ref(null)
const meeting = ref(null) // 面包屑用（会议名 / 业务线名）
const loading = ref(true)
const loadError = ref('')

const isChunked = computed(
  () => file.value && ['requirements', 'facts'].includes(file.value.kind),
)

// ---------- 切块编辑 ----------

const draftChunks = ref([])
const saving = ref(false)
const saveError = ref('')
const saveResult = ref(null) // { bump, version }
const newType = ref('req')

function toDraft(c) {
  const fields = { ...c.fields }
  delete fields.quotes // quotes 只读展示，不提交（后端按 ref_id 继承）
  return {
    ref_id: c.ref_id,
    chunk_type: c.chunk_type,
    section: c.section,
    fields,
    quotes: c.fields.quotes || [],
    isNew: false,
  }
}

function removeDraft(i) {
  draftChunks.value.splice(i, 1)
}

function addDraft() {
  const last = draftChunks.value.filter((c) => c.chunk_type !== 'prose').at(-1)
  draftChunks.value.push({
    ref_id: null,
    chunk_type: newType.value,
    section: last ? last.section : '',
    fields: {},
    quotes: [],
    isNew: true,
  })
}

async function saveChunks() {
  saving.value = true
  saveError.value = ''
  saveResult.value = null
  try {
    const res = await api.put(`/files/${fid}/chunks`, {
      chunks: draftChunks.value.map((c) => ({
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

// ---------- 整篇编辑（非切块文件） ----------

const editingContent = ref(false)
const contentDraft = ref('')
const bumpChoice = ref('patch')
const changeNote = ref('')

const BUMP_LABELS = {
  major: 'MAJOR（删条目级的大改）',
  minor: 'MINOR（新增内容）',
  patch: 'PATCH（修订措辞）',
}

function startContentEdit() {
  contentDraft.value = file.value.content_md
  bumpChoice.value = 'patch'
  changeNote.value = ''
  saveResult.value = null
  editingContent.value = true
}

async function saveContent() {
  saving.value = true
  saveError.value = ''
  saveResult.value = null
  try {
    const res = await api.put(`/files/${fid}/content`, {
      content: contentDraft.value,
      bump: bumpChoice.value,
      change_note: changeNote.value,
    })
    saveResult.value = res
    editingContent.value = false
    await load()
  } catch (e) {
    saveError.value = errText(e)
  } finally {
    saving.value = false
  }
}

// ---------- 版本与 diff ----------

const fromV = ref('')
const toV = ref('')
const diffText = ref('')
const diffLoading = ref(false)
const diffError = ref('')

async function runDiff() {
  diffText.value = ''
  diffError.value = ''
  if (!fromV.value || !toV.value || fromV.value === toV.value) return
  diffLoading.value = true
  try {
    const res = await api.get(
      `/files/${fid}/diff?from=${encodeURIComponent(fromV.value)}&to=${encodeURIComponent(toV.value)}`,
    )
    diffText.value = res.diff
  } catch (e) {
    diffError.value = errText(e)
  } finally {
    diffLoading.value = false
  }
}

async function exportCurrent() {
  try {
    await downloadFile(`/files/${fid}/export`)
  } catch (e) {
    loadError.value = errText(e)
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    ;[file.value, meeting.value] = await Promise.all([
      api.get(`/files/${fid}`),
      api.get(`/meetings/${mid}`),
    ])
    draftChunks.value = file.value.chunks.map(toDraft)
    newType.value = ADDABLE_TYPES[file.value.kind]?.[0] || 'req'
    const vs = file.value.versions
    fromV.value = vs.at(-2)?.version || ''
    toV.value = vs.at(-1)?.version || ''
    diffText.value = ''
    editingContent.value = false
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page file-page">
    <div v-if="loading" class="muted">正在加载…</div>

    <div v-else-if="loadError && !file" class="card load-fail">
      <p class="error-text" role="alert">{{ loadError }}</p>
      <button type="button" class="btn" @click="load">重新加载</button>
    </div>

    <template v-else-if="file">
      <MeetingBreadcrumb
        :items="[
          { label: '会议记录', to: '/meetings' },
          ...(meeting ? [{ label: meeting.series_name }] : []),
          { label: meeting?.name || '会议', to: `/meetings/${mid}` },
          { label: file.filename },
        ]"
      />
      <h1 class="page-title mono file-title">{{ file.filename }}</h1>
      <p class="page-desc">
        <span class="muted">{{ file.kind_label }} · </span>
        <VersionChip :version="file.current_version" />
        <span class="muted"> · {{ PARSE_LABELS[file.parse_status] || file.parse_status }}</span>
      </p>

      <!-- 解析失败：突出展示报错（可直接贴给 agent 修源文件） -->
      <div v-if="file.parse_status === 'failed'" class="card fail-card">
        <p class="fail-title">源文件解析失败，未切块。把下面的报错贴给 agent 修源文件后重新上传同名文件即可。</p>
        <pre class="fail-pre mono">{{ file.parse_error }}</pre>
      </div>

      <div v-if="saveResult" class="card save-banner" role="status">
        已保存：{{ saveResult.bump.toUpperCase() }} →
        <VersionChip :version="saveResult.version" />
      </div>
      <p v-if="saveError" class="error-text" role="alert">{{ saveError }}</p>

      <!-- 切块文件：块卡片编辑 -->
      <template v-if="isChunked && file.parse_status === 'ok'">
        <section class="section">
          <div class="chunk-list">
            <div
              v-for="(c, i) in draftChunks"
              :key="i"
              class="card chunk-card"
              :class="{ 'is-prose': c.chunk_type === 'prose', 'is-new': c.isNew }"
            >
              <template v-if="c.chunk_type === 'prose'">
                <div class="chunk-head">
                  <span class="chunk-badge">散文节</span>
                  <span class="muted mono chunk-section">{{ c.section }}</span>
                </div>
                <pre class="prose-pre mono">{{ c.fields.raw }}</pre>
              </template>

              <template v-else>
                <div class="chunk-head">
                  <span class="chunk-badge">{{ CHUNK_TYPE_LABELS[c.chunk_type] }}</span>
                  <span class="mono ref-id">{{ c.ref_id || '（保存时分配编号）' }}</span>
                  <span class="muted mono chunk-section">{{ c.section }}</span>
                  <button
                    type="button"
                    class="btn btn-danger btn-del"
                    @click="removeDraft(i)"
                  >
                    删除条目
                  </button>
                </div>

                <div class="field-grid">
                  <template v-for="key in ITEM_FIELDS[c.chunk_type]" :key="key">
                    <label class="label field-label">{{ FIELD_LABELS[key] }}</label>
                    <select
                      v-if="key === 'status'"
                      class="input"
                      v-model="c.fields.status"
                    >
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
                  <input class="input" v-model="c.section" placeholder="如：一、分组A" />
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
              <option v-for="t in ADDABLE_TYPES[file.kind]" :key="t" :value="t">
                {{ CHUNK_TYPE_LABELS[t] }}（{{ { req: 'REQ', con: 'CON', act: 'ACT', q: 'Q', fact: 'FACT' }[t] }}-）
              </option>
            </select>
            <button type="button" class="btn" @click="addDraft">新增条目</button>
            <span class="muted add-hint">
              删条目 → MAJOR，增条目 → MINOR，仅改字段 → PATCH（保存时自动算）
            </span>
            <button
              type="button"
              class="btn btn-primary save-btn"
              :disabled="saving"
              @click="saveChunks"
            >
              {{ saving ? '保存中…' : '保存全部修改' }}
            </button>
          </div>
        </section>
      </template>

      <!-- 非切块文件 / 解析失败文件：整篇查看与编辑 -->
      <template v-else>
        <section class="section">
          <div v-if="!editingContent" class="card content-card">
            <pre class="content-pre mono">{{ file.content_md }}</pre>
            <div class="content-ops">
              <button
                v-if="!isChunked"
                type="button"
                class="btn btn-primary"
                @click="startContentEdit"
              >
                编辑整篇内容
              </button>
            </div>
          </div>

          <div v-else class="card content-card">
            <textarea class="input content-textarea mono" v-model="contentDraft" rows="24"></textarea>
            <div class="content-edit-bar">
              <label class="label bump-label">版本步进</label>
              <select class="input bump-select" v-model="bumpChoice">
                <option v-for="(label, b) in BUMP_LABELS" :key="b" :value="b">{{ label }}</option>
              </select>
              <input
                class="input note-input"
                v-model="changeNote"
                placeholder="变更说明（可选）"
              />
              <button
                type="button"
                class="btn btn-primary"
                :disabled="saving"
                @click="saveContent"
              >
                {{ saving ? '保存中…' : '保存为新版本' }}
              </button>
              <button type="button" class="btn" @click="editingContent = false">取消</button>
            </div>
          </div>
        </section>
      </template>

      <!-- 版本历史 + diff + 导出 -->
      <section class="section">
        <h2 class="section-title">版本历史（{{ file.versions.length }}）</h2>
        <div class="card section-card">
          <ul class="ver-list">
            <li v-for="v in file.versions" :key="v.version" class="ver-row">
              <VersionChip :version="v.version" />
              <span class="ver-bump mono">{{ v.source === 'upload' ? '上传' : v.bump }}</span>
              <span class="muted ver-note">{{ v.change_note || '—' }}</span>
              <span class="muted ver-meta">{{ v.created_by }} · {{ fmtTime(v.created_at) }}</span>
            </li>
          </ul>

          <div v-if="file.versions.length >= 2" class="diff-bar">
            <label class="sel">
              <span class="sel-label mono">from</span>
              <select class="input" v-model="fromV">
                <option v-for="v in file.versions" :key="v.version" :value="v.version">
                  v{{ v.version }}
                </option>
              </select>
            </label>
            <span class="arrow mono">→</span>
            <label class="sel">
              <span class="sel-label mono">to</span>
              <select class="input" v-model="toV">
                <option v-for="v in file.versions" :key="v.version" :value="v.version">
                  v{{ v.version }}
                </option>
              </select>
            </label>
            <button
              type="button"
              class="btn"
              :disabled="diffLoading || !fromV || !toV || fromV === toV"
              @click="runDiff"
            >
              {{ diffLoading ? '对比中…' : '对比' }}
            </button>
            <button type="button" class="btn export-btn" @click="exportCurrent">
              导出当前版本
            </button>
          </div>
          <div v-else class="diff-bar">
            <span class="muted">再编辑一版后可对比差异。</span>
            <button type="button" class="btn export-btn" @click="exportCurrent">
              导出当前版本
            </button>
          </div>

          <p v-if="diffError" class="error-text" role="alert">{{ diffError }}</p>
          <BlockTextDiff v-if="diffText" :text="diffText" />
        </div>
      </section>

      <p v-if="loadError" class="error-text" role="alert">{{ loadError }}</p>
    </template>
  </div>
</template>

<style scoped>
.file-title {
  font-size: var(--text-lg);
  word-break: break-all;
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
  gap: var(--sp-3);
}

.fail-card {
  margin-top: var(--sp-4);
  padding: var(--sp-4) var(--sp-5);
  border-color: var(--danger);
}

.fail-title {
  color: var(--danger);
  font-weight: 500;
  font-size: var(--text-sm);
}

.fail-pre {
  margin-top: var(--sp-2);
  padding: var(--sp-3);
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  font-size: var(--text-xs);
  white-space: pre-wrap;
}

.save-banner {
  margin-top: var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-sm);
  border-color: var(--success);
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

.is-prose .chunk-badge {
  border-color: var(--hairline);
  color: var(--ink-2);
  background: var(--card);
}

.ref-id {
  font-size: var(--text-sm);
  font-weight: 600;
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

.content-card {
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.content-pre {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.7;
  white-space: pre-wrap;
}

.content-textarea {
  font-size: var(--text-xs);
  line-height: 1.7;
  resize: vertical;
}

.content-edit-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.bump-label {
  margin-bottom: 0;
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.bump-select {
  width: auto;
}

.note-input {
  flex: 1;
  min-width: 160px;
}

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

.ver-note {
  font-size: var(--text-xs);
}

.ver-meta {
  font-size: var(--text-xs);
  margin-left: auto;
}

.diff-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  border-top: 1px solid var(--hairline);
  padding-top: var(--sp-3);
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

.export-btn {
  margin-left: auto;
}
</style>

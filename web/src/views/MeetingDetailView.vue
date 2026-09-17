<script setup>
/**
 * MeetingDetailView（/meetings/:id）—— 会议详情：文件分两组（标准文件固定
 * 顺序 / 其他文件）卡片列表，支持页内上传（MeetingUpload）、重命名（PATCH，
 * kind 自动重识别）、删除（DELETE）；哈希码展示 + 复制 + 重新生成、分享范围
 * 勾选、导出 zip。
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, downloadFile } from '../api/client.js'
import VersionChip from '../components/VersionChip.vue'
import MeetingUpload from '../components/MeetingUpload.vue'
import MeetingBreadcrumb from '../components/MeetingBreadcrumb.vue'
import {
  KIND_LABELS,
  PARSE_LABELS,
  SHAREABLE_KINDS,
  errText,
} from '../meetingMeta.js'

const route = useRoute()
const router = useRouter()
const mid = route.params.id

const meeting = ref(null)
const loading = ref(true)
const loadError = ref('')

const kinds = ref([])
const kindsSaving = ref(false)
const kindsMsg = ref('')

const curlCopied = ref(false)
const regenerating = ref(false)
const exporting = ref(false)

// curl 命令带完整 URL（含哈希码），是唯一展示 token 的地方
const curlCmd = computed(() =>
  meeting.value?.share_token
    ? `curl "${window.location.origin}/api/share/${meeting.value.share_token}"`
    : '',
)

// 标准文件固定展示顺序（其余 kind=other 进「其他文件」组）
const STANDARD_ORDER = ['transcript', 'requirements', 'facts', 'confirm', 'questions', 'glossary']

const standardFiles = computed(() => {
  if (!meeting.value) return []
  const rank = (f) => STANDARD_ORDER.indexOf(f.kind)
  return meeting.value.files
    .filter((f) => STANDARD_ORDER.includes(f.kind))
    .sort((a, b) => rank(a) - rank(b) || a.id - b.id)
})
const otherFiles = computed(() =>
  meeting.value ? meeting.value.files.filter((f) => !STANDARD_ORDER.includes(f.kind)) : [],
)

const renamingId = ref(null)
const renameValue = ref('')
const fileError = ref('')

const editingMeeting = ref(false)
const meetingForm = ref({ name: '', date: '' })
const meetingSaving = ref(false)
const meetingError = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    meeting.value = await api.get(`/meetings/${mid}`)
    kinds.value = [...meeting.value.share_kinds]
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function copyCurl() {
  try {
    await navigator.clipboard.writeText(curlCmd.value)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = curlCmd.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  curlCopied.value = true
  setTimeout(() => (curlCopied.value = false), 1500)
}

async function regenerate() {
  if (
    !window.confirm('重新生成后旧哈希码立即失效，已发给 AI 的链接都会 404。确定继续？')
  )
    return
  regenerating.value = true
  try {
    const res = await api.post(`/meetings/${mid}/share-token/regenerate`)
    meeting.value.share_token = res.share_token
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    regenerating.value = false
  }
}

async function saveKinds() {
  kindsSaving.value = true
  kindsMsg.value = ''
  try {
    const res = await api.put(`/meetings/${mid}/share-kinds`, { kinds: kinds.value })
    meeting.value.share_kinds = res.share_kinds
    kindsMsg.value = '已保存 ✓'
    setTimeout(() => (kindsMsg.value = ''), 1500)
  } catch (e) {
    kindsMsg.value = errText(e)
  } finally {
    kindsSaving.value = false
  }
}

async function exportZip() {
  exporting.value = true
  try {
    await downloadFile(`/meetings/${mid}/export`)
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    exporting.value = false
  }
}

function startRename(f) {
  renamingId.value = f.id
  renameValue.value = f.filename
  fileError.value = ''
}

async function saveRename(f) {
  const filename = renameValue.value.trim()
  if (!filename || filename === f.filename) {
    renamingId.value = null
    return
  }
  try {
    await api.patch(`/files/${f.id}`, { filename })
    renamingId.value = null
    await load()
  } catch (e) {
    fileError.value = errText(e)
  }
}

async function removeFile(f) {
  if (!window.confirm(`删除文件「${f.filename}」？其全部版本与切块会一并删除，不可恢复。`))
    return
  fileError.value = ''
  try {
    await api.delete(`/files/${f.id}`)
    await load()
  } catch (e) {
    fileError.value = errText(e)
  }
}

function openFile(f) {
  router.push(`/meetings/${mid}/files/${f.id}`)
}

function startEditMeeting() {
  meetingForm.value = { name: meeting.value.name, date: meeting.value.date || '' }
  meetingError.value = ''
  editingMeeting.value = true
}

async function saveMeeting() {
  const name = meetingForm.value.name.trim()
  if (!name) return
  meetingSaving.value = true
  meetingError.value = ''
  try {
    await api.patch(`/meetings/${mid}`, {
      name,
      date: meetingForm.value.date || null, // 留空 = 显式清空日期
    })
    editingMeeting.value = false
    await load()
  } catch (e) {
    meetingError.value = errText(e)
  } finally {
    meetingSaving.value = false
  }
}

async function removeMeeting() {
  if (
    !window.confirm(
      `删除会议「${meeting.value.name}」？其全部 ${meeting.value.files.length} 个文件及版本历史会一并删除，不可恢复。`,
    )
  )
    return
  try {
    await api.delete(`/meetings/${mid}`)
    router.push('/meetings')
  } catch (e) {
    loadError.value = errText(e)
  }
}
</script>

<template>
  <div class="page meeting-detail">
    <div v-if="loading" class="muted">正在加载…</div>

    <div v-else-if="loadError && !meeting" class="card load-fail">
      <p class="error-text" role="alert">{{ loadError }}</p>
      <button type="button" class="btn" @click="load">重新加载</button>
    </div>

    <template v-else-if="meeting">
      <MeetingBreadcrumb
        :items="[
          { label: '会议记录', to: '/meetings' },
          { label: meeting.series_name },
          { label: meeting.name },
        ]"
      />
      <div class="meeting-title-row">
        <h1 class="page-title">{{ meeting.name }}</h1>
        <div class="meeting-title-ops">
          <button type="button" class="btn" @click="startEditMeeting">编辑会议</button>
          <button type="button" class="btn btn-danger" @click="removeMeeting">删除会议</button>
        </div>
      </div>
      <p class="page-desc">
        {{ meeting.date || '日期未解析' }}
        <template v-if="meeting.dir_name"> · 原始目录：<code class="mono">{{ meeting.dir_name }}</code></template>
      </p>

      <div v-if="editingMeeting" class="card edit-meeting-card">
        <label class="label">会议名称</label>
        <input
          class="input"
          v-model="meetingForm.name"
          @keyup.enter="saveMeeting"
          @keyup.esc="editingMeeting = false"
        />
        <label class="label">会议日期（留空 = 清空日期）</label>
        <input class="input date-input" type="date" v-model="meetingForm.date" />
        <div class="edit-meeting-ops">
          <button
            type="button"
            class="btn btn-primary"
            :disabled="meetingSaving"
            @click="saveMeeting"
          >
            {{ meetingSaving ? '保存中…' : '保存' }}
          </button>
          <button type="button" class="btn" @click="editingMeeting = false">取消</button>
        </div>
        <p v-if="meetingError" class="error-text" role="alert">{{ meetingError }}</p>
      </div>

      <!-- 分享与导出 -->
      <section class="section">
        <h2 class="section-title">哈希码分享</h2>
        <div class="card section-card">
          <pre class="code-pre mono">{{ curlCmd }}</pre>
          <div class="curl-ops">
            <button type="button" class="btn" @click="copyCurl">
              {{ curlCopied ? '已复制到剪贴板 ✓' : '复制 curl 命令' }}
            </button>
            <button
              type="button"
              class="btn btn-danger"
              :disabled="regenerating"
              @click="regenerate"
            >
              {{ regenerating ? '生成中…' : '重新生成哈希码' }}
            </button>
          </div>
          <p class="muted hint">
            URL 里的哈希码本身即授权，拿到链接的人可只读访问下方勾选的文件内容（Markdown）；
            重新生成后旧链接立即失效。「AI 接入 › 会议记录分享」页可生成提示词模板。
          </p>
          <div class="kinds-row">
            <label v-for="k in SHAREABLE_KINDS" :key="k" class="kind-check">
              <input type="checkbox" :value="k" v-model="kinds" />
              {{ KIND_LABELS[k] }}
            </label>
            <button
              type="button"
              class="btn"
              :disabled="kindsSaving"
              @click="saveKinds"
            >
              {{ kindsSaving ? '保存中…' : '保存范围' }}
            </button>
            <span v-if="kindsMsg" class="muted kinds-msg">{{ kindsMsg }}</span>
          </div>
          <div class="export-row">
            <button type="button" class="btn" :disabled="exporting" @click="exportZip">
              {{ exporting ? '打包中…' : '导出整会议 zip' }}
            </button>
            <span class="muted hint-inline">打包全部文件的当前版本（原文件名）。</span>
          </div>
        </div>
      </section>

      <!-- 文件列表 -->
      <section class="section">
        <h2 class="section-title">文件（{{ meeting.files.length }}）</h2>
        <MeetingUpload :meeting-id="meeting.id" @uploaded="load" />
        <p v-if="fileError" class="error-text file-err" role="alert">{{ fileError }}</p>

        <div v-if="!meeting.files.length" class="card empty">
          <p class="muted">还没有文件。把 md 文件拖到上方虚线区即可批量上传。</p>
        </div>

        <template
          v-for="group in [
            { title: '标准文件', files: standardFiles },
            { title: '其他文件', files: otherFiles },
          ]"
          :key="group.title"
        >
          <div v-if="group.files.length" class="file-group">
            <h3 class="group-title">{{ group.title }}（{{ group.files.length }}）</h3>
            <div class="file-list">
              <div
                v-for="f in group.files"
                :key="f.id"
                class="card file-card"
                :class="{ 'is-failed': f.parse_status === 'failed' }"
                @click="openFile(f)"
              >
                <div class="file-head">
                  <template v-if="renamingId === f.id">
                    <input
                      class="input rename-input mono"
                      v-model="renameValue"
                      @click.stop
                      @keyup.enter="saveRename(f)"
                      @keyup.esc="renamingId = null"
                    />
                    <button type="button" class="btn" @click.stop="saveRename(f)">保存</button>
                    <button type="button" class="btn" @click.stop="renamingId = null">取消</button>
                  </template>
                  <template v-else>
                    <span class="mono file-name">{{ f.filename }}</span>
                    <span class="kind-badge">{{ f.kind_label }}</span>
                    <VersionChip :version="f.current_version" />
                    <span class="parse-badge" :class="`is-${f.parse_status}`">
                      {{ PARSE_LABELS[f.parse_status] || f.parse_status }}
                    </span>
                    <span class="file-ops">
                      <button type="button" class="btn op-btn" @click.stop="startRename(f)">
                        重命名
                      </button>
                      <button type="button" class="btn btn-danger op-btn" @click.stop="removeFile(f)">
                        删除
                      </button>
                    </span>
                  </template>
                </div>
                <p v-if="f.parse_status === 'failed'" class="error-text parse-err" @click.stop>
                  {{ f.parse_error }}
                </p>
              </div>
            </div>
          </div>
        </template>
      </section>

      <p v-if="loadError" class="error-text" role="alert">{{ loadError }}</p>
    </template>
  </div>
</template>

<style scoped>
.meeting-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
}

.meeting-title-ops {
  display: flex;
  gap: var(--sp-2);
  flex: none;
}

.edit-meeting-card {
  margin-top: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--sp-2);
}

.edit-meeting-card .date-input {
  max-width: 220px;
}

.edit-meeting-ops {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
}

.section {
  margin-top: var(--sp-6);
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

.curl-ops {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.hint {
  font-size: var(--text-xs);
}

.kinds-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.kind-check {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--text-sm);
  cursor: pointer;
}

.kinds-msg {
  font-size: var(--text-xs);
}

.export-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.hint-inline {
  font-size: var(--text-xs);
}

.empty {
  margin-top: var(--sp-3);
  padding: var(--sp-5);
  border-style: dashed;
}

.file-err {
  margin-top: var(--sp-2);
}

.file-group {
  margin-top: var(--sp-4);
}

.group-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ink-2);
  margin-bottom: var(--sp-2);
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.file-card {
  padding: var(--sp-3) var(--sp-4);
  cursor: pointer;
  transition: border-color var(--dur) var(--ease);
}

.file-card:hover {
  border-color: var(--ink-2);
}

.file-card.is-failed {
  border-color: var(--danger);
}

.file-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.file-ops {
  margin-left: auto;
  display: flex;
  gap: var(--sp-2);
}

.op-btn {
  font-size: var(--text-xs);
  padding: 3px var(--sp-3);
}

.rename-input {
  flex: 1;
  min-width: 240px;
  padding: 4px var(--sp-2);
  font-size: var(--text-xs);
}

.file-name {
  font-size: var(--text-sm);
  font-weight: 500;
  word-break: break-all;
}

.kind-badge {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border: 1px solid var(--contract);
  border-radius: var(--radius-sm);
  color: var(--contract);
  background: var(--contract-wash);
  white-space: nowrap;
}

.parse-badge {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  white-space: nowrap;
}

.parse-badge.is-ok {
  color: var(--success);
  border-color: var(--success);
}

.parse-badge.is-failed {
  color: var(--danger);
  border-color: var(--danger);
  font-weight: 500;
}

.parse-badge.is-na {
  color: var(--ink-2);
}

.parse-err {
  margin-top: var(--sp-2);
  font-size: var(--text-xs);
  white-space: pre-wrap;
}
</style>

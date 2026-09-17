<script setup>
/**
 * MeetingUpload —— 会议 md 文件批量上传：拖拽区（dragover 高亮 / drop 取文件，
 * 保留点击选择），区内提示标准文件命名规则；上传后逐文件展示成功/失败/重复状态，
 * 失败的突出显示 parse_error（可直接贴给 agent 修源文件）。
 *
 * 用法：<MeetingUpload :meeting-id="m.id" @uploaded="reload" />
 */
import { ref } from 'vue'
import { api } from '../api/client.js'
import { KIND_LABELS, PARSE_LABELS, errText } from '../meetingMeta.js'

const props = defineProps({
  meetingId: { type: Number, required: true },
})
const emit = defineEmits(['uploaded'])

const dragOver = ref(false)
const uploading = ref(false)
const results = ref(null)
const error = ref('')
const fileInput = ref(null)

const HINT =
  '标准文件 6 类：*_转写.md、*_精准需求.md、*_业务事实.md、*_需求确认单.md、*_内部问题清单.md、*_修正词表.md；*_精简.md 等其余文件归为「其他」整篇存储。只接受 .md。'

function resultClass(r) {
  if (r.status === 'failed') return 'is-failed'
  if (r.status === 'duplicate') return 'is-dup'
  return 'is-ok'
}

function statusText(r) {
  if (r.status === 'duplicate') return '重复，已跳过'
  if (r.status === 'failed') return '解析失败'
  return PARSE_LABELS[r.parse_status] || '成功'
}

async function doUpload(fileList) {
  const files = [...fileList]
  const bad = files.filter((f) => !f.name.endsWith('.md'))
  if (bad.length) {
    error.value = `只接受 .md 文件，已忽略：${bad.map((f) => f.name).join('、')}`
  } else {
    error.value = ''
  }
  const mds = files.filter((f) => f.name.endsWith('.md'))
  if (!mds.length) return
  uploading.value = true
  results.value = null
  const fd = new FormData()
  for (const f of mds) fd.append('files', f, f.name)
  try {
    const res = await api.postForm(`/meetings/${props.meetingId}/upload`, fd)
    results.value = res.results
    emit('uploaded')
  } catch (e) {
    error.value = errText(e)
  } finally {
    uploading.value = false
  }
}

function onDrop(e) {
  dragOver.value = false
  if (e.dataTransfer?.files?.length) doUpload(e.dataTransfer.files)
}

function onPick(e) {
  if (e.target.files?.length) doUpload(e.target.files)
  e.target.value = '' // 允许重选同一批文件
}
</script>

<template>
  <div
    class="dropzone"
    :class="{ 'is-over': dragOver, 'is-busy': uploading }"
    @dragover.prevent="dragOver = true"
    @dragleave.prevent="dragOver = false"
    @drop.prevent="onDrop"
    @click="fileInput?.click()"
  >
    <input
      ref="fileInput"
      type="file"
      accept=".md,text/markdown"
      multiple
      hidden
      @change="onPick"
    />
    <p class="dz-title">
      {{ uploading ? '上传中…' : '拖拽 md 文件到这里，或点击选择（可多选）' }}
    </p>
    <p class="muted dz-hint">{{ HINT }}</p>
  </div>

  <p v-if="error" class="error-text dz-err" role="alert">{{ error }}</p>

  <ul v-if="results?.length" class="upload-results">
    <li
      v-for="r in results"
      :key="r.filename"
      class="upload-item"
      :class="resultClass(r)"
    >
      <span class="mono upload-name">{{ r.filename }}</span>
      <span class="kind-badge">{{ KIND_LABELS[r.kind] || r.kind }}</span>
      <span class="upload-status">{{ statusText(r) }}</span>
      <p v-if="r.error" class="error-text upload-detail">{{ r.error }}</p>
    </li>
  </ul>
</template>

<style scoped>
.dropzone {
  border: 1px dashed var(--hairline);
  border-radius: var(--radius);
  padding: var(--sp-4) var(--sp-5);
  cursor: pointer;
  transition:
    border-color var(--dur) var(--ease),
    background var(--dur) var(--ease);
}

.dropzone:hover,
.dropzone.is-over {
  border-color: var(--contract);
  background: var(--contract-wash);
}

.dropzone.is-busy {
  opacity: 0.6;
  cursor: wait;
}

.dz-title {
  font-size: var(--text-sm);
  font-weight: 500;
}

.dz-hint {
  margin-top: var(--sp-1);
  font-size: var(--text-xs);
}

.dz-err {
  margin-top: var(--sp-2);
}

.upload-results {
  margin-top: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.upload-item {
  font-size: var(--text-sm);
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.upload-name {
  font-size: var(--text-xs);
  word-break: break-all;
}

.kind-badge {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--paper);
  white-space: nowrap;
}

.upload-status {
  font-size: var(--text-xs);
}

.is-ok .upload-status {
  color: var(--success);
}

.is-dup .upload-status {
  color: var(--warning);
}

.is-failed .upload-status {
  color: var(--danger);
  font-weight: 500;
}

.upload-detail {
  flex-basis: 100%;
  font-size: var(--text-xs);
}
</style>

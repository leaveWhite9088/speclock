<script setup>
/**
 * MeetingSearchView（/meetings/search）—— 全局切块搜索：关键词 + 类型过滤
 * （全部/精准需求/业务事实）+ 状态过滤；结果卡片显示 ref_id、陈述、所属
 * 会议/文件，点击跳转到对应文件页。
 */
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client.js'
import MeetingBreadcrumb from '../components/MeetingBreadcrumb.vue'
import {
  CHUNK_TYPE_LABELS,
  STATUS_LABELS,
  STATUS_OPTIONS,
  errText,
} from '../meetingMeta.js'

const route = useRoute()
const router = useRouter()

const q = ref(typeof route.query.q === 'string' ? route.query.q : '')
const kind = ref(typeof route.query.kind === 'string' ? route.query.kind : '') // '' | req | fact
const status = ref('')
const results = ref([])
const searched = ref(false)
const searching = ref(false)
const error = ref('')

const KIND_FILTERS = [
  { value: '', label: '全部类型' },
  { value: 'req', label: '精准需求' },
  { value: 'fact', label: '业务事实' },
]

async function search() {
  searching.value = true
  error.value = ''
  try {
    const params = new URLSearchParams()
    if (q.value.trim()) params.set('q', q.value.trim())
    if (kind.value) params.set('kind', kind.value)
    if (status.value) params.set('status', status.value)
    results.value = await api.get(`/meetings/search?${params.toString()}`)
    searched.value = true
  } catch (e) {
    error.value = errText(e)
  } finally {
    searching.value = false
  }
}

onMounted(search)

// 从会议记录页跳入时 query 变化 → 重新搜索
watch(
  () => [route.query.q, route.query.kind],
  ([nq, nk]) => {
    q.value = typeof nq === 'string' ? nq : ''
    kind.value = typeof nk === 'string' ? nk : ''
    search()
  },
)

function mainText(h) {
  return h.fields.statement || h.fields.question || h.text_md
}

function openHit(h) {
  router.push(`/meetings/${h.meeting_id}/files/${h.file_id}`)
}
</script>

<template>
  <div class="page search-page">
    <MeetingBreadcrumb
      :items="[{ label: '会议记录', to: '/meetings' }, { label: '搜索' }]"
    />
    <h1 class="page-title">会议搜索</h1>
    <p class="page-desc">在全部会议的精准需求与业务事实条目里检索（匹配条目渲染文本）。</p>

    <!-- 紧凑搜索行：回车即搜 -->
    <div class="search-row">
      <input
        class="input"
        v-model="q"
        placeholder="关键词，如：计划表、口径、凑单…"
        @keyup.enter="search"
      />
      <select class="input filter" v-model="kind" @change="search" aria-label="条目类型">
        <option v-for="f in KIND_FILTERS" :key="f.value" :value="f.value">{{ f.label }}</option>
      </select>
      <select class="input filter" v-model="status" @change="search" aria-label="条目状态">
        <option value="">全部状态</option>
        <option v-for="s in STATUS_OPTIONS" :key="s" :value="s">{{ STATUS_LABELS[s] }}</option>
      </select>
      <button type="button" class="btn btn-primary search-btn" :disabled="searching" @click="search">
        {{ searching ? '搜索中…' : '搜索' }}
      </button>
    </div>

    <p v-if="error" class="error-text page-err" role="alert">{{ error }}</p>

    <p v-else-if="searched && !results.length" class="muted empty-hint">
      没有命中的条目。换个关键词，或放宽类型 / 状态过滤。
    </p>

    <div v-if="results.length" class="result-list">
      <p class="muted count">{{ results.length }} 条命中</p>
      <div
        v-for="h in results"
        :key="h.chunk_id"
        class="card hit-card"
        @click="openHit(h)"
      >
        <div class="hit-head">
          <span class="mono ref-id">{{ h.ref_id || '—' }}</span>
          <span class="chunk-badge">{{ CHUNK_TYPE_LABELS[h.chunk_type] || h.chunk_type }}</span>
          <span v-if="h.fields.status" class="status-badge">
            {{ STATUS_LABELS[h.fields.status] || h.fields.status }}
          </span>
          <span class="muted hit-loc">
            {{ h.meeting_name }} › <span class="mono">{{ h.filename }}</span>
            <template v-if="h.section"> › {{ h.section }}</template>
          </span>
        </div>
        <p class="hit-text">{{ mainText(h) }}</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.search-row {
  margin-top: var(--sp-4);
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  max-width: 720px;
}

.filter {
  width: auto;
  flex: none;
}

.search-btn {
  flex: none;
}

.page-err {
  margin-top: var(--sp-3);
}

.empty-hint {
  margin-top: var(--sp-5);
}

.result-list {
  margin-top: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.count {
  font-size: var(--text-xs);
}

.hit-card {
  padding: var(--sp-3) var(--sp-4);
  cursor: pointer;
  transition: border-color var(--dur) var(--ease);
}

.hit-card:hover {
  border-color: var(--ink-2);
}

.hit-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.ref-id {
  font-size: var(--text-sm);
  font-weight: 600;
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

.status-badge {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--paper);
  white-space: nowrap;
}

.hit-loc {
  font-size: var(--text-xs);
  margin-left: auto;
}

.hit-text {
  margin-top: var(--sp-2);
  font-size: var(--text-sm);
}
</style>

<script setup>
// 归档管理：已归档模块列表，支持恢复（回到已发布）与彻底删除（二次确认，不可恢复）。
import { onMounted, ref } from 'vue'
import { api } from '../api/client.js'
import VersionChip from '../components/VersionChip.vue'

const loading = ref(true)
const error = ref('')
const rows = ref([])
const pending = ref(null) // { id, action: 'restore' | 'purge' }
const busy = ref(false)
const rowError = ref({})

function fmtTime(iso) {
  return iso ? String(iso).replace('T', ' ').slice(0, 19) : '-'
}

function errText(e) {
  const d = e?.detail ?? e
  return typeof d === 'string' ? d : JSON.stringify(d, null, 2)
}

function ask(row, action) {
  pending.value = { id: row.id, action }
  rowError.value = { ...rowError.value, [row.id]: '' }
}

function cancel() {
  pending.value = null
}

async function confirm(row) {
  const action = pending.value?.action
  if (!action) return
  busy.value = true
  try {
    if (action === 'restore') {
      await api.post(`/blocks/${row.id}/restore`)
    } else {
      await api.delete(`/blocks/${row.id}/purge`)
    }
    pending.value = null
    await load()
  } catch (e) {
    rowError.value = { ...rowError.value, [row.id]: errText(e) }
  } finally {
    busy.value = false
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    rows.value = await api.get('/archive')
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page archive-page">
    <p class="page-eyebrow">Archive</p>
    <h1 class="page-title">归档管理</h1>
    <p class="page-desc">
      归档模块对 AI 不可见（读取 404、索引不出现），历史版本保留可查。归档与恢复都会立即派生所属文档的新版本（MINOR）。
    </p>

    <p v-if="loading" class="muted">加载中…</p>

    <div v-else-if="error" class="card state-card">
      <p class="error-text">{{ error }}</p>
      <button type="button" class="btn" @click="load">重试</button>
    </div>

    <div v-else-if="!rows.length" class="card state-card">
      <p class="muted">
        没有已归档的模块。在模块页面对已发布模块执行「删除」即归档——归档后历史版本仍然保留，可随时恢复。
      </p>
      <RouterLink to="/" class="btn">回到文档树</RouterLink>
    </div>

    <div v-else class="row-list">
      <article v-for="row in rows" :key="row.id" class="card arch-row">
        <div class="arch-main">
          <p class="arch-path mono muted">
            {{ row.project_name }} / {{ row.domain_name }} /
            <RouterLink :to="`/documents/${row.document_id}`">{{
              row.document_title
            }}</RouterLink>
          </p>
          <div class="arch-title-line">
            <RouterLink :to="`/blocks/${row.id}`" class="arch-title">{{
              row.title
            }}</RouterLink>
            <VersionChip
              v-if="row.current_published_version"
              :version="row.current_published_version"
            />
            <span v-else class="muted text-sm">无已发布版本</span>
          </div>
          <p class="muted arch-time">归档于 {{ fmtTime(row.archived_at) }}</p>
        </div>

        <div class="arch-ops">
          <template v-if="pending?.id === row.id">
            <p class="confirm-text" :class="{ 'is-danger': pending.action === 'purge' }">
              <template v-if="pending.action === 'restore'">
                恢复「{{ row.title }}」为已发布状态？所属文档将派生新版本（MINOR），模块回到 manifest。
              </template>
              <template v-else>
                彻底删除「{{ row.title }}」？其全部版本历史将被一并删除，不可恢复。
              </template>
            </p>
            <div class="confirm-btns">
              <button
                type="button"
                class="btn"
                :class="{ 'btn-danger': pending.action === 'purge' }"
                :disabled="busy"
                @click="confirm(row)"
              >
                {{ busy ? '处理中…' : pending.action === 'restore' ? '确认恢复' : '确认彻底删除' }}
              </button>
              <button type="button" class="btn" :disabled="busy" @click="cancel">取消</button>
            </div>
          </template>
          <template v-else>
            <button type="button" class="btn" @click="ask(row, 'restore')">恢复</button>
            <button type="button" class="btn btn-danger" @click="ask(row, 'purge')">
              彻底删除
            </button>
          </template>
        </div>

        <p v-if="rowError[row.id]" class="error-text arch-error">{{ rowError[row.id] }}</p>
      </article>
    </div>
  </div>
</template>

<style scoped>
.archive-page {
  max-width: 860px;
}

.state-card {
  margin-top: var(--sp-5);
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.row-list {
  margin-top: var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.arch-row {
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  align-items: center;
  gap: var(--sp-5);
  flex-wrap: wrap;
}

.arch-main {
  flex: 1;
  min-width: 260px;
}

.arch-path {
  font-size: var(--text-xs);
  margin-bottom: var(--sp-1);
}

.arch-title-line {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.arch-title {
  font-weight: 600;
  font-size: var(--text-md);
}

.text-sm {
  font-size: var(--text-sm);
}

.arch-time {
  font-size: var(--text-xs);
  margin-top: var(--sp-1);
}

.arch-ops {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.confirm-text {
  font-size: var(--text-sm);
  max-width: 320px;
}

.confirm-text.is-danger {
  color: var(--danger);
}

.confirm-btns {
  display: flex;
  gap: var(--sp-2);
}

.arch-error {
  flex-basis: 100%;
}
</style>

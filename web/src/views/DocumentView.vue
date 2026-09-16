<script setup>
// 文档详情：模块清单 + 文档版本时间线（每版可展开 manifest 快照）。
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/client.js'
import VersionChip from '../components/VersionChip.vue'

const route = useRoute()
const docId = computed(() => Number(route.params.id))

const loading = ref(true)
const error = ref('')
const doc = ref(null) // { id, title, current_version, blocks, projectName, domainName }
const versions = ref([])
const openManifest = ref({}) // version -> bool

const STATUS_TEXT = { draft: '草稿', published: '已发布', archived: '已归档' }

function fmtTime(iso) {
  return iso ? String(iso).replace('T', ' ').slice(0, 19) : '-'
}

function errText(e) {
  const d = e?.detail ?? e
  return typeof d === 'string' ? d : JSON.stringify(d, null, 2)
}

function cmpVersion(a, b) {
  const pa = String(a).split('.').map(Number)
  const pb = String(b).split('.').map(Number)
  for (let i = 0; i < 3; i++) {
    if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0)
  }
  return 0
}

function manifestRows(v) {
  return Object.entries(v.manifest || {}).map(([blockId, m]) => ({
    blockId: Number(blockId),
    title: m.title,
    version: m.version,
  }))
}

function triggerTitle(v) {
  const m = v.manifest?.[String(v.triggered_by_block_id)]
  return m ? m.title : `#${v.triggered_by_block_id}`
}

function toggleManifest(version) {
  openManifest.value = { ...openManifest.value, [version]: !openManifest.value[version] }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [tree, vers] = await Promise.all([
      api.get('/tree'),
      api.get(`/documents/${docId.value}/versions`),
    ])
    let found = null
    for (const p of tree) {
      for (const d of p.domains) {
        for (const dc of d.documents) {
          if (dc.id === docId.value) {
            found = { ...dc, projectName: p.name, domainName: d.name }
          }
        }
      }
    }
    if (!found) {
      throw { status: 404, detail: `文档 ${docId.value} 不存在或已被删除。回到文档树选择一份文档。` }
    }
    doc.value = found
    versions.value = [...vers].sort((a, b) => cmpVersion(b.version, a.version))
    // 最新一版默认展开 manifest
    openManifest.value = versions.value.length ? { [versions.value[0].version]: true } : {}
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

watch(docId, load, { immediate: true })
</script>

<template>
  <div class="page doc-page">
    <p v-if="loading" class="muted">加载中…</p>

    <div v-else-if="error" class="card state-card">
      <p class="error-text">{{ error }}</p>
      <button type="button" class="btn" @click="load">重试</button>
    </div>

    <template v-else-if="doc">
      <p class="page-eyebrow">{{ doc.projectName }} / {{ doc.domainName }}</p>
      <h1 class="page-title">
        {{ doc.title }}
        <VersionChip v-if="doc.current_version" :version="doc.current_version" />
      </h1>
      <p class="page-desc">
        模块独立发布；每次模块发布都会为本文档派生一个新的文档版本（manifest 快照）。
      </p>

      <section class="section">
        <h2 class="section-title">模块（{{ doc.blocks.length }}）</h2>
        <div v-if="doc.blocks.length" class="card block-list">
          <div v-for="b in doc.blocks" :key="b.id" class="block-row">
            <RouterLink :to="`/blocks/${b.id}`" class="block-title">{{
              b.title
            }}</RouterLink>
            <span class="status-badge" :class="`is-${b.status}`">{{
              STATUS_TEXT[b.status] || b.status
            }}</span>
            <VersionChip
              v-if="b.current_published_version"
              :version="b.current_published_version"
            />
            <span v-else class="muted text-sm">未发布</span>
            <span v-if="b.completed" class="done-mark" title="当前版本已标记完成">
              ✓ 已完成
            </span>
          </div>
        </div>
        <div v-else class="card state-card">
          <p class="muted">本文档还没有模块。在文档树里为「{{ doc.title }}」新建第一个模块。</p>
        </div>
      </section>

      <section class="section">
        <h2 class="section-title">版本历史（{{ versions.length }}）</h2>
        <div v-if="versions.length" class="timeline">
          <article v-for="v in versions" :key="v.version" class="tl-item">
            <span class="tl-dot" aria-hidden="true"></span>
            <div class="card tl-card">
              <header class="tl-head">
                <VersionChip :version="v.version" />
                <span class="tl-note">{{ v.change_note || '（无变更说明）' }}</span>
                <button type="button" class="btn tl-toggle" @click="toggleManifest(v.version)">
                  {{ openManifest[v.version] ? '收起 manifest' : `manifest（${manifestRows(v).length}）` }}
                </button>
              </header>
              <p class="tl-meta muted">
                {{ fmtTime(v.published_at) }} · {{ v.published_by }} 发布 · 触发模块
                <RouterLink :to="`/blocks/${v.triggered_by_block_id}`">{{
                  triggerTitle(v)
                }}</RouterLink>
              </p>
              <table v-if="openManifest[v.version]" class="manifest-table">
                <thead>
                  <tr><th>模块</th><th>pin 版本</th></tr>
                </thead>
                <tbody>
                  <tr v-for="m in manifestRows(v)" :key="m.blockId">
                    <td>
                      <RouterLink :to="`/blocks/${m.blockId}`">{{ m.title }}</RouterLink>
                    </td>
                    <td><VersionChip :version="m.version" /></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
        </div>
        <div v-else class="card state-card">
          <p class="muted">
            还没有文档版本。发布任一模块后，这里会自动派生第一个文档版本。
          </p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.doc-page {
  max-width: 860px;
}

.section {
  margin-top: var(--sp-6);
}

.section-title {
  font-size: var(--text-lg);
  font-weight: 600;
  margin-bottom: var(--sp-3);
}

.state-card {
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.text-sm {
  font-size: var(--text-sm);
}

/* ---------- 模块清单 ---------- */

.block-list {
  padding: var(--sp-2) var(--sp-4);
}

.block-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) 0;
}

.block-row + .block-row {
  border-top: 1px solid var(--hairline);
}

.block-title {
  font-weight: 500;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-badge {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--hairline);
  color: var(--ink-2);
  white-space: nowrap;
}

.status-badge.is-published {
  color: var(--contract);
  border-color: var(--contract);
  background: var(--contract-wash);
}

.status-badge.is-archived {
  color: var(--ink-2);
  background: var(--paper);
}

.done-mark {
  margin-left: auto;
  font-size: var(--text-xs);
  color: var(--success);
  white-space: nowrap;
}

/* ---------- 版本时间线 ---------- */

.timeline {
  position: relative;
  padding-left: var(--sp-5);
}

.timeline::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 10px;
  bottom: 10px;
  width: 1px;
  background: var(--hairline);
}

.tl-item {
  position: relative;
}

.tl-item + .tl-item {
  margin-top: var(--sp-4);
}

.tl-dot {
  position: absolute;
  left: calc(-1 * var(--sp-5) + 2px);
  top: 16px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--card);
  border: 2px solid var(--contract);
}

.tl-card {
  padding: var(--sp-4);
}

.tl-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.tl-note {
  font-size: var(--text-sm);
  flex: 1;
  min-width: 200px;
}

.tl-toggle {
  padding: 3px var(--sp-3);
  font-size: var(--text-xs);
}

.tl-meta {
  margin-top: var(--sp-2);
  font-size: var(--text-xs);
}

.manifest-table {
  width: 100%;
  margin-top: var(--sp-3);
  border-top: 1px solid var(--hairline);
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.manifest-table th {
  text-align: left;
  font-weight: 500;
  color: var(--ink-2);
  font-size: var(--text-xs);
  padding: var(--sp-2) 0;
}

.manifest-table td {
  padding: var(--sp-2) 0;
  border-top: 1px solid var(--hairline);
}
</style>

<script setup>
// 小业务详情：模块清单 + 小业务版本时间线（每版可展开 manifest 快照）。
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { resources } from '../api/resources.js'
import { errText } from '../errors.js'
import { BLOCK_STATUS } from '../labels.js'
import { useKeyNames } from '../api/keyNames.js'
import { fmtTime } from '../time.js'
import VersionChip from '../components/VersionChip.vue'
import ExecStatusBadge from '../components/ExecStatusBadge.vue'
import AppBreadcrumb from '../components/AppBreadcrumb.vue'
import LoadingState from '../components/LoadingState.vue'
import ErrorState from '../components/ErrorState.vue'

const { keyName } = useKeyNames()

const route = useRoute()
const docId = computed(() => Number(route.params.id))

const loading = ref(true)
const error = ref('')
const doc = ref(null) // { id, title, current_version, blocks, projectName, businessName }
const versions = ref([])
const openManifest = ref({}) // version -> bool

const STATUS_TEXT = BLOCK_STATUS

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
      resources.tree(),
      resources.capabilities.versions(docId.value),
    ])
    let found = null
    for (const p of tree) {
      for (const d of p.businesses) {
        for (const dc of d.capabilities) {
          if (dc.id === docId.value) {
            found = { ...dc, projectName: p.name, businessName: d.name }
          }
        }
      }
    }
    if (!found) {
      throw { status: 404, detail: `小业务 ${docId.value} 不存在或已被删除。回到文档树选择一个小业务。` }
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
    <LoadingState v-if="loading" />
    <ErrorState v-else-if="error" :message="error" @retry="load" />

    <template v-else-if="doc">
      <AppBreadcrumb :capability-id="docId" />
      <h1 class="page-title">
        {{ doc.title }}
        <VersionChip v-if="doc.current_version" :version="doc.current_version" />
      </h1>
      <div class="summary-box">
        <p v-if="doc.summary" class="summary-text">{{ doc.summary }}</p>
        <p v-else class="summary-text muted">暂无简述。简述会随索引下发给 agent，帮助它判断这个小业务是否相关。</p>
      </div>
      <p class="page-desc">
        模块独立发布；一个 Commit 会为本小业务派生一个新的小业务版本（manifest 快照）。
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
            <ExecStatusBadge :status="b.execution_status" />
          </div>
        </div>
        <div v-else class="card state-card">
          <p class="muted">本小业务还没有模块（模块由 Agent 经审核单创建）。</p>
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
                {{ fmtTime(v.published_at) }} · {{ keyName(v.published_by) }} 发布
                <template v-if="v.cr_id"> · 审核单 <RouterLink :to="`/change-requests/${v.cr_id}`">#{{ v.cr_id }}</RouterLink></template>
                · 触发模块
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
            还没有小业务版本。发布任一模块后，这里会自动派生第一个小业务版本。
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

.summary-box {
  margin-top: var(--sp-3);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-2);
}

.summary-text {
  font-size: var(--text-sm);
}

.summary-btn {
  padding: 3px var(--sp-3);
  font-size: var(--text-xs);
}

.summary-input {
  width: 100%;
  font: inherit;
  font-size: var(--text-sm);
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  resize: vertical;
}

.summary-actions {
  display: flex;
  gap: var(--sp-2);
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

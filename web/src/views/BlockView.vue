<script setup>
/**
 * BlockView（/blocks/:id）—— 已发布模块只读页：完整快照渲染、版本切换、
 * 完成标记切换、「编辑」「查看 diff」入口。
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client.js'
import VersionChip from '../components/VersionChip.vue'
import BlockStatusBadge from '../components/BlockStatusBadge.vue'
import BlockMethodBadge from '../components/BlockMethodBadge.vue'
import BlockApiDetail from '../components/BlockApiDetail.vue'
import BlockMd from '../components/BlockMd.vue'

const route = useRoute()
const router = useRouter()
const bid = route.params.id

const loading = ref(true)
const loadError = ref('')
const meta = ref(null) // 草稿侧的实时元信息（title/status/document_id）
const versions = ref([])
const snap = ref(null) // 当前查看的版本快照
const selected = ref('')
const completeBusy = ref(false)
const opError = ref('')

function errText(e) {
  const d = e && e.detail
  if (!d) return '请求失败，请检查网络后重试。'
  if (typeof d === 'string') return d
  return d.error || JSON.stringify(d)
}

function sorted(list) {
  return [...list].sort((a, b) =>
    String(a.published_at || '').localeCompare(String(b.published_at || '')),
  )
}

async function loadVersion(v) {
  snap.value = await api.get(`/blocks/${bid}/versions/${v}`)
  selected.value = v
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [d, vs] = await Promise.all([
      api.get(`/blocks/${bid}/draft`),
      api.get(`/blocks/${bid}/versions`),
    ])
    meta.value = d
    versions.value = sorted(vs)
    const want =
      typeof route.query.version === 'string' && route.query.version
        ? route.query.version
        : d.current_published_version || versions.value.at(-1)?.version
    if (want) await loadVersion(want)
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function pickVersion(v) {
  if (!v || v === selected.value) return
  router.replace({ query: { version: v } })
}

watch(
  () => route.query.version,
  (v) => {
    if (v && v !== selected.value && meta.value) {
      loadVersion(v).catch((e) => (opError.value = errText(e)))
    }
  },
)

const apis = computed(() => snap.value?.apis || [])
const rules = computed(() => snap.value?.rules || [])

const latestDiff = computed(() => {
  const vs = versions.value
  if (vs.length < 2) return null
  return { from: vs[vs.length - 2].version, to: vs[vs.length - 1].version }
})

function prevVersion(v) {
  const i = versions.value.findIndex((x) => x.version === v)
  return i > 0 ? versions.value[i - 1].version : null
}

async function toggleComplete() {
  if (!snap.value || completeBusy.value) return
  completeBusy.value = true
  opError.value = ''
  const done = !snap.value.completed
  try {
    const res = await api.post(`/blocks/${bid}/${done ? 'complete' : 'uncomplete'}`)
    snap.value.completed = res.completed
    snap.value.completed_version = res.completed_version
  } catch (e) {
    opError.value = errText(e)
  } finally {
    completeBusy.value = false
  }
}
</script>

<template>
  <div class="page view-page">
    <div v-if="loading" class="muted">正在加载…</div>

    <div v-else-if="loadError" class="card load-fail">
      <p class="error-text" role="alert">{{ loadError }}</p>
      <button type="button" class="btn" @click="load">重新加载</button>
    </div>

    <template v-else-if="meta">
      <p class="crumb muted">
        <RouterLink to="/">文档树</RouterLink> ›
        <RouterLink :to="`/documents/${meta.document_id}`">所属文档</RouterLink> ›
        {{ meta.title }}
      </p>

      <!-- 尚未发布：引导空状态 -->
      <div v-if="!versions.length" class="card empty">
        <h1 class="page-title">{{ meta.title }}</h1>
        <p class="muted">该模块尚未发布，没有可查看的内容。</p>
        <RouterLink class="btn btn-primary" :to="`/blocks/${bid}/edit`">
          打开编辑器，补齐内容后发布第一版
        </RouterLink>
      </div>

      <template v-else-if="snap">
        <div class="view-head">
          <div class="title-row">
            <h1 class="page-title">{{ snap.title }}</h1>
            <BlockStatusBadge :status="snap.status" />
          </div>
          <div class="seal-row">
            <span class="seal-label mono">version</span>
            <VersionChip :version="snap.version" status="published" />
            <select
              class="input ver-select"
              :value="selected"
              @change="pickVersion($event.target.value)"
              aria-label="切换版本"
            >
              <option v-for="v in versions" :key="v.version" :value="v.version">
                v{{ v.version }} · {{ v.change_note || '无变更说明' }}
              </option>
            </select>
          </div>
          <p class="muted seal-meta">
            {{ snap.change_note || '（无变更说明）' }} · 由 {{ snap.published_by }} 发布于
            {{ snap.published_at }}
          </p>

          <div class="ops-row">
            <RouterLink class="btn" :to="`/blocks/${bid}/edit`">编辑</RouterLink>
            <RouterLink class="btn" :to="`/blocks/${bid}/diff`">查看 diff</RouterLink>
            <RouterLink
              v-if="latestDiff"
              class="btn"
              :to="`/blocks/${bid}/diff?from=${latestDiff.from}&to=${latestDiff.to}`"
            >
              ⚡ 最近一次变更（v{{ latestDiff.from }} → v{{ latestDiff.to }}）
            </RouterLink>
            <button
              v-else
              type="button"
              class="btn"
              disabled
              title="暂无历史版本"
            >
              ⚡ 最近一次变更
            </button>

            <span class="complete-box">
              <span v-if="snap.completed" class="done-badge">
                ✓ 已完成<template v-if="snap.completed_version"
                  >@v{{ snap.completed_version }}</template
                >
              </span>
              <span v-else class="undone-badge">未完成</span>
              <button
                type="button"
                class="btn"
                :class="{ 'btn-primary': !snap.completed }"
                :disabled="completeBusy"
                @click="toggleComplete"
              >
                {{ snap.completed ? '取消完成' : '标记完成' }}
              </button>
            </span>
          </div>
          <p v-if="opError" class="error-text" role="alert">{{ opError }}</p>
        </div>

        <section class="card sec">
          <h2 class="sec-title">业务背景与流程</h2>
          <BlockMd :source="snap.content_md" />
        </section>

        <section class="card sec">
          <h2 class="sec-title">业务规则清单（{{ rules.length }} 条）</h2>
          <table v-if="rules.length" class="rules-table">
            <thead>
              <tr>
                <th class="col-idx">#</th>
                <th class="col-name">规则名</th>
                <th>规则详述</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in rules" :key="i">
                <td class="muted mono">{{ i + 1 }}</td>
                <td>{{ r.name }}</td>
                <td>{{ r.detail }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted">无规则（历史版本可能早于结构化拆分）。</p>
        </section>

        <section class="card sec">
          <h2 class="sec-title">API 列表（{{ apis.length }} 个）</h2>
          <p v-if="!apis.length" class="muted">该版本没有 API。</p>
          <details v-for="(a, i) in apis" :key="i" class="api-item">
            <summary class="api-summary">
              <span class="idx mono muted">#{{ i + 1 }}</span>
              <BlockMethodBadge :api="a.api" />
              <span class="mono api-path">{{ (a.api || '').split(' ')[1] }}</span>
              <span class="api-name">{{ a.name }}</span>
              <span class="muted api-desc">{{ a.desc }}</span>
            </summary>
            <BlockApiDetail :api="a" />
          </details>
        </section>

        <section class="card sec">
          <h2 class="sec-title">非功能性需求</h2>
          <BlockMd v-if="snap.nfr_md" :source="snap.nfr_md" />
          <p v-else class="muted">无非功能性需求。</p>
        </section>

        <section class="card sec">
          <h2 class="sec-title">版本历史</h2>
          <table class="ver-table">
            <thead>
              <tr>
                <th>版本</th>
                <th>变更说明</th>
                <th>发布时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="v in versions" :key="v.version">
                <td>
                  <VersionChip :version="v.version" />
                  <span v-if="v.version === selected" class="current-tag">当前查看</span>
                </td>
                <td>{{ v.change_note || '—' }}</td>
                <td class="muted mono ver-time">{{ v.published_at }}</td>
                <td class="ver-ops">
                  <a href="#" @click.prevent="pickVersion(v.version)">查看</a>
                  <template v-if="prevVersion(v.version)">
                    ·
                    <RouterLink
                      :to="`/blocks/${bid}/diff?from=${prevVersion(v.version)}&to=${v.version}`"
                      >与上一版对比</RouterLink
                    >
                  </template>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.crumb {
  font-size: var(--text-sm);
  margin-bottom: var(--sp-2);
}

.load-fail {
  margin-top: var(--sp-5);
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.empty {
  margin-top: var(--sp-4);
  padding: var(--sp-6);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
  border-style: dashed;
}

.view-head {
  margin-bottom: var(--sp-5);
}

.title-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.seal-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-top: var(--sp-3);
}

.seal-label {
  font-size: var(--text-xs);
  letter-spacing: 0.08em;
  color: var(--ink-2);
  text-transform: uppercase;
}

.ver-select {
  width: auto;
  min-width: 220px;
  padding: 4px var(--sp-2);
  font-size: var(--text-sm);
}

.seal-meta {
  margin-top: var(--sp-2);
  font-size: var(--text-sm);
}

.ops-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  margin-top: var(--sp-4);
}

.complete-box {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
}

.done-badge {
  font-size: var(--text-xs);
  color: var(--success);
  border: 1px solid var(--success);
  border-radius: var(--radius-sm);
  padding: 2px 8px;
  white-space: nowrap;
}

.undone-badge {
  font-size: var(--text-xs);
  color: var(--ink-2);
  border: 1px dashed var(--ink-2);
  border-radius: var(--radius-sm);
  padding: 2px 8px;
  white-space: nowrap;
}

.sec {
  padding: var(--sp-4) var(--sp-5);
  margin-bottom: var(--sp-4);
}

.sec-title {
  font-size: var(--text-lg);
  font-weight: 600;
  margin-bottom: var(--sp-3);
}

.rules-table,
.ver-table {
  width: 100%;
  border-collapse: collapse;
}

.rules-table th,
.ver-table th {
  text-align: left;
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--ink-2);
  padding: 0 var(--sp-2) var(--sp-1) 0;
  border-bottom: 1px solid var(--hairline);
}

.rules-table td,
.ver-table td {
  padding: var(--sp-2) var(--sp-2) var(--sp-2) 0;
  font-size: var(--text-sm);
  vertical-align: top;
  border-bottom: 1px solid var(--hairline);
}

.col-idx {
  width: 32px;
}

.col-name {
  width: 220px;
}

.api-item {
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  margin-bottom: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
}

.api-summary {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  cursor: pointer;
  font-size: var(--text-sm);
  list-style: none;
  flex-wrap: wrap;
}

.api-summary::-webkit-details-marker {
  display: none;
}

.api-summary::before {
  content: '▸';
  color: var(--ink-2);
  font-size: var(--text-xs);
}

.api-item[open] .api-summary::before {
  content: '▾';
}

.api-item[open] .api-summary {
  margin-bottom: var(--sp-3);
}

.api-name {
  font-weight: 500;
}

.api-desc {
  font-size: var(--text-xs);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 40%;
}

.ver-time {
  font-size: var(--text-xs);
}

.current-tag {
  margin-left: var(--sp-2);
  font-size: var(--text-xs);
  color: var(--contract);
}

.ver-ops {
  font-size: var(--text-sm);
  white-space: nowrap;
}
</style>

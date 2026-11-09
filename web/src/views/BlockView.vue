<script setup>
/**
 * BlockView（/blocks/:id）—— 已发布模块只读页：完整快照渲染、版本切换、
 * 执行状态展示、「查看 diff」入口、版本溯源到审核单。
 * 本页纯展示，不提供任何修改操作（所有写入都由 Agent 经审核单 + Commit 完成）。
 */
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { resources } from '../api/resources.js'
import { errText } from '../errors.js'
import { EXEC_EVENT, EXEC_STATUS, label } from '../labels.js'
import { useKeyNames } from '../api/keyNames.js'
import { fmtTime } from '../time.js'
import VersionChip from '../components/VersionChip.vue'
import BlockStatusBadge from '../components/BlockStatusBadge.vue'
import BlockMethodBadge from '../components/BlockMethodBadge.vue'
import BlockApiDetail from '../components/BlockApiDetail.vue'
import BlockMd from '../components/BlockMd.vue'
import AppBreadcrumb from '../components/AppBreadcrumb.vue'
import ExecStatusBadge from '../components/ExecStatusBadge.vue'
import LoadingState from '../components/LoadingState.vue'
import ErrorState from '../components/ErrorState.vue'

const route = useRoute()
const router = useRouter()
const bid = route.params.id
const { keyName } = useKeyNames()

const loading = ref(true)
const loadError = ref('')
const meta = ref(null) // 模块元信息（title/status/capability_id/current_published_version），取自 /tree
const versions = ref([])
const snap = ref(null) // 当前查看的版本快照
const selected = ref('')
const opError = ref('')
const openEvents = ref({}) // 版本号 -> 是否展开执行历史

function sorted(list) {
  return [...list].sort((a, b) =>
    String(a.published_at || '').localeCompare(String(b.published_at || '')),
  )
}

async function loadVersion(v) {
  snap.value = await resources.blocks.version(bid, v)
  selected.value = v
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [tree, vs] = await Promise.all([resources.tree(), resources.blocks.versions(bid)])
    let d = null
    for (const p of tree)
      for (const biz of p.businesses)
        for (const cap of biz.capabilities)
          for (const b of cap.blocks)
            if (String(b.id) === String(bid))
              d = { ...b, capability_id: cap.id, current_published_version: b.current_published_version }
    if (!d) throw { detail: '没有找到这个模块（或当前密钥无权访问它所在的项目）。' }
    meta.value = d
    versions.value = sorted(vs)
    const pinned =
      typeof route.query.version === 'string' && route.query.version
        ? route.query.version
        : ''
    // 依次尝试：URL pin → 当前发布版 → 列表末版；pin 的版本不存在（404）时
    // 回落到最新版本而非整页报错
    const candidates = [
      ...new Set(
        [pinned, d.current_published_version, versions.value.at(-1)?.version].filter(
          Boolean,
        ),
      ),
    ]
    snap.value = null
    let loaded = false
    for (const v of candidates) {
      try {
        await loadVersion(v)
        loaded = true
        break
      } catch {
        /* 该版本不可查看，尝试下一个 */
      }
    }
    if (pinned && selected.value !== pinned) {
      opError.value = loaded
        ? `没有找到版本 v${pinned}，已为你显示最新版本。`
        : ''
    }
  } catch (e) {
    loadError.value = errText(e)
  } finally {
    loading.value = false
  }
  scrollToHash()
}

// 地址里带 #item-R-2 时（例如从搜索结果跳来），滚动到那一行并闪一下
async function scrollToHash() {
  const id = route.hash ? decodeURIComponent(route.hash.slice(1)) : ''
  if (!id) return
  await nextTick()
  const el = document.getElementById(id)
  if (!el) return
  el.scrollIntoView({ block: 'center' })
  el.classList.add('flash')
  setTimeout(() => el.classList.remove('flash'), 2000)
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
const acceptance = computed(() => snap.value?.acceptance || [])

const latestDiff = computed(() => {
  const vs = versions.value
  if (vs.length < 2) return null
  return { from: vs[vs.length - 2].version, to: vs[vs.length - 1].version }
})

const versionsDesc = computed(() => [...versions.value].reverse())

function prevVersion(v) {
  const i = versions.value.findIndex((x) => x.version === v)
  return i > 0 ? versions.value[i - 1].version : null
}

function toggleEvents(v) {
  openEvents.value = { ...openEvents.value, [v]: !openEvents.value[v] }
}
</script>

<template>
  <div class="page view-page">
    <LoadingState v-if="loading" />
    <ErrorState v-else-if="loadError" :message="loadError" @retry="load" />

    <template v-else-if="meta">
      <AppBreadcrumb :block-id="bid" />

      <!-- 尚未发布：引导空状态 -->
      <div v-if="!versions.length" class="card empty">
        <h1 class="page-title">{{ meta.title }}</h1>
        <p class="muted">该模块还没有可查看的已发布版本（可能版本都已被作废）。</p>
      </div>

      <template v-else-if="snap">
        <div class="view-head">
          <div class="title-row">
            <h1 class="page-title">{{ snap.title }}</h1>
            <span class="bid mono">#{{ bid }}</span>
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
            {{ snap.change_note || '（无变更说明）' }} · 由 {{ keyName(snap.published_by) }} 发布于
            {{ fmtTime(snap.published_at) }}
            <template v-if="snap.level"> · 版本级别 {{ snap.level }}（机械标签，仅供参考）</template>
            <template v-if="snap.cr_id">
              · 来自 <RouterLink :to="`/change-requests/${snap.cr_id}`">审核单 #{{ snap.cr_id }}</RouterLink>
              的 Commit #{{ snap.commit_id }}
            </template>
          </p>

          <div class="ops-row">
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
              执行状态 <ExecStatusBadge :status="snap.execution_status" />
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
                <th class="col-idx">编号</th>
                <th class="col-name">规则名</th>
                <th>规则详述</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in rules" :id="r.id ? `item-${r.id}` : undefined" :key="i">
                <td class="muted mono">{{ r.id || i + 1 }}</td>
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
          <h2 class="sec-title">验收条件（{{ acceptance.length }} 条）</h2>
          <table v-if="acceptance.length" class="rules-table">
            <thead>
              <tr>
                <th class="col-idx">编号</th>
                <th class="col-name">验收条件名</th>
                <th>验收条件详述</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in acceptance" :id="r.id ? `item-${r.id}` : undefined" :key="i">
                <td class="muted mono">{{ r.id || i + 1 }}</td>
                <td>{{ r.name }}</td>
                <td>{{ r.detail }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted">无验收条件。</p>
        </section>

        <section class="card sec">
          <h2 class="sec-title">版本历史</h2>
          <table class="ver-table">
            <thead>
              <tr>
                <th>版本</th>
                <th>变更说明</th>
                <th>发布时间</th>
                <th>审核单</th>
                <th>执行</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="v in versionsDesc" :key="v.version">
                <tr>
                  <td>
                    <VersionChip :version="v.version" />
                    <span v-if="v.version === selected" class="current-tag">当前查看</span>
                  </td>
                  <td>{{ v.change_note || '—' }}</td>
                  <td class="muted mono ver-time">{{ fmtTime(v.published_at) }}</td>
                  <td class="muted mono">
                    <RouterLink v-if="v.cr_id" :to="`/change-requests/${v.cr_id}`">#{{ v.cr_id }}</RouterLink>
                    <template v-else>—</template>
                  </td>
                  <td class="ver-acks">
                    <ExecStatusBadge :status="v.execution_status" />
                    <a
                      v-if="v.events && v.events.length"
                      href="#"
                      class="ack-link"
                      @click.prevent="toggleEvents(v.version)"
                      >{{ openEvents[v.version] ? '收起' : '历史' }}</a
                    >
                  </td>
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
                <tr v-if="openEvents[v.version]" class="events-row">
                  <td colspan="6">
                    <ol class="events">
                      <li v-for="(e, i) in v.events" :key="i">
                        <span class="mono muted">{{ fmtTime(e.created_at) }}</span>
                        <span class="ev-name">{{ label(EXEC_EVENT, e.event) }}</span>
                        <span class="muted">{{ label(EXEC_STATUS, e.from) }} → {{ label(EXEC_STATUS, e.to) }}</span>
                        <span class="muted">{{ keyName(e.actor) }}</span>
                        <span v-if="e.note">{{ e.note }}</span>
                      </li>
                    </ol>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
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

.ver-acks {
  font-size: var(--text-xs);
}

.ack-link {
  margin-left: var(--sp-2);
  white-space: nowrap;
}

.ver-ops {
  font-size: var(--text-sm);
  white-space: nowrap;
}

.confirm-text {
  font-size: var(--text-sm);
  margin-right: var(--sp-3);
}

.confirm-text.is-danger {
  color: var(--danger);
}

.confirm-btns {
  display: inline-flex;
  gap: var(--sp-2);
}
.events {
  margin: 0;
  padding-left: var(--sp-4);
  font-size: var(--text-xs);
}

.events li {
  display: flex;
  gap: var(--sp-3);
  flex-wrap: wrap;
  padding: 2px 0;
}

.ev-name {
  font-weight: 500;
}
</style>

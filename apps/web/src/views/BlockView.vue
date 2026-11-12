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
import { useAutoRefresh } from '../composables/useAutoRefresh.js'

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
const openDetail = ref({}) // 版本号 -> 是否展开「为什么改 + 执行进展」
const crCache = ref({}) // 审核单 id -> 审核单（懒加载，用来显示「为什么改」）
const crError = ref({})

function sorted(list) {
  return [...list].sort((a, b) =>
    String(a.published_at || '').localeCompare(String(b.published_at || '')),
  )
}

async function loadVersion(v) {
  snap.value = await resources.blocks.version(bid, v)
  selected.value = v
}

async function load({ silent = false } = {}) {
  if (!silent) {
    loading.value = true
    loadError.value = ''
  }
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
    // 静默刷新时保持用户正在看的版本
    const pinned =
      silent && selected.value
        ? selected.value
        : typeof route.query.version === 'string' && route.query.version
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
    if (!silent) snap.value = null
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
    if (!silent) loadError.value = errText(e)
  } finally {
    if (!silent) loading.value = false
  }
  if (!silent) scrollToHash()
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

onMounted(() => load())
useAutoRefresh(load)

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

async function toggleDetail(v) {
  openDetail.value = { ...openDetail.value, [v.version]: !openDetail.value[v.version] }
  const id = v.cr_id
  if (openDetail.value[v.version] && id && !crCache.value[id]) {
    try {
      crCache.value = { ...crCache.value, [id]: await resources.crs.get(id) }
    } catch (e) {
      crError.value = { ...crError.value, [id]: errText(e) }
    }
  }
}
</script>

<template>
  <div class="page view-page">
    <LoadingState v-if="loading" />
    <ErrorState v-else-if="loadError" :message="loadError" @retry="load()" />

    <template v-else-if="meta">
      <AppBreadcrumb :block-id="bid" />

      <!-- 尚未发布：引导空状态 -->
      <div v-if="!versions.length" class="empty">
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
            {{ snap.change_note || '无变更说明' }} · {{ keyName(snap.published_by) }} · {{ fmtTime(snap.published_at) }}
            <template v-if="snap.cr_id">
              · <RouterLink :to="`/change-requests/${snap.cr_id}`">审核单 #{{ snap.cr_id }}</RouterLink>
            </template>
          </p>

          <div class="ops-row">
            <RouterLink class="btn" :to="`/blocks/${bid}/diff`">查看 diff</RouterLink>
            <RouterLink
              v-if="latestDiff"
              class="btn"
              :to="`/blocks/${bid}/diff?from=${latestDiff.from}&to=${latestDiff.to}`"
            >
              最近一次变更 v{{ latestDiff.from }} → v{{ latestDiff.to }}
            </RouterLink>
            <button
              v-else
              type="button"
              class="btn"
              disabled
              title="暂无历史版本"
            >
              最近一次变更
            </button>

            <span class="complete-box">
              执行状态 <ExecStatusBadge :status="snap.execution_status" />
            </span>
          </div>
          <p v-if="opError" class="error-text" role="alert">{{ opError }}</p>
        </div>

        <section class="sec">
          <h2 class="sec-title">背景</h2>
          <BlockMd :source="snap.content_md" />
        </section>

        <section class="sec">
          <h2 class="sec-title">业务规则 <span class="count">{{ rules.length }}</span></h2>
          <table v-if="rules.length" class="rules-table">
            <thead>
              <tr>
                <th class="col-idx"></th>
                <th class="col-name">规则</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in rules" :id="r.id ? `item-${r.id}` : undefined" :key="i">
                <td class="muted mono idx">{{ r.id || i + 1 }}</td>
                <td class="name">{{ r.name }}</td>
                <td class="detail">{{ r.detail }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted">无</p>
        </section>

        <section class="sec">
          <h2 class="sec-title">API <span class="count">{{ apis.length }}</span></h2>
          <p v-if="!apis.length" class="muted">无</p>
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

        <section class="sec">
          <h2 class="sec-title">验收条件 <span class="count">{{ acceptance.length }}</span></h2>
          <table v-if="acceptance.length" class="rules-table">
            <thead>
              <tr>
                <th class="col-idx"></th>
                <th class="col-name">条件</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in acceptance" :id="r.id ? `item-${r.id}` : undefined" :key="i">
                <td class="muted mono idx">{{ r.id || i + 1 }}</td>
                <td class="name">{{ r.name }}</td>
                <td class="detail">{{ r.detail }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="muted">无</p>
        </section>

        <details class="fold sec">
          <summary>版本历史 <span class="count">{{ versions.length }}</span></summary>
          <div class="table-scroll"><table class="ver-table">
            <thead>
              <tr>
                <th>版本</th>
                <th>变更说明</th>
                <th>发布时间</th>
                <th>审核单</th>
                <th>执行</th>
                <th></th>
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
                      v-if="v.cr_id || (v.events && v.events.length)"
                      href="#"
                      class="ack-link"
                      @click.prevent="toggleDetail(v)"
                      >{{ openDetail[v.version] ? '收起' : '详情' }}</a
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
                <tr v-if="openDetail[v.version]" class="events-row">
                  <td colspan="6">
                    <div v-if="v.cr_id" class="why">
                      <p class="why-title">为什么改
                        <RouterLink :to="`/change-requests/${v.cr_id}`">审核单 #{{ v.cr_id }}</RouterLink>
                        <span v-if="crCache[v.cr_id]?.kind === 'internal'" class="kind-tag">内部整理</span>
                      </p>
                      <p v-if="crCache[v.cr_id]" class="why-body">{{ crCache[v.cr_id].intent }}</p>
                      <p v-if="crCache[v.cr_id]?.expected_outcome" class="why-body muted">
                        变成：{{ crCache[v.cr_id].expected_outcome }}
                      </p>
                      <p v-else-if="crError[v.cr_id]" class="error-text">{{ crError[v.cr_id] }}</p>
                      <p v-else-if="!crCache[v.cr_id]" class="muted">加载中…</p>
                    </div>
                    <p v-else class="muted">这个版本不是经审核单产生的（灌入的示例数据）。</p>
                    <p v-if="v.events && v.events.length" class="why-title">执行进展</p>
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
          </table></div>
        </details>
      </template>
    </template>
  </div>
</template>

<style scoped>
.empty {
  margin-top: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.view-head {
  margin-bottom: var(--sp-4);
}

.title-row {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--sp-2) var(--sp-3);
}

.bid {
  font-size: var(--text-sm);
  color: var(--ink-2);
}

.seal-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-3);
  margin-top: var(--sp-3);
}

.ver-select {
  width: auto;
  max-width: 100%;
  min-width: 0;
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
  margin-top: var(--sp-3);
}

.complete-box {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-sm);
  color: var(--ink-2);
}

/* 各部分用标题 + 细线隔开，不套卡片 */
.sec {
  margin-top: var(--sp-5);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--hairline);
}

.sec-title {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: 600;
  margin-bottom: var(--sp-2);
}

.sec-title .count {
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 400;
  color: var(--ink-2);
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
  padding: 0 var(--sp-3) var(--sp-1) 0;
}

.rules-table td,
.ver-table td {
  padding: var(--sp-2) var(--sp-3) var(--sp-2) 0;
  font-size: var(--text-md);
  vertical-align: top;
  border-top: 1px solid var(--hairline);
}

.col-idx {
  width: 1%;
}

.col-name {
  width: 30%;
  min-width: 8em;
}

.idx {
  white-space: nowrap;
  font-size: var(--text-xs);
}

.name {
  font-weight: 500;
}

.table-scroll {
  overflow-x: auto;
}

/* 窄屏：规则 / 验收条件每条一块：编号 + 名称一行，说明在下面 */
@media (max-width: 560px) {
  .rules-table,
  .rules-table tbody {
    display: block;
  }

  .rules-table thead {
    display: none;
  }

  .rules-table tr {
    display: grid;
    grid-template-columns: auto 1fr;
    column-gap: var(--sp-2);
    padding: var(--sp-2) 0;
    border-top: 1px solid var(--hairline);
  }

  .rules-table td {
    padding: 0;
    border: none;
  }

  .rules-table .detail {
    grid-column: 1 / -1;
    margin-top: 2px;
    color: var(--ink-2);
    font-size: var(--text-sm);
  }
}

.api-item {
  border-top: 1px solid var(--hairline);
  padding: var(--sp-2) var(--sp-1);
}

.api-summary {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  cursor: pointer;
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
  font-size: var(--text-sm);
  min-width: 0;
}

.ver-time {
  font-size: var(--text-xs);
  white-space: nowrap;
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

.why {
  margin-bottom: var(--sp-3);
}

.why-title {
  font-size: var(--text-sm);
  font-weight: 600;
  margin-bottom: 2px;
}

.why-body {
  font-size: var(--text-sm);
}

.kind-tag {
  margin-left: var(--sp-2);
  padding: 0 var(--sp-2);
  font-size: var(--text-xs);
  border-radius: 999px;
  background: var(--warning-wash);
  color: var(--warning);
}

.events {
  margin: 0;
  padding-left: var(--sp-4);
  font-size: var(--text-sm);
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

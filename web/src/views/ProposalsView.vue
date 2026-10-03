<script setup>
// 提案收件箱：按状态过滤，待处理提案可批准（应用到草稿并发布）或拒绝（需填理由）。
import { computed, onMounted, ref } from 'vue'
import { marked } from 'marked'
import { api } from '../api/client.js'
import { fmtTime } from '../time.js'
import VersionChip from '../components/VersionChip.vue'
import BlockTextDiff from '../components/BlockTextDiff.vue'

const TABS = [
  { key: 'submitted', label: '待处理' },
  { key: 'published', label: '已发布' },
  { key: 'rejected', label: '已拒绝' },
]

const EMPTY_TEXT = {
  submitted: '没有待处理的提案。AI 通过 submit_proposal 提交的变更建议会出现在这里。',
  published: '还没有已发布的提案。批准待处理提案后，它会带着发布版本号归档到这里。',
  rejected: '没有已拒绝的提案。',
}

const activeTab = ref('submitted')
const loading = ref(true)
const error = ref('')
const proposals = ref([])
const notes = ref({}) // proposalId -> 审批意见
const busy = ref({}) // proposalId -> bool
const cardError = ref({}) // proposalId -> string
const flash = ref('')

const emptyText = computed(() => EMPTY_TEXT[activeTab.value])

function errText(e) {
  const d = e?.detail ?? e
  if (typeof d === 'string') return d
  if (d && Array.isArray(d.missing)) {
    return `${d.error || '操作被拒绝'}：${d.missing.join('；')}`
  }
  return JSON.stringify(d, null, 2)
}

function renderMd(text) {
  return marked.parse(text || '')
}

function apiOps(p) {
  return p.proposed_api_ops?.length ? p.proposed_api_ops : p.proposed_apis_view || []
}

function isEmptyPayload(p) {
  return (
    !p.proposed_content_md &&
    !p.proposed_api_ops?.length &&
    !p.proposed_apis?.length &&
    !p.proposed_rule_ops?.length
  )
}

// 契约行里 "METHOD /path:" 段与卡片标题重复，削掉统一成短格式
// （如 response:GET /a/b/{id}:f: string → response:f: string）；路径含 {} 无冒号，不误伤字段路径
const API_PATH_RE = /^(request|response|api):(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+\S+?:/

function stripApiPath(s) {
  return s.replace(API_PATH_RE, '$1:')
}

// 扁平变更字符串 → 字段键（"request:a.b: string required" → "request:a.b"）
function flatKey(s) {
  const t = stripApiPath(s)
  const i = t.lastIndexOf(': ')
  return i < 0 ? t : t.slice(0, i)
}

// 把 op.changes 整理成按键索引的状态表；desc/name 变更在标题下单独展示，不进表
function changeMaps(op) {
  const c = op.changes?.contract || {}
  const maps = { added: new Set(), removed: new Set(), modified: new Set(), desc: {} }
  for (const s of c.added || []) maps.added.add(flatKey(s))
  for (const s of c.removed || []) maps.removed.add(flatKey(s))
  for (const s of c.modified || []) maps.modified.add(flatKey(s))
  for (const t of op.changes?.text || []) {
    const m = /^(request|response):(.+)\.description$/.exec(t.path || '')
    if (m) maps.desc[`${m[1]}:${m[2]}`] = t
  }
  return maps
}

// API 显示名/简介变更：卡片标题下红旧绿新两行
function nameChange(op) {
  return (op.changes?.text || []).find((t) => t.path === 'name') || null
}

function descChange(op) {
  return (op.changes?.text || []).find((t) => t.path === 'desc') || null
}

// ---------- 字段树全景 diff（GitHub PR「全文 + 高亮」风格） ----------

function fieldLine(f) {
  const req = f.required ? ' required' : ''
  const desc = f.description ? ` — ${f.description}` : ''
  return `${f.name}: ${f.type}${req}${desc}`
}

// 整棵子树统一着色（新增子树全绿 / 删除子树全红）；parents 记录祖先行下标，供 hunk 保留结构上下文
function pushSubtree(rows, f, depth, cls, parents) {
  const idx = rows.length
  rows.push({ text: fieldLine(f), cls, depth, parents })
  for (const ch of f.children || []) pushSubtree(rows, ch, depth + 1, cls, [...parents, idx])
}

// 以提案树为主序对齐两棵字段树；removed 节点插回它在当前树同级中的位置
function mergeLevel(rows, kind, prefix, curList, newList, depth, maps, parents = []) {
  const news = newList || []
  const cur = curList || []
  const newNames = new Set(news.map((f) => f.name))
  let ci = 0
  for (const f of news) {
    const key = `${kind}:${prefix}${f.name}`
    while (ci < cur.length && cur[ci].name !== f.name) {
      if (!newNames.has(cur[ci].name)) pushSubtree(rows, cur[ci], depth, 'is-del', parents)
      ci++
    }
    const matched = ci < cur.length ? cur[ci] : null
    if (matched) ci++
    if (!matched) {
      pushSubtree(rows, f, depth, 'is-add', parents)
      continue
    }
    let idx
    if (maps.modified.has(key) || key in maps.desc) {
      // 类型/必填变化或 description 变化：红旧行 + 绿新行成对，原地展示
      rows.push({ text: fieldLine(matched), cls: 'is-del', depth, parents })
      idx = rows.length
      rows.push({ text: fieldLine(f), cls: 'is-add', depth, parents })
    } else {
      idx = rows.length
      rows.push({ text: fieldLine(f), cls: '', depth, parents })
    }
    mergeLevel(
      rows,
      kind,
      `${prefix}${f.name}.`,
      matched.children,
      f.children,
      depth + 1,
      maps,
      [...parents, idx]
    )
  }
  while (ci < cur.length) {
    if (!newNames.has(cur[ci].name)) pushSubtree(rows, cur[ci], depth, 'is-del', parents)
    ci++
  }
}

// 一个分组的行集：upsert 走树对齐；delete 整树红行；新增 API（无 current）整树绿行
function treeRows(op, kind) {
  const rows = []
  if (op.op === 'delete') {
    for (const f of op.current_entry?.[kind] || []) pushSubtree(rows, f, 0, 'is-del', [])
    return rows
  }
  mergeLevel(rows, kind, '', op.current_entry?.[kind], op.entry?.[kind], 0, changeMaps(op))
  return rows
}

// GitHub hunk 模式：变化行 ±HUNK_CTX 行上下文 + 变化行的祖先链可见，其余收进折叠条
const HUNK_CTX = 3
// 整 API 新增/删除（全树都是变化行）时退化为截断：超过 MAX 行只露前 HEAD 行
const WHOLE_TREE_MAX = 25
const WHOLE_TREE_HEAD = 10

function treeSegments(op, kind) {
  const rows = treeRows(op, kind)
  const n = rows.length
  if (!n) return []
  const changed = []
  rows.forEach((r, i) => {
    if (r.cls !== '') changed.push(i)
  })
  if (changed.length === n && n > WHOLE_TREE_MAX) {
    return [
      { type: 'rows', rows: rows.slice(0, WHOLE_TREE_HEAD) },
      { type: 'fold', rows: rows.slice(WHOLE_TREE_HEAD) },
    ]
  }
  const visible = new Array(n).fill(false)
  for (const i of changed) {
    for (let k = Math.max(0, i - HUNK_CTX); k <= Math.min(n - 1, i + HUNK_CTX); k++) {
      visible[k] = true
    }
    for (const p of rows[i].parents) visible[p] = true
  }
  const segs = []
  let i = 0
  while (i < n) {
    let j = i
    while (j < n && visible[j] === visible[i]) j++
    segs.push({ type: visible[i] ? 'rows' : 'fold', rows: rows.slice(i, j) })
    i = j
  }
  return segs
}

// 分组内是否有任何变化行（无变化的分组整体不渲染，避免空分组标题 + 全折叠条）
function groupHasChange(op, kind) {
  return treeRows(op, kind).some((r) => r.cls !== '')
}

function textLines(text) {
  const arr = (text || '').split('\n')
  while (arr.length && arr[arr.length - 1] === '') arr.pop()
  return arr
}

// 删除规则：整块红行
function ruleDelLines(op) {
  return [
    { kind: 'del', text: `− rule: ${op.name}` },
    ...textLines(op.current_entry?.detail).map((l) => ({ kind: 'del', text: `− ${l}` })),
  ]
}

// 新增规则：整块绿行
function ruleAddLines(op) {
  return [
    { kind: 'add', text: `+ rule: ${op.name}` },
    ...textLines(op.entry?.detail).map((l) => ({ kind: 'add', text: `+ ${l}` })),
  ]
}

// 无任何可见变更的 op 不渲染（删除目标已不存在 / upsert 零差异）
function apiOpHasChange(op) {
  if (op.op === 'delete') return !!op.current_entry
  if (!op.current_entry) return true // 新增 API
  const c = op.changes?.contract
  const hasContract = !!(c && (c.added?.length || c.modified?.length || c.removed?.length))
  return hasContract || (op.changes?.text || []).length > 0
}

function ruleOpHasChange(op) {
  if (op.op === 'delete') return !!op.current_entry
  if (!op.current_entry) return true // 新增规则
  return !!op.detail_diff
}

function visibleApiOps(p) {
  return apiOps(p).filter(apiOpHasChange)
}

function visibleRuleOps(p) {
  return (p.proposed_rule_ops || []).filter(ruleOpHasChange)
}

function ruleOpKindLabel(op) {
  return { added: '新增规则', modified: '规则变更', unchanged: '无差异', removed: '删除规则' }[
    op.kind
  ]
}

function ruleOpKindClass(op) {
  return {
    added: 'is-upsert',
    modified: 'is-modified',
    unchanged: '',
    removed: 'is-delete',
  }[op.kind]
}

function switchTab(key) {
  if (activeTab.value === key) return
  activeTab.value = key
  flash.value = ''
  load()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    proposals.value = await api.get(`/proposals?status=${activeTab.value}`)
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

async function resolve(p, action) {
  const note = (notes.value[p.id] || '').trim()
  if (action === 'reject' && !note) {
    cardError.value = { ...cardError.value, [p.id]: '拒绝需要填写理由——告诉提交方为什么。' }
    return
  }
  if (
    action === 'approve' &&
    isEmptyPayload(p) &&
    !window.confirm(
      `提案 #${p.id} 不含任何内容变更（无改写正文、无 API/规则变更），` +
        '发布将只记录说明并 bump 版本号，正文/接口/规则零变化。确定批准并发布？'
    )
  ) {
    return
  }
  busy.value = { ...busy.value, [p.id]: true }
  cardError.value = { ...cardError.value, [p.id]: '' }
  try {
    const r = await api.post(`/proposals/${p.id}/resolve`, {
      action,
      resolution_note: note,
    })
    flash.value =
      action === 'approve'
        ? `提案 #${p.id} 已批准并发布为 v${r.published_version}（文档版本 v${r.document_version}）。`
        : `提案 #${p.id} 已拒绝。`
    await load()
  } catch (e) {
    cardError.value = { ...cardError.value, [p.id]: errText(e) }
  } finally {
    busy.value = { ...busy.value, [p.id]: false }
  }
}

onMounted(load)
</script>

<template>
  <div class="page proposals-page">
    <p class="page-eyebrow">Proposals</p>
    <h1 class="page-title">提案收件箱</h1>
    <p class="page-desc">
      提案是 AI 唯一的写出口。批准后提案内容会应用到模块草稿并立即发布；拒绝需填写理由。
    </p>

    <div class="tabs" role="tablist">
      <button
        v-for="t in TABS"
        :key="t.key"
        type="button"
        role="tab"
        class="tab"
        :class="{ 'is-active': activeTab === t.key }"
        :aria-selected="activeTab === t.key"
        @click="switchTab(t.key)"
      >
        {{ t.label }}
      </button>
    </div>

    <p v-if="flash" class="flash">{{ flash }}</p>

    <p v-if="loading" class="muted">加载中…</p>

    <div v-else-if="error" class="card state-card">
      <p class="error-text">{{ error }}</p>
      <button type="button" class="btn" @click="load">重试</button>
    </div>

    <div v-else-if="!proposals.length" class="card state-card">
      <p class="muted">{{ emptyText }}</p>
    </div>

    <div v-else class="proposal-list">
      <article v-for="p in proposals" :key="p.id" class="card proposal-card">
        <header class="p-head">
          <span class="p-id mono">#{{ p.id }}</span>
          <RouterLink :to="`/blocks/${p.block_id}`" class="p-block">{{
            p.block_title
          }}</RouterLink>
          <span class="p-status" :class="`is-${p.status}`">
            {{ { submitted: '待处理', published: '已发布', rejected: '已拒绝' }[p.status] || p.status }}
          </span>
          <VersionChip
            v-if="p.published_version"
            :version="p.published_version"
          />
          <span class="p-author">{{ p.author_type === 'agent' ? 'AI 提交' : '人工提交' }}</span>
          <span class="muted p-time">{{ fmtTime(p.created_at) }}</span>
        </header>

        <dl class="p-body">
          <div class="p-field">
            <dt>问题</dt>
            <dd>{{ p.description }}</dd>
          </div>
          <div class="p-field">
            <dt>建议</dt>
            <dd>{{ p.suggestion }}</dd>
          </div>
          <div v-if="p.scenario" class="p-field">
            <dt>场景</dt>
            <dd class="muted">{{ p.scenario }}</dd>
          </div>
        </dl>

        <p
          v-if="isEmptyPayload(p)"
          class="p-empty-warning"
          :class="{ 'is-note-only': p.note_only }"
        >
          <template v-if="p.note_only">
            纯说明提案（note_only）：不含内容变更，发布将只记录说明并 bump 版本号。
          </template>
          <template v-else>
            ⚠ 此提案不含内容变更（无改写正文、无 API/规则变更），批准发布将只记录说明并
            bump 版本号，正文/接口/规则零变化。
          </template>
        </p>

        <div v-if="p.proposed_content_md" class="p-proposed">
          <p class="p-proposed-label">建议改写后的内容预览</p>
          <!-- markdown 渲染结果包在容器内，样式由下方 :deep 控制 -->
          <div class="md-body" v-html="renderMd(p.proposed_content_md)"></div>
          <details v-if="p.content_diff" class="p-op-detail p-content-diff">
            <summary>与当前正文的文本差异</summary>
            <BlockTextDiff :text="p.content_diff" />
          </details>
        </div>
        <div v-if="visibleApiOps(p).length" class="p-ops">
          <p class="p-proposed-label">
            <template v-if="p.proposed_api_ops && p.proposed_api_ops.length">
              建议的 API 变更（delta，基于 {{ p.base_version ? `v${p.base_version}` : '未发布版本' }}）
            </template>
            <template v-else>
              建议的 API 变更（整体替换，按 API 分拆{{ p.base_version ? `，对照 v${p.base_version}` : '' }}）
            </template>
          </p>
          <ul class="p-op-list">
            <li v-for="(op, i) in visibleApiOps(p)" :key="i" class="p-op">
              <div class="p-op-head">
                <span class="p-op-badge" :class="`is-${op.op}`">
                  {{ op.op === 'upsert' ? '更新' : '删除' }}
                </span>
                <span class="mono p-op-api">{{ op.api }}</span>
                <span v-if="(op.entry || op.current_entry)?.name" class="p-op-name">
                  {{ (op.entry || op.current_entry).name }}
                </span>
              </div>

              <!-- 显示名 / 简介变更：紧跟标题，红旧绿新 -->
              <div v-if="nameChange(op) || descChange(op)" class="p-diff mono p-desc-diff">
                <template v-if="nameChange(op)">
                  <span v-if="nameChange(op).old" class="p-diff-line is-del"
                    >− name: {{ nameChange(op).old }}</span
                  >
                  <span v-if="nameChange(op).new" class="p-diff-line is-add"
                    >+ name: {{ nameChange(op).new }}</span
                  >
                </template>
                <template v-if="descChange(op)">
                  <span v-if="descChange(op).old" class="p-diff-line is-del"
                    >− desc: {{ descChange(op).old }}</span
                  >
                  <span v-if="descChange(op).new" class="p-diff-line is-add"
                    >+ desc: {{ descChange(op).new }}</span
                  >
                </template>
              </div>

              <!-- 字段树全景（GitHub hunk 模式）：变化行 ±3 上下文 + 祖先链，其余折叠 -->
              <div
                v-if="groupHasChange(op, 'request') || groupHasChange(op, 'response')"
                class="p-diff mono p-tree"
              >
                <template
                  v-for="sec in [
                    ['请求字段', 'request'],
                    ['响应字段', 'response'],
                  ]"
                  :key="sec[1]"
                >
                  <template v-if="groupHasChange(op, sec[1])">
                    <span class="p-diff-line is-group">{{ sec[0] }}</span>
                    <template v-for="(seg, k) in treeSegments(op, sec[1])" :key="k">
                      <template v-if="seg.type === 'rows'">
                        <span
                          v-for="(r, m) in seg.rows"
                          :key="m"
                          class="p-diff-line"
                          :class="r.cls"
                          :style="{ paddingLeft: `calc(var(--sp-3) + ${r.depth * 1.2}em)` }"
                          >{{ r.text }}</span
                        >
                      </template>
                      <details v-else class="p-fold">
                        <summary class="p-diff-line is-fold">… {{ seg.rows.length }} 行无变化 …</summary>
                        <span
                          v-for="(r, m) in seg.rows"
                          :key="m"
                          class="p-diff-line"
                          :style="{ paddingLeft: `calc(var(--sp-3) + ${r.depth * 1.2}em)` }"
                          >{{ r.text }}</span
                        >
                      </details>
                    </template>
                  </template>
                </template>
              </div>
            </li>
          </ul>
        </div>

        <div v-if="visibleRuleOps(p).length" class="p-ops">
          <p class="p-proposed-label">
            建议的规则变更（delta，基于 {{ p.base_version ? `v${p.base_version}` : '未发布版本' }}）
          </p>
          <ul class="p-op-list">
            <li v-for="(op, i) in visibleRuleOps(p)" :key="i" class="p-op">
              <div class="p-op-head">
                <span class="p-op-badge" :class="`is-${op.op}`">
                  {{ op.op === 'upsert' ? '更新' : '删除' }}
                </span>
                <span class="p-op-rule">{{ op.name }}</span>
                <span class="p-op-badge" :class="ruleOpKindClass(op)">
                  {{ ruleOpKindLabel(op) }}
                </span>
              </div>

              <template v-if="op.op === 'delete'">
                <p class="p-op-note muted">将删除以下当前规则：</p>
                <div class="p-diff mono">
                  <span
                    v-for="(l, j) in ruleDelLines(op)"
                    :key="j"
                    class="p-diff-line"
                    :class="`is-${l.kind}`"
                    >{{ l.text || ' ' }}</span
                  >
                </div>
              </template>

              <template v-else>
                <div v-if="!op.current_entry" class="p-diff mono">
                  <span
                    v-for="(l, j) in ruleAddLines(op)"
                    :key="j"
                    class="p-diff-line"
                    :class="`is-${l.kind}`"
                    >{{ l.text || ' ' }}</span
                  >
                </div>
                <template v-else>
                  <p class="p-op-side-label p-diff-label">详述文本差异</p>
                  <BlockTextDiff :text="op.detail_diff" />
                </template>
              </template>
            </li>
          </ul>
        </div>

        <template v-if="p.status === 'submitted'">
          <div class="p-actions">
            <input
              v-model="notes[p.id]"
              class="input p-note"
              type="text"
              placeholder="审批意见（批准可选填，拒绝必填）"
            />
            <button
              type="button"
              class="btn btn-primary"
              :disabled="busy[p.id]"
              @click="resolve(p, 'approve')"
            >
              {{ busy[p.id] ? '处理中…' : '批准并发布' }}
            </button>
            <button
              type="button"
              class="btn btn-danger"
              :disabled="busy[p.id]"
              @click="resolve(p, 'reject')"
            >
              拒绝
            </button>
          </div>
          <p v-if="cardError[p.id]" class="error-text p-error">{{ cardError[p.id] }}</p>
        </template>
        <p v-else class="p-resolution muted">
          审批意见：{{ p.resolution_note || '（未填写）' }}
        </p>
      </article>
    </div>
  </div>
</template>

<style scoped>
/* 提案收件箱放宽到约 80% 屏宽，左对齐（覆盖全局 .page 的 960px 上限，仅本页生效） */
.proposals-page {
  width: 80%;
  max-width: none;
}

@media (max-width: 900px) {
  .proposals-page {
    width: auto;
  }
}

.state-card {
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

/* ---------- 状态 tab ---------- */

.tabs {
  display: flex;
  gap: var(--sp-1);
  margin-top: var(--sp-5);
  border-bottom: 1px solid var(--hairline);
}

.tab {
  appearance: none;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  padding: var(--sp-2) var(--sp-3);
  font: inherit;
  font-size: var(--text-sm);
  color: var(--ink-2);
  cursor: pointer;
  margin-bottom: -1px;
  transition:
    color var(--dur) var(--ease),
    border-color var(--dur) var(--ease);
}

.tab:hover {
  color: var(--ink);
}

.tab.is-active {
  color: var(--contract);
  border-bottom-color: var(--contract);
  font-weight: 500;
}

.flash {
  margin-top: var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  border: 1px solid var(--success);
  border-radius: var(--radius);
  color: var(--success);
  background: color-mix(in srgb, var(--success) 6%, var(--card));
  font-size: var(--text-sm);
}

/* ---------- 提案卡片 ---------- */

.proposal-list {
  margin-top: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.proposal-card {
  padding: var(--sp-4) var(--sp-5);
}

.p-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  padding-bottom: var(--sp-3);
  border-bottom: 1px solid var(--hairline);
}

.p-id {
  color: var(--ink-2);
  font-size: var(--text-sm);
}

.p-block {
  font-weight: 600;
  font-size: var(--text-md);
}

.p-status {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--hairline);
  color: var(--ink-2);
  white-space: nowrap;
}

.p-status.is-submitted {
  color: var(--warning);
  border-color: var(--warning);
  background: color-mix(in srgb, var(--warning) 7%, var(--card));
}

.p-status.is-published {
  color: var(--success);
  border-color: var(--success);
}

.p-status.is-rejected {
  color: var(--danger);
  border-color: var(--danger);
}

.p-author {
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.p-time {
  margin-left: auto;
  font-size: var(--text-xs);
}

.p-body {
  margin: var(--sp-3) 0 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.p-field {
  display: flex;
  gap: var(--sp-3);
  font-size: var(--text-sm);
}

.p-field dt {
  flex: 0 0 3em;
  font-weight: 600;
  color: var(--ink-2);
}

.p-field dd {
  margin: 0;
  min-width: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

.p-empty-warning {
  margin: var(--sp-3) 0 0;
  padding: var(--sp-2) var(--sp-3);
  border: 1px solid var(--danger);
  border-radius: var(--radius-sm);
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 6%, var(--card));
  font-size: var(--text-sm);
}

.p-empty-warning.is-note-only {
  border-color: var(--warning);
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 6%, var(--card));
}

/* ---------- proposed 内容预览 ---------- */

.p-proposed {
  margin-top: var(--sp-3);
}

.p-proposed-label {
  font-size: var(--text-xs);
  color: var(--ink-2);
  margin-bottom: var(--sp-2);
}

.md-body {
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  background: var(--paper);
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--text-sm);
  max-height: 320px;
  overflow: auto;
}

.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3) {
  font-size: var(--text-md);
  margin: var(--sp-3) 0 var(--sp-2);
}

.md-body :deep(p) {
  margin: var(--sp-2) 0;
}

.md-body :deep(ul),
.md-body :deep(ol) {
  padding-left: var(--sp-5);
  list-style: disc;
}

.md-body :deep(ol) {
  list-style: decimal;
}

.md-body :deep(pre) {
  background: var(--card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  padding: var(--sp-2) var(--sp-3);
  overflow-x: auto;
  font-size: var(--text-xs);
}

.md-body :deep(code) {
  font-size: var(--text-xs);
}

/* ---------- delta 变更列表 ---------- */

.p-ops {
  margin-top: var(--sp-3);
}

.p-op-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.p-op {
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--paper);
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--text-sm);
}

.p-op-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.p-op-badge {
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--hairline);
  white-space: nowrap;
}

.p-op-badge.is-upsert {
  color: var(--contract);
  border-color: var(--contract);
  background: color-mix(in srgb, var(--contract) 7%, var(--card));
}

.p-op-badge.is-delete {
  color: var(--danger);
  border-color: var(--danger);
  background: color-mix(in srgb, var(--danger) 7%, var(--card));
}

.p-op-badge.is-modified {
  color: var(--warning);
  border-color: var(--warning);
  background: color-mix(in srgb, var(--warning) 7%, var(--card));
}

.p-op-rule {
  font-weight: 600;
  font-size: var(--text-sm);
}

.p-content-diff {
  margin-top: var(--sp-2);
}

.p-op-api {
  font-size: var(--text-xs);
}

.p-op-note {
  margin: var(--sp-2) 0 0;
  font-size: var(--text-xs);
}

.p-op-side-label {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ink-2);
  margin-bottom: var(--sp-1);
}

/* ---------- diff 行展示（与 BlockTextDiff 同观感：绿底新增 / 红底删除，等宽折行） ---------- */

.p-diff {
  margin-top: var(--sp-2);
  padding: var(--sp-2) 0;
  background: var(--card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  font-size: var(--text-xs);
  line-height: 1.6;
}

.p-diff-line {
  display: block;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 0 var(--sp-3);
}

.p-diff-line.is-add {
  color: var(--success);
  background: rgba(21, 122, 78, 0.08);
}

.p-diff-line.is-del {
  color: var(--danger);
  background: rgba(196, 53, 28, 0.08);
}

/* 字段树全景：分组标题与折叠段 */
.p-diff-line.is-group {
  color: var(--ink-2);
  font-weight: 600;
}

.p-fold summary {
  cursor: pointer;
  color: var(--ink-2);
  list-style: none;
}

.p-fold summary::-webkit-details-marker {
  display: none;
}

.p-fold summary::before {
  content: '▸ ';
}

.p-fold[open] summary::before {
  content: '▾ ';
}

.p-diff-label {
  margin-top: var(--sp-2);
}

/* desc 变更紧跟标题 */
.p-desc-diff {
  margin-top: var(--sp-1);
}

.p-op-name {
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.p-op-detail {
  margin-top: var(--sp-1);
}

.p-op-detail summary {
  cursor: pointer;
  color: var(--ink-2);
  font-size: var(--text-xs);
}

/* ---------- 审批操作 ---------- */

.p-actions {
  margin-top: var(--sp-4);
  display: flex;
  gap: var(--sp-2);
  align-items: center;
}

.p-note {
  flex: 1;
  min-width: 200px;
}

.p-error {
  margin-top: var(--sp-2);
}

.p-resolution {
  margin-top: var(--sp-3);
  padding-top: var(--sp-3);
  border-top: 1px solid var(--hairline);
  font-size: var(--text-sm);
}

@media (max-width: 640px) {
  .p-actions {
    flex-wrap: wrap;
  }

  .p-note {
    flex-basis: 100%;
  }
}
</style>

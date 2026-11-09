<script setup>
/**
 * CRDetailView（/change-requests/:id）—— 审核单详情（只读展示）。
 * 面向“人”的部分在前：为什么变 / 变成什么样 / 不再成立的旧认知 / 验收条件 / 影响说明 / 决定；
 * 面向“Agent”的落地明细（Commit、模块版本）默认收起，人不需要看模块拆分。
 */
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/client.js'
import { useKeyNames } from '../api/keyNames.js'
import { fmtTime } from '../time.js'
import CRStatusBadge from '../components/CRStatusBadge.vue'
import VersionChip from '../components/VersionChip.vue'

const { keyName } = useKeyNames()
const route = useRoute()
const crId = computed(() => Number(route.params.id))

const cr = ref(null)
const loading = ref(true)
const error = ref('')
const showOps = ref({})

function errText(e) {
  const d = e?.detail ?? e
  return typeof d === 'string' ? d : JSON.stringify(d, null, 2)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    cr.value = await api.get(`/change-requests/${crId.value}`)
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

watch(crId, load, { immediate: true })

const VIA_TEXT = {
  cli: '命令行',
  natural_language: '对话中明确表态',
  api: '接口',
  agent_declared: 'Agent 自行判定（内部整理，未经人批准）',
}

const covered = computed(() => new Set(cr.value?.coverage?.covered || []))

function coveredBy(acId) {
  return (cr.value?.commits || []).filter((c) => (c.covers || []).includes(acId)).map((c) => c.seq)
}

const decided = computed(() => ['approved', 'applied', 'rejected', 'superseded'].includes(cr.value?.status) && cr.value?.decided_by)

function toggleOps(id) {
  showOps.value = { ...showOps.value, [id]: !showOps.value[id] }
}

function blockRows(c) {
  return c.result?.blocks || []
}

function capRows(c) {
  return c.result?.capability_versions || []
}
</script>

<template>
  <div class="page cr-page">
    <p class="crumb"><RouterLink to="/change-requests">← 审核单</RouterLink></p>

    <p v-if="loading" class="muted">加载中…</p>

    <div v-else-if="error" class="card state-card">
      <p class="error-text">{{ error }}</p>
      <button type="button" class="btn" @click="load">重试</button>
    </div>

    <template v-else-if="cr">
      <div class="title-row">
        <h1 class="page-title">{{ cr.title }}</h1>
        <span class="mono muted">#{{ cr.id }}</span>
        <CRStatusBadge :status="cr.status" />
        <span v-if="cr.kind === 'internal'" class="kind-tag" title="由 Agent 自行判定不改变业务内容，提交即生效">
          内部整理
        </span>
      </div>
      <p class="muted meta">
        {{ keyName(cr.created_by) }} 创建于 {{ fmtTime(cr.created_at) }}
        <template v-if="cr.submitted_at"> · 提交于 {{ fmtTime(cr.submitted_at) }}</template>
        <template v-if="cr.applied_at"> · 落地于 {{ fmtTime(cr.applied_at) }}</template>
      </p>

      <div v-if="cr.status === 'pending_review'" class="card notice">
        <strong>正等你确认。</strong>
        看完下面的内容后，直接告诉 Agent “同意”或“驳回，因为……”即可。
        <span class="muted">内容哈希（Agent 批准时会带上）：</span>
        <code class="mono">{{ cr.content_hash.slice(0, 12) }}…</code>
      </div>

      <div v-if="cr.kind === 'internal'" class="card notice">
        <strong>这是一张「内部整理」单：</strong>
        由 Agent 自行判定不改变业务内容，提交即生效，没有经过你批准。系统会在落地时检查
        规则、验收条件、API 的条目总和是否一字未变，变了会拒绝。
        <template v-if="cr.kind_reason">Agent 的理由：<em>{{ cr.kind_reason }}</em></template>
      </div>

      <p v-if="cr.supersedes_id" class="muted">
        取代审核单
        <RouterLink :to="`/change-requests/${cr.supersedes_id}`">#{{ cr.supersedes_id }}</RouterLink>
      </p>
      <p v-if="cr.superseded_by_id" class="muted">
        已被审核单
        <RouterLink :to="`/change-requests/${cr.superseded_by_id}`">#{{ cr.superseded_by_id }}</RouterLink>
        取代
      </p>

      <section class="card sec">
        <h2 class="sec-title">为什么变</h2>
        <p class="prose">{{ cr.intent || '（未填写）' }}</p>
      </section>

      <section class="card sec">
        <h2 class="sec-title">变成什么样</h2>
        <p class="prose">{{ cr.expected_outcome || '（未填写）' }}</p>
      </section>

      <section v-if="cr.obsolete.length" class="card sec">
        <h2 class="sec-title">不再成立的旧认知</h2>
        <ul class="plain-list">
          <li v-for="(o, i) in cr.obsolete" :key="i">{{ o }}</li>
        </ul>
      </section>

      <section class="card sec">
        <h2 class="sec-title">验收条件（{{ cr.acceptance.length }}）</h2>
        <table v-if="cr.acceptance.length" class="ac-table">
          <thead>
            <tr>
              <th class="col-id">编号</th>
              <th class="col-name">名称</th>
              <th>详述</th>
              <th class="col-cov">落地情况</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in cr.acceptance" :key="a.id">
              <td class="mono muted">{{ a.id }}</td>
              <td>{{ a.name }}</td>
              <td>{{ a.detail }}</td>
              <td class="cov">
                <template v-if="['approved', 'applied'].includes(cr.status)">
                  <span v-if="covered.has(a.id)" class="cov-ok">✓ Commit {{ coveredBy(a.id).map((n) => '#' + n).join('、') }}</span>
                  <span v-else class="cov-miss">待落地</span>
                </template>
                <span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">（还没有验收条件）</p>
      </section>

      <section v-if="cr.impact_note" class="card sec">
        <h2 class="sec-title">影响说明</h2>
        <p class="prose">{{ cr.impact_note }}</p>
      </section>

      <section v-if="decided || cr.status === 'rejected'" class="card sec">
        <h2 class="sec-title">{{ cr.status === 'rejected' ? '驳回记录' : cr.kind === 'internal' ? '生效记录' : '批准记录' }}</h2>
        <p class="meta-line">
          {{ keyName(cr.decided_by) }} · {{ fmtTime(cr.decided_at) }} · 方式：{{ VIA_TEXT[cr.decision_via] || cr.decision_via }}
        </p>
        <p v-if="cr.decision_evidence" class="quote">“{{ cr.decision_evidence }}”</p>
        <p v-if="cr.decision_note" class="prose">
          <span class="muted">{{ cr.status === 'rejected' ? '驳回理由：' : '备注：' }}</span>{{ cr.decision_note }}
        </p>
      </section>

      <section v-if="cr.commits.length" class="card sec">
        <h2 class="sec-title">落地明细（{{ cr.commits.length }} 个 Commit）<span class="muted tech">技术细节，供 Agent 与追溯使用</span></h2>
        <article v-for="c in cr.commits" :key="c.id" class="commit">
          <header class="commit-head">
            <strong>Commit #{{ c.seq }}</strong>
            <span class="muted">{{ c.change_note }}</span>
            <span class="muted mono">{{ fmtTime(c.created_at) }} · {{ keyName(c.created_by) }}</span>
          </header>
          <p class="muted">覆盖验收条件：{{ (c.covers || []).join('、') || '无' }}</p>
          <ul v-if="blockRows(c).length" class="plain-list">
            <li v-for="b in blockRows(c)" :key="b.block_id">
              <RouterLink :to="`/blocks/${b.block_id}`">{{ b.title }}</RouterLink>
              <VersionChip :version="b.version" />
              <span class="muted">{{ b.created ? '新建' : '更新' }} · 级别 {{ b.level }}</span>
            </li>
          </ul>
          <p v-if="capRows(c).length" class="muted">
            小业务版本：
            <template v-for="cv in capRows(c)" :key="cv.capability_id">
              <RouterLink :to="`/capabilities/${cv.capability_id}`">#{{ cv.capability_id }}</RouterLink>
              <VersionChip :version="cv.version" />{{ ' ' }}
            </template>
          </p>
          <p v-if="(c.result.archived_blocks || []).length" class="muted">归档模块：{{ c.result.archived_blocks.join('、') }}</p>
          <p v-if="(c.result.restored_blocks || []).length" class="muted">恢复模块：{{ c.result.restored_blocks.join('、') }}</p>
          <button type="button" class="btn btn-mini" @click="toggleOps(c.id)">
            {{ showOps[c.id] ? '收起 ops' : '查看 ops' }}
          </button>
          <pre v-if="showOps[c.id]" class="ops-pre mono">{{ JSON.stringify(c.ops, null, 2) }}</pre>
        </article>
      </section>
    </template>
  </div>
</template>

<style scoped>
.cr-page {
  max-width: 860px;
}

.crumb {
  margin-bottom: var(--sp-3);
  font-size: var(--text-sm);
}

.title-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.meta {
  margin: var(--sp-1) 0 var(--sp-4);
  font-size: var(--text-sm);
}

.state-card {
  margin-top: var(--sp-5);
  padding: var(--sp-6);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.notice {
  margin: var(--sp-3) 0;
  padding: var(--sp-3) var(--sp-4);
  background: #fff6e0;
  border-color: #f0d9a0;
  font-size: var(--text-sm);
}

.sec {
  margin-top: var(--sp-4);
  padding: var(--sp-4) var(--sp-5);
}

.sec-title {
  font-size: var(--text-md, 16px);
  font-weight: 600;
  margin-bottom: var(--sp-2);
}

.tech {
  margin-left: var(--sp-2);
  font-size: var(--text-sm);
  font-weight: 400;
}

.prose {
  white-space: pre-wrap;
  line-height: 1.7;
}

.plain-list {
  padding-left: var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.ac-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
}

.ac-table th,
.ac-table td {
  text-align: left;
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--hairline);
  vertical-align: top;
}

.ac-table th {
  color: var(--ink-2);
  font-weight: 500;
}

.col-id {
  width: 64px;
}

.col-name {
  width: 160px;
}

.col-cov {
  width: 150px;
}

.cov-ok {
  color: #1d6b34;
}

.cov-miss {
  color: #8a5a00;
}

.meta-line {
  color: var(--ink-2);
  font-size: var(--text-sm);
}

.quote {
  margin: var(--sp-2) 0;
  padding: var(--sp-2) var(--sp-3);
  border-left: 3px solid var(--hairline);
  background: var(--paper);
}

.commit {
  padding: var(--sp-3) 0;
  border-top: 1px solid var(--hairline);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  align-items: flex-start;
}

.commit-head {
  display: flex;
  gap: var(--sp-3);
  align-items: baseline;
  flex-wrap: wrap;
}

.ops-pre {
  width: 100%;
  max-height: 360px;
  overflow: auto;
  padding: var(--sp-3);
  background: var(--paper);
  border-radius: var(--radius);
  font-size: var(--text-xs, 12px);
}
.kind-tag {
  font-size: var(--text-xs);
  padding: 0 var(--sp-2);
  border: 1px solid var(--warning);
  color: var(--warning);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--warning) 7%, var(--card));
  white-space: nowrap;
}
</style>

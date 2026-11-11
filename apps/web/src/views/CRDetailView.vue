<script setup>
/**
 * CRDetailView（/change-requests/:id）—— 审核单详情（只读展示）。
 * 面向“人”的部分在前：为什么变 / 变成什么样 / 不再成立的旧认知 / 验收条件 / 影响说明 / 决定；
 * 面向“Agent”的落地明细（Commit、模块版本）默认收起，人不需要看模块拆分。
 */
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { resources } from '../api/resources.js'
import { useAsync } from '../composables/useAsync.js'
import { DECISION_VIA, label } from '../labels.js'
import { buildTrace, loadTraceData } from '../trace.js'
import { fmtTime } from '../time.js'
import CRStatusBadge from '../components/CRStatusBadge.vue'
import TraceChain from '../components/TraceChain.vue'
import LoadingState from '../components/LoadingState.vue'
import ErrorState from '../components/ErrorState.vue'
import KeyChip from '../components/KeyChip.vue'
import { useAutoRefresh } from '../composables/useAutoRefresh.js'

const route = useRoute()
const crId = computed(() => Number(route.params.id))

const { data: cr, loading, error, reload: load } = useAsync(() => resources.crs.get(crId.value), {
  watch: [crId],
})

// 落地明细：Commit → 受影响的模块 / 小业务（版本怎么变的）→ 现在的执行状态；
// 审核单取到之后再取这些关联数据，取不到不影响上面的主要内容
const traceQ = useAsync(
  async () => buildTrace({ cr: cr.value, ...(await loadTraceData(cr.value)) }),
  { watch: [cr], immediate: false, silentWatch: true },
)
useAutoRefresh(load)

// 内部整理单只该有改名和搬模块，不会产生任何新的模块版本。落地后哪些模块出现了新版本 / 被新建 / 归档 / 恢复，
// 是机械记下的事实，不是 Core 的判断——有就说明模块内容变了，值得人看一眼
const internalChanged = computed(() => {
  if (cr.value?.kind !== 'internal') return []
  return (traceQ.data.value || []).flatMap((c) => [
    ...(c.blocks || []).map((b) => ({ title: b.title, what: `${b.created ? '新建' : '新版本'} ${b.version}` })),
    ...(c.archived || []).map((m) => ({ title: m.title, what: '归档' })),
    ...(c.restored || []).map((m) => ({ title: m.title, what: '恢复' })),
  ])
})

const VIA_TEXT = DECISION_VIA

const covered = computed(() => new Set(cr.value?.coverage?.covered || []))

function coveredBy(acId) {
  return (cr.value?.commits || []).filter((c) => (c.covers || []).includes(acId)).map((c) => c.seq)
}

const decided = computed(() => ['approved', 'applied', 'rejected', 'superseded'].includes(cr.value?.status) && cr.value?.decided_by)

</script>

<template>
  <div class="page cr-page">
    <p class="crumb"><RouterLink to="/change-requests">← 审核单</RouterLink></p>

    <LoadingState v-if="loading" />
    <ErrorState v-else-if="error" :message="error" @retry="load" />

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
        <KeyChip :hint="cr.created_by" /> 创建于 {{ fmtTime(cr.created_at) }}
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
        由 Agent 自行判定不改变业务内容，提交即生效，没有经过你批准。<strong>系统不检查内容</strong>，
        到底改了什么请看下面的落地明细。
        <template v-if="cr.kind_reason">Agent 的理由：<em>{{ cr.kind_reason }}</em></template>
        <p v-if="internalChanged.length" class="warn-line">
          注意：内部整理只该有改名和搬模块，不该产生任何新的模块版本，这张单却有
          （{{ internalChanged.map((b) => `${b.title}：${b.what}`).join('、') }}）。
          说明模块的内容变了（规则、验收条件、API 或背景），这应该是业务变更单，要经你批准。
        </p>
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
          <KeyChip :hint="cr.decided_by" /> · {{ fmtTime(cr.decided_at) }} · 方式：{{ label(VIA_TEXT, cr.decision_via) }}
        </p>
        <p v-if="cr.decision_evidence" class="quote">“{{ cr.decision_evidence }}”</p>
        <p v-if="cr.decision_note" class="prose">
          <span class="muted">{{ cr.status === 'rejected' ? '驳回理由：' : '备注：' }}</span>{{ cr.decision_note }}
        </p>
      </section>

      <section v-if="cr.commits.length" class="card sec">
        <h2 class="sec-title">
          落地明细（{{ cr.commits.length }} 个 Commit）
          <span class="muted tech">改了哪些模块、版本怎么变的、现在做到哪了</span>
        </h2>
        <p v-if="cr.kind === 'internal'" class="muted tech-note">
          这是内部整理单，系统不检查内容。内部整理只该有改名和搬模块，下面如果出现了模块的新版本，说明模块内容变了。
        </p>
        <p v-if="traceQ.loading.value" class="muted tech-note">正在整理…</p>
        <p v-else-if="traceQ.error.value" class="error-text tech-note">{{ traceQ.error.value }}</p>
        <TraceChain v-else-if="traceQ.data.value" :commits="traceQ.data.value" />
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

.warn-line {
  margin: var(--sp-2) 0 0;
  color: #8a4b00;
  font-weight: 500;
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

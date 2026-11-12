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
        <span class="mono muted id">#{{ cr.id }}</span>
        <CRStatusBadge :status="cr.status" />
        <span v-if="cr.kind === 'internal'" class="kind-tag">内部整理</span>
      </div>
      <p class="muted meta">
        <KeyChip :hint="cr.created_by" /> · 创建 {{ fmtTime(cr.created_at) }}
        <template v-if="cr.submitted_at"> · 提交 {{ fmtTime(cr.submitted_at) }}</template>
        <template v-if="cr.applied_at"> · 落地 {{ fmtTime(cr.applied_at) }}</template>
      </p>

      <p v-if="cr.status === 'pending_review'" class="notice">
        <strong>等你确认</strong>
        <span class="muted">哈希 <code class="mono">{{ cr.content_hash.slice(0, 12) }}…</code></span>
      </p>

      <div v-if="cr.kind === 'internal'" class="notice is-watch">
        <p><strong>内部整理单</strong>：Agent 自行判定，没有经过你批准<template v-if="cr.kind_reason">。理由：{{ cr.kind_reason }}</template></p>
        <p v-if="internalChanged.length" class="warn-line">
          越界：内部整理不该产生模块新版本，这张单却有（{{ internalChanged.map((b) => `${b.title}：${b.what}`).join('、') }}）。应当是业务变更单。
        </p>
      </div>

      <p v-if="cr.supersedes_id" class="muted rel">
        取代
        <RouterLink :to="`/change-requests/${cr.supersedes_id}`">#{{ cr.supersedes_id }}</RouterLink>
      </p>
      <p v-if="cr.superseded_by_id" class="muted rel">
        已被
        <RouterLink :to="`/change-requests/${cr.superseded_by_id}`">#{{ cr.superseded_by_id }}</RouterLink>
        取代
      </p>

      <section class="sec">
        <h2 class="sec-title">为什么变</h2>
        <p class="prose">{{ cr.intent || '—' }}</p>
      </section>

      <section class="sec">
        <h2 class="sec-title">变成什么样</h2>
        <p class="prose">{{ cr.expected_outcome || '—' }}</p>
      </section>

      <section v-if="cr.obsolete.length" class="sec">
        <h2 class="sec-title">不再成立</h2>
        <ul class="plain-list">
          <li v-for="(o, i) in cr.obsolete" :key="i">{{ o }}</li>
        </ul>
      </section>

      <section class="sec">
        <h2 class="sec-title">验收条件 <span class="count">{{ cr.acceptance.length }}</span></h2>
        <table v-if="cr.acceptance.length" class="ac-table">
          <tbody>
            <tr v-for="a in cr.acceptance" :key="a.id">
              <td class="mono muted idx">{{ a.id }}</td>
              <td class="name">{{ a.name }}</td>
              <td class="detail">{{ a.detail }}</td>
              <td class="cov">
                <template v-if="['approved', 'applied'].includes(cr.status)">
                  <span v-if="covered.has(a.id)" class="cov-ok">✓ Commit {{ coveredBy(a.id).map((n) => '#' + n).join('、') }}</span>
                  <span v-else class="cov-miss">待落地</span>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">无</p>
      </section>

      <section v-if="cr.impact_note" class="sec">
        <h2 class="sec-title">影响</h2>
        <p class="prose">{{ cr.impact_note }}</p>
      </section>

      <section v-if="decided || cr.status === 'rejected'" class="sec">
        <h2 class="sec-title">{{ cr.status === 'rejected' ? '驳回' : cr.kind === 'internal' ? '生效' : '批准' }}</h2>
        <p class="meta-line">
          <KeyChip :hint="cr.decided_by" /> · {{ fmtTime(cr.decided_at) }} · {{ label(VIA_TEXT, cr.decision_via) }}
        </p>
        <p v-if="cr.decision_evidence" class="quote">“{{ cr.decision_evidence }}”</p>
        <p v-if="cr.decision_note" class="prose">
          <span class="muted">{{ cr.status === 'rejected' ? '理由：' : '备注：' }}</span>{{ cr.decision_note }}
        </p>
      </section>

      <section v-if="cr.commits.length" class="sec">
        <h2 class="sec-title">落地明细 <span class="count">{{ cr.commits.length }} 个 Commit</span></h2>
        <p v-if="traceQ.loading.value" class="muted">正在整理…</p>
        <p v-else-if="traceQ.error.value" class="error-text">{{ traceQ.error.value }}</p>
        <TraceChain v-else-if="traceQ.data.value" :commits="traceQ.data.value" />
      </section>
    </template>
  </div>
</template>

<style scoped>
.crumb {
  margin-bottom: var(--sp-3);
  font-size: var(--text-sm);
}

.title-row {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2) var(--sp-3);
  flex-wrap: wrap;
}

.id {
  font-size: var(--text-sm);
}

.meta {
  margin: var(--sp-1) 0 var(--sp-3);
  font-size: var(--text-sm);
}

.rel {
  font-size: var(--text-sm);
}

/* 需要你注意的一句话：前面一个小圆点，不套盒子 */
.notice {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--sp-1) var(--sp-3);
  margin: var(--sp-3) 0;
  padding: var(--sp-1) 0;
}

.notice::before {
  content: '';
  align-self: center;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
}

.notice.is-watch {
  display: block;
}

.notice.is-watch::before {
  display: none;
}

.warn-line {
  margin-top: var(--sp-1);
  color: var(--danger);
}

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

.prose {
  white-space: pre-wrap;
  line-height: 1.75;
}

.plain-list {
  padding-left: var(--sp-5);
  list-style: disc;
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

/* 验收条件：编号 · 名称 · 说明 · 落地情况；窄屏折成两行 */
.ac-table {
  width: 100%;
  border-collapse: collapse;
}

.ac-table td {
  text-align: left;
  padding: var(--sp-2) var(--sp-3) var(--sp-2) 0;
  border-top: 1px solid var(--hairline);
  vertical-align: top;
}

.idx {
  width: 1%;
  white-space: nowrap;
  font-size: var(--text-xs);
}

.name {
  width: 28%;
  min-width: 7em;
  font-weight: 500;
}

.cov {
  width: 1%;
  white-space: nowrap;
  font-size: var(--text-sm);
}

.cov-ok {
  color: var(--success);
}

.cov-miss {
  color: var(--warning);
}

.meta-line {
  color: var(--ink-2);
  font-size: var(--text-sm);
}

.quote {
  margin: var(--sp-2) 0;
  padding: var(--sp-1) var(--sp-3);
  border-left: 3px solid var(--hairline-2);
  color: var(--ink-2);
}

.kind-tag {
  font-size: var(--text-xs);
  padding: 0 var(--sp-2);
  border-radius: 999px;
  background: var(--warning-wash);
  color: var(--warning);
  white-space: nowrap;
}

@media (max-width: 560px) {
  .ac-table,
  .ac-table tbody {
    display: block;
  }

  .ac-table tr {
    display: grid;
    grid-template-columns: auto 1fr auto;
    column-gap: var(--sp-2);
    padding: var(--sp-2) 0;
    border-top: 1px solid var(--hairline);
  }

  .ac-table td {
    padding: 0;
    border: none;
    width: auto;
  }

  .ac-table .detail {
    grid-column: 1 / -1;
    margin-top: 2px;
    color: var(--ink-2);
    font-size: var(--text-sm);
  }
}
</style>

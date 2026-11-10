<script setup>
/**
 * OverviewView（/）—— 总览：回答「现在有什么需要我关注的」。
 * 需要你行动的（待确认的审核单、卡住的任务）最醒目；事后过目的（Agent 自行判定的内部整理）
 * 单独一块；其余是进展和数字。只做展示，没有任何操作。
 */
import { computed } from 'vue'
import { resources } from '../api/resources.js'
import { useAsync } from '../composables/useAsync.js'
import { isRead } from '../activity.js'
import { buildOverview } from '../overview.js'
import PageHeader from '../components/PageHeader.vue'
import AttentionSection from '../components/AttentionSection.vue'
import StatCard from '../components/StatCard.vue'
import ActivityItem from '../components/ActivityItem.vue'
import ExecStatusBadge from '../components/ExecStatusBadge.vue'
import EmptyState from '../components/EmptyState.vue'
import KeyChip from '../components/KeyChip.vue'
import TimeAgo from '../components/TimeAgo.vue'
import { useAutoRefresh } from '../composables/useAutoRefresh.js'

const crsQ = useAsync(() => resources.crs.list())
const workQ = useAsync(() => resources.work.list())
const treeQ = useAsync(() => resources.tree())
const activityQ = useAsync(() => resources.activity({ limit: 100 }))

function reloadAll(opts) {
  return Promise.all([crsQ.reload(opts), workQ.reload(opts), treeQ.reload(opts), activityQ.reload(opts)])
}
useAutoRefresh(reloadAll)

const o = computed(() =>
  buildOverview({
    crs: crsQ.data.value || [],
    work: workQ.data.value || [],
    tree: treeQ.data.value || [],
  }),
)

const recent = computed(() => (activityQ.data.value || []).filter((x) => !isRead(x)).slice(0, 10))

const loadedOnce = computed(() => crsQ.data.value && workQ.data.value && treeQ.data.value)
const showEmptyGuide = computed(() => loadedOnce.value && o.value.isEmpty)

const crSub = computed(() => {
  const c = o.value.counts.crs
  const parts = [
    c.pending_review && `待确认 ${c.pending_review}`,
    c.approved && `进行中 ${c.approved}`,
    c.applied && `已落地 ${c.applied}`,
    c.rejected && `已驳回 ${c.rejected}`,
  ].filter(Boolean)
  return parts.join(' · ') || '还没有审核单'
})

const crTotal = computed(() => Object.values(o.value.counts.crs).reduce((a, b) => a + b, 0))
const workTotal = computed(() => Object.values(o.value.counts.work).reduce((a, b) => a + b, 0))

const workSub = computed(() => {
  const c = o.value.counts.work
  const parts = [
    c.pending && `待领取 ${c.pending}`,
    c.in_progress && `进行中 ${c.in_progress}`,
    c.implemented && `待验收 ${c.implemented}`,
    c.verified && `已验收 ${c.verified}`,
  ].filter(Boolean)
  return parts.join(' · ') || '还没有任务'
})

const summary = computed(() => {
  if (!loadedOnce.value || o.value.isEmpty) return ''
  const n = o.value.pending.length + o.value.stuck.length
  if (n) return `有 ${n} 件事在等你处理。`
  if (o.value.internal.length) return `没有需要你处理的事；有 ${o.value.internal.length} 张 Agent 自行判定的内部整理单可以过目。`
  return '没有需要你处理的事，一切正常。'
})
</script>

<template>
  <div class="page overview-page">
    <PageHeader eyebrow="Overview" title="总览" desc="现在有什么需要你关注的。这里只做展示：批准、驳回都在对话里告诉 Agent。">
      <p v-if="summary" class="summary" :class="{ calm: !o.pending.length && !o.stuck.length }">{{ summary }}</p>
    </PageHeader>

    <EmptyState
      v-if="showEmptyGuide"
      title="还没有任何内容"
      text="SpecLock 还是空的。让需求 Agent 把你的想法整理成审核单，你在对话里确认后，它会提交 Commit 建立 大业务 → 小业务 → 模块；模块发布后会自动产生待办，交给执行 Agent。"
    >
      <RouterLink to="/mcp" class="btn">查看 Agent 接入说明</RouterLink>
    </EmptyState>

    <template v-else>
      <div class="stats">
        <StatCard label="已发布模块" :value="o.counts.modules" sub="点击查看文档树" to="/tree" />
        <StatCard
          label="已验收"
          :value="`${o.counts.verifiedPercent}%`"
          :sub="`${o.counts.verifiedModules} / ${o.counts.modules} 个模块的当前版本`"
          :percent="o.counts.verifiedPercent"
          to="/work"
        />
        <StatCard label="审核单" :value="crTotal" :sub="crSub" to="/change-requests" />
        <StatCard label="任务" :value="workTotal" :sub="workSub" to="/work" />
      </div>

      <AttentionSection
        title="等我确认"
        hint="看完内容后，直接在对话里告诉 Agent「同意」或「驳回，因为……」。"
        tone="alert"
        :count="o.pending.length"
        :loading="crsQ.loading.value"
        :error="crsQ.error.value"
        empty-text="没有等你确认的审核单。"
        to="/change-requests"
      >
        <li v-for="c in o.pending" :key="c.id" class="row">
          <RouterLink :to="`/change-requests/${c.id}`" class="row-title">#{{ c.id }} {{ c.title }}</RouterLink>
          <span class="row-meta muted">
            <KeyChip :hint="c.created_by" /> 提交于 <TimeAgo :value="c.submitted_at || c.created_at" />
            · {{ (c.acceptance || []).length }} 条验收条件
          </span>
        </li>
      </AttentionSection>

      <AttentionSection
        title="卡住的任务"
        hint="被阻塞：执行 Agent 遇到规格里没写清的业务问题，在等答复。失败：没做成或验收没通过。"
        tone="alert"
        :count="o.stuck.length"
        :loading="workQ.loading.value"
        :error="workQ.error.value"
        empty-text="没有被阻塞或失败的任务。"
        to="/work"
      >
        <li v-for="w in o.stuck" :key="w.id" class="row">
          <div class="row-line">
            <ExecStatusBadge :status="w.status" />
            <RouterLink :to="`/blocks/${w.block_id}?version=${w.version}`" class="row-title">{{ w.block_title }}</RouterLink>
            <span class="mono muted">v{{ w.version }}</span>
            <TimeAgo class="row-time muted" :value="w.updated_at" />
          </div>
          <p v-if="w.reason" class="row-reason">{{ w.reason }}</p>
          <p class="row-meta muted">{{ w.business }} / {{ w.capability_title }}</p>
        </li>
      </AttentionSection>

      <AttentionSection
        title="Agent 自行判定的内部整理"
        hint="需求 Agent 自行判定这些没有改变业务内容，所以没有经过你批准。系统不检查内容，点进去看它实际改了什么；内部整理只该有改名和搬模块，出现模块新版本的就是越界。最近 7 天："
        tone="watch"
        :count="o.internal.length"
        :loading="crsQ.loading.value"
        :error="crsQ.error.value"
        empty-text="最近没有内部整理。"
      >
        <li v-for="c in o.internal" :key="c.id" class="row">
          <div class="row-line">
            <RouterLink :to="`/change-requests/${c.id}`" class="row-title">#{{ c.id }} {{ c.title }}</RouterLink>
            <TimeAgo class="row-time muted" :value="c.decided_at || c.submitted_at || c.created_at" />
          </div>
          <p class="row-reason">理由：{{ c.kind_reason }}</p>
          <p class="row-meta muted"><KeyChip :hint="c.created_by" /></p>
        </li>
      </AttentionSection>

      <AttentionSection
        title="等验收"
        hint="执行 Agent 已提交实现，等测试 Agent 独立验收。"
        :count="o.waiting.length"
        :loading="workQ.loading.value"
        :error="workQ.error.value"
        empty-text="没有等验收的任务。"
        to="/work"
      >
        <li v-for="w in o.waiting" :key="w.id" class="row">
          <div class="row-line">
            <RouterLink :to="`/blocks/${w.block_id}?version=${w.version}`" class="row-title">{{ w.block_title }}</RouterLink>
            <span class="mono muted">v{{ w.version }}</span>
            <span class="row-meta muted">实现者 <KeyChip :hint="w.claimed_by" /></span>
            <TimeAgo class="row-time muted" :value="w.updated_at" />
          </div>
        </li>
      </AttentionSection>

      <AttentionSection
        title="进行中"
        :count="o.inProgress.length"
        :loading="workQ.loading.value"
        :error="workQ.error.value"
        empty-text="现在没有人在做任务。"
        to="/work"
      >
        <li v-for="w in o.inProgress" :key="w.id" class="row">
          <div class="row-line">
            <RouterLink :to="`/blocks/${w.block_id}?version=${w.version}`" class="row-title">{{ w.block_title }}</RouterLink>
            <span class="mono muted">v{{ w.version }}</span>
            <span class="row-meta muted"><KeyChip :hint="w.claimed_by" /> 领取</span>
            <TimeAgo class="row-time muted" :value="w.updated_at" />
          </div>
        </li>
      </AttentionSection>

      <section class="card recent">
        <header class="recent-head">
          <h2 class="recent-title">最近活动</h2>
          <RouterLink v-if="recent.length" to="/activity" class="recent-all">查看全部 →</RouterLink>
        </header>
        <p v-if="activityQ.loading.value" class="muted small">加载中…</p>
        <p v-else-if="activityQ.error.value" class="error-text small">{{ activityQ.error.value }}</p>
        <p v-else-if="!recent.length" class="muted small">还没有活动记录。</p>
        <ul v-else>
          <ActivityItem v-for="a in recent" :key="a.id" :item="a" />
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.overview-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.summary {
  margin-top: var(--sp-3);
  font-size: var(--text-lg);
  font-weight: 500;
  color: var(--warning);
}

.summary.calm {
  color: var(--success);
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: var(--sp-3);
}

.row {
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--hairline);
  font-size: var(--text-sm);
}

.row:last-child {
  border-bottom: none;
}

.row-line {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.row-title {
  font-weight: 500;
}

.row-meta {
  font-size: var(--text-xs);
}

.row-time {
  margin-left: auto;
  font-size: var(--text-xs);
}

.row-reason {
  margin-top: 2px;
  color: var(--ink);
  overflow-wrap: anywhere;
}

.recent {
  padding: var(--sp-4) var(--sp-5);
}

.recent-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.recent-title {
  font-size: var(--text-md);
  font-weight: 600;
}

.recent-all {
  margin-left: auto;
  font-size: var(--text-sm);
}

.small {
  margin-top: var(--sp-2);
  font-size: var(--text-sm);
}
</style>

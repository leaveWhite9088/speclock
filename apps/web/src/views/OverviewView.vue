<script setup>
/**
 * OverviewView（/）—— 总览：回答「现在有什么需要我关注的」。
 * 需要你处理的（待确认的审核单、卡住的任务，合成一组）最醒目；数字区只放进度（已完成、已验收）；事后过目的（Agent 自行判定的内部整理）
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

// 待验收和进行中合成一组「任务进展」
const progress = computed(() => [...o.value.waiting, ...o.value.inProgress])

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
    <PageHeader title="总览">
      <p v-if="summary" class="summary" :class="{ calm: !o.pending.length && !o.stuck.length }">{{ summary }}</p>
    </PageHeader>

    <EmptyState
      v-if="showEmptyGuide"
      title="还没有任何内容"
      text="让需求 Agent 把想法整理成审核单，你确认后它提交 Commit，规格就有了。"
    >
      <RouterLink to="/mcp" class="btn">Agent 接入</RouterLink>
    </EmptyState>

    <template v-else>
      <div class="stats">
        <StatCard
          label="已完成"
          :value="`${o.counts.workDonePercent}%`"
          :sub="`${o.counts.workDone} / ${o.counts.workTotal} 个任务`"
          :percent="o.counts.workDonePercent"
          to="/work"
        />
        <StatCard
          label="已验收"
          :value="`${o.counts.verifiedPercent}%`"
          :sub="`${o.counts.verifiedModules} / ${o.counts.modules} 个模块的当前版本`"
          :percent="o.counts.verifiedPercent"
          to="/work"
        />
      </div>

      <AttentionSection
        title="等我处理"
        tone="alert"
        open
        :count="o.pending.length + o.stuck.length"
        :loading="crsQ.loading.value || workQ.loading.value"
        :error="crsQ.error.value || workQ.error.value"
      >
        <li v-for="c in o.pending" :key="c.id">
          <RouterLink :to="`/change-requests/${c.id}`" class="row">
            <span class="dot is-accent"></span>
            <span class="row-main">
              <span class="row-title">#{{ c.id }} {{ c.title }}</span>
              <span class="row-sub">
                <KeyChip :hint="c.created_by" /> · {{ (c.acceptance || []).length }} 条验收
              </span>
            </span>
            <TimeAgo class="row-meta" :value="c.submitted_at || c.created_at" />
          </RouterLink>
        </li>
        <li v-for="w in o.stuck" :key="w.id">
          <RouterLink :to="`/blocks/${w.block_id}?version=${w.version}`" class="row">
            <span class="dot" :class="w.status === 'failed' ? 'is-bad' : 'is-warn'"></span>
            <span class="row-main">
              <span class="row-title">{{ w.block_title }} <span class="mono muted">v{{ w.version }}</span></span>
              <span v-if="w.reason" class="row-sub reason">{{ w.reason }}</span>
              <span class="row-sub">{{ w.business }} / {{ w.capability_title }}</span>
            </span>
            <span class="row-meta"><ExecStatusBadge :status="w.status" /></span>
          </RouterLink>
        </li>
      </AttentionSection>

      <AttentionSection title="任务进展" open :count="progress.length" :loading="workQ.loading.value" :error="workQ.error.value" to="/work">
        <li v-for="w in progress" :key="w.id">
          <RouterLink :to="`/blocks/${w.block_id}?version=${w.version}`" class="row">
            <span class="dot is-accent"></span>
            <span class="row-main">
              <span class="row-title">{{ w.block_title }} <span class="mono muted">v{{ w.version }}</span></span>
              <span class="row-sub"><KeyChip :hint="w.claimed_by" /> · <TimeAgo :value="w.updated_at" /></span>
            </span>
            <span class="row-meta"><ExecStatusBadge :status="w.status" /></span>
          </RouterLink>
        </li>
      </AttentionSection>

      <AttentionSection title="内部整理" :count="o.internal.length" :loading="crsQ.loading.value" :error="crsQ.error.value">
        <li v-for="c in o.internal" :key="c.id">
          <RouterLink :to="`/change-requests/${c.id}`" class="row">
            <span class="dot"></span>
            <span class="row-main">
              <span class="row-title">#{{ c.id }} {{ c.title }}</span>
              <span class="row-sub">{{ c.kind_reason }}</span>
            </span>
            <TimeAgo class="row-meta" :value="c.decided_at || c.submitted_at || c.created_at" />
          </RouterLink>
        </li>
      </AttentionSection>

      <AttentionSection title="最近活动" :count="recent.length" :loading="activityQ.loading.value" :error="activityQ.error.value" to="/activity">
        <ActivityItem v-for="a in recent" :key="a.id" :item="a" />
      </AttentionSection>
    </template>
  </div>
</template>

<style scoped>
.summary {
  margin-top: var(--sp-1);
  font-size: var(--text-lg);
  color: var(--contract);
}

.summary.calm {
  color: var(--success);
}

/* 几个数字并排，中间只有细线，不用卡片 */
.stats {
  display: flex;
  flex-wrap: wrap;
  margin: var(--sp-5) 0 var(--sp-2);
  padding: var(--sp-3) 0;
  border-top: 1px solid var(--hairline);
  border-bottom: 1px solid var(--hairline);
}

.stats > * {
  flex: 1 1 120px;
  min-width: 0;
}

.stats > * + * {
  border-left: 1px solid var(--hairline);
}

.reason {
  color: var(--ink);
}

@container (max-width: 520px) {
  .stats > * {
    flex-basis: 45%;
  }

}
</style>

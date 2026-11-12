<script setup>
/**
 * ActivityView（/activity）—— 活动时间线：谁在什么时候做了什么。
 * 按天分组；可按类别 / 谁 / 时间范围 / 对象筛选（筛选条件写在地址栏，可以分享）；
 * 默认不含「读取」（读取占了日志的绝大部分）；「加载更多」按游标翻页。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { resources } from '../api/resources.js'
import { useKeyNames } from '../api/keyNames.js'
import { useAsync } from '../composables/useAsync.js'
import { errText } from '../errors.js'
import { CATEGORIES, RANGES, activityParams, groupByDay, parseTarget } from '../activity.js'
import PageHeader from '../components/PageHeader.vue'
import AsyncState from '../components/AsyncState.vue'
import ActivityItem from '../components/ActivityItem.vue'
import { useAutoRefresh } from '../composables/useAutoRefresh.js'

const PAGE = 50
const route = useRoute()
const router = useRouter()
const { keyName } = useKeyNames()

const q = (name) => (typeof route.query[name] === 'string' ? route.query[name] : '')
const category = ref(q('cat'))
const actor = ref(q('actor'))
const range = ref(q('range'))
const target = ref(q('target'))

// 地址栏变化（例如从别的页面带着 ?target=… 跳过来）时，同步到筛选条件
watch(
  () => route.query,
  () => {
    category.value = q('cat')
    actor.value = q('actor')
    range.value = q('range')
    target.value = q('target')
  },
)

// 筛选条件同步到地址栏（replace，不污染历史）
watch([category, actor, range, target], ([c, a, r, t]) => {
  router.replace({ query: { cat: c || undefined, actor: a || undefined, range: r || undefined, target: t || undefined } })
})

const extra = ref([])
const hasMore = ref(false)
const loadingMore = ref(false)
const moreError = ref('')

const { data, loading, error, reload } = useAsync(
  async () => {
    extra.value = []
    moreError.value = ''
    const page = await resources.activity(activityParams({ category: category.value, actor: actor.value, range: range.value, target: target.value, limit: PAGE }))
    hasMore.value = page.length >= PAGE
    return page
  },
  { watch: [category, actor, range, target] },
)

// 自动刷新：还在第一页时静默刷新；已经「加载更多」翻过页就不动列表（免得内容跳动），提示有新活动
const hasNew = ref(false)
useAutoRefresh((opts) => (extra.value.length ? (hasNew.value = true) : reload(opts)))
function refreshNow() {
  hasNew.value = false
  reload()
}

const items = computed(() => [...(data.value || []), ...extra.value])
const groups = computed(() => groupByDay(items.value))

async function loadMore() {
  const last = items.value.at(-1)
  if (!last) return
  loadingMore.value = true
  moreError.value = ''
  try {
    const page = await resources.activity(
      activityParams({ category: category.value, actor: actor.value, range: range.value, target: target.value, beforeId: last.id, limit: PAGE }),
    )
    extra.value = [...extra.value, ...page]
    hasMore.value = page.length >= PAGE
  } catch (e) {
    moreError.value = errText(e)
  } finally {
    loadingMore.value = false
  }
}

// 「谁」的候选：有 key.manage 权限时用完整的 key 列表，否则退回到当前已加载记录里出现过的
const keys = ref([])
resources
  .keys()
  .then((list) => (keys.value = list))
  .catch(() => {})

const actorOptions = computed(() => {
  const seen = new Map()
  for (const k of keys.value) seen.set(k.hint, keyName(k.hint))
  for (const a of items.value) if (!seen.has(a.actor)) seen.set(a.actor, keyName(a.actor))
  if (actor.value && !seen.has(actor.value)) seen.set(actor.value, keyName(actor.value))
  return [...seen.entries()].map(([hint, name]) => ({ hint, name }))
})

const targetText = computed(() => (target.value ? parseTarget(target.value).text : ''))
const hasFilter = computed(() => category.value || actor.value || range.value || target.value)

function clearFilters() {
  category.value = ''
  actor.value = ''
  range.value = ''
  target.value = ''
}
</script>

<template>
  <div class="page activity-page">
    <PageHeader title="活动" />

    <div class="filters">
      <label class="f">
        <span class="f-label">类别</span>
        <select v-model="category" class="input">
          <option v-for="c in CATEGORIES" :key="c.key" :value="c.key">{{ c.label }}</option>
        </select>
      </label>
      <label class="f">
        <span class="f-label">谁</span>
        <select v-model="actor" class="input">
          <option value="">所有人</option>
          <option v-for="o in actorOptions" :key="o.hint" :value="o.hint">{{ o.name }}</option>
        </select>
      </label>
      <label class="f">
        <span class="f-label">时间</span>
        <select v-model="range" class="input">
          <option v-for="r in RANGES" :key="r.key" :value="r.key">{{ r.label }}</option>
        </select>
      </label>
      <span v-if="target" class="tag">
        {{ targetText }}
        <button type="button" class="tag-x" aria-label="取消对象筛选" @click="target = ''">×</button>
      </span>
      <button v-if="hasFilter" type="button" class="link-btn" @click="clearFilters">清除</button>
    </div>

    <p v-if="hasNew" class="new-banner">
      有新活动 <button type="button" class="link-btn" @click="refreshNow">刷新</button>
    </p>

    <AsyncState
      :loading="loading"
      :error="error"
      :empty="!items.length"
      :empty-title="hasFilter ? '没有符合条件的活动' : '还没有活动'"
      @retry="reload"
    >
      <section v-for="g in groups" :key="g.key" class="day">
        <h2 class="day-title">{{ g.label }}<span class="count">{{ g.items.length }}</span></h2>
        <ul class="list">
          <ActivityItem v-for="a in g.items" :key="a.id" :item="a" expandable />
        </ul>
      </section>

      <p v-if="moreError" class="error-text more-error" role="alert">{{ moreError }}</p>
      <div v-if="hasMore" class="more">
        <button type="button" class="btn" :disabled="loadingMore" @click="loadMore">
          {{ loadingMore ? '加载中…' : '加载更多' }}
        </button>
      </div>
    </AsyncState>
  </div>
</template>

<style scoped>
.filters {
  margin-top: var(--sp-4);
  display: flex;
  align-items: flex-end;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.f {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1 1 130px;
  max-width: 200px;
}

.f-label {
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  padding: 3px var(--sp-3);
  border-radius: 999px;
  background: var(--contract-wash);
  color: var(--contract);
  font-size: var(--text-sm);
}

.tag-x {
  appearance: none;
  border: none;
  background: none;
  color: inherit;
  cursor: pointer;
  font-size: var(--text-md);
  line-height: 1;
}

.new-banner {
  margin-top: var(--sp-3);
  font-size: var(--text-sm);
  color: var(--contract);
}

.link-btn {
  appearance: none;
  border: none;
  background: none;
  padding: 0;
  color: var(--contract);
  font: inherit;
  font-size: var(--text-sm);
  cursor: pointer;
  text-decoration: underline;
}

.day {
  margin-top: var(--sp-5);
}

.day-title {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: 600;
  margin-bottom: var(--sp-1);
}

.day-title .count {
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: 400;
  color: var(--ink-2);
}

.day .list > :last-child {
  border-bottom: 1px solid var(--hairline);
}

.more {
  margin-top: var(--sp-5);
  text-align: center;
}

.more-error {
  margin-top: var(--sp-3);
}
</style>

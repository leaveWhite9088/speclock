<script setup>
/**
 * SearchView（/search?q=…）—— 搜索结果：按 模块 / 规则 / 验收条件 / API / 审核单 分组，
 * 命中词高亮；规则和验收条件可以直达模块页里的那一行。
 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { resources } from '../api/resources.js'
import { useAsync } from '../composables/useAsync.js'
import { groupHits, highlightSegments, hitLink, hitPath } from '../search.js'
import PageHeader from '../components/PageHeader.vue'
import AsyncState from '../components/AsyncState.vue'
import CRStatusBadge from '../components/CRStatusBadge.vue'
import { useAutoRefresh } from '../composables/useAutoRefresh.js'

const route = useRoute()
const q = computed(() => (typeof route.query.q === 'string' ? route.query.q.trim() : ''))

const { data, loading, error, reload } = useAsync(
  () => (q.value ? resources.search({ q: q.value }) : Promise.resolve(null)),
  { watch: [q] },
)

useAutoRefresh(reload)
const groups = computed(() => groupHits(data.value?.hits || []))
const total = computed(() => data.value?.total ?? 0)
</script>

<template>
  <div class="page search-page">
    <PageHeader title="搜索" />

    <p v-if="!q" class="muted hint">输入关键词，回车搜索（<kbd>/</kbd> 聚焦搜索框）</p>

    <AsyncState
      v-else
      :loading="loading"
      :error="error"
      :empty="!total"
      :empty-title="`没有找到「${q}」`"
      @retry="reload"
    >
      <p class="count muted">
        {{ total }} 处命中<template v-if="data?.truncated">，只显示前 {{ data.hits.length }} 条</template>
      </p>

      <section v-for="g in groups" :key="g.type" class="group">
        <h2 class="group-title">{{ g.label }}<span class="muted n">{{ g.hits.length }}</span></h2>
        <div class="card">
          <ul>
            <li v-for="(h, i) in g.hits" :key="`${g.type}-${i}`" class="hit">
              <div class="hit-head">
                <RouterLink :to="hitLink(h)" class="hit-title">
                  <template v-if="h.item_id && h.type !== 'api'"><span class="mono id">{{ h.item_id }}</span> </template>
                  <template v-for="(s, j) in highlightSegments(h.title, q)" :key="j"><mark v-if="s.hit">{{ s.text }}</mark><template v-else>{{ s.text }}</template></template>
                </RouterLink>
                <CRStatusBadge v-if="h.type === 'cr'" :status="h.status" />
                <span v-if="h.type === 'cr' && h.kind === 'internal'" class="muted tag">内部整理</span>
              </div>
              <p class="hit-path muted">{{ hitPath(h) }} · {{ h.field }}</p>
              <p class="hit-snippet">
                <template v-for="(s, j) in highlightSegments(h.snippet, q)" :key="j"><mark v-if="s.hit">{{ s.text }}</mark><template v-else>{{ s.text }}</template></template>
              </p>
            </li>
          </ul>
        </div>
      </section>
    </AsyncState>
  </div>
</template>

<style scoped>
.hint,
.count {
  margin-top: var(--sp-4);
  font-size: var(--text-sm);
}

kbd {
  padding: 0 var(--sp-2);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  background: var(--card);
  font-size: var(--text-xs);
}

.group {
  margin-top: var(--sp-5);
}

.group-title {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: 600;
  margin-bottom: var(--sp-2);
}

.n {
  margin-left: var(--sp-2);
  font-size: var(--text-xs);
  font-weight: 400;
}

.hit {
  padding: var(--sp-3) var(--sp-1);
  border-top: 1px solid var(--hairline);
}

.hit-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.hit-title {
  font-weight: 500;
}

.id {
  color: var(--ink-2);
}

.hit-path,
.tag {
  font-size: var(--text-xs);
}

.hit-snippet {
  margin-top: var(--sp-1);
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}

mark {
  background: color-mix(in srgb, var(--warning) 22%, transparent);
  color: inherit;
  border-radius: 2px;
  padding: 0 1px;
}
</style>

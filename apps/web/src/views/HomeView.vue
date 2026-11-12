<script setup>
/**
 * HomeView（/）—— 文档树导航页：项目 → 大业务 → 小业务 → 模块 四级可展开树，
 * 纯展示（没有任何修改操作）；模块节点显示版本印章与状态徽标。
 */
import { ref, computed } from 'vue'
import { resources } from '../api/resources.js'
import { useAsync } from '../composables/useAsync.js'
import TreeNode from '../components/TreeNode.vue'
import AsyncState from '../components/AsyncState.vue'
import PageHeader from '../components/PageHeader.vue'
import EmptyState from '../components/EmptyState.vue'
import { useAutoRefresh } from '../composables/useAutoRefresh.js'
import { TREE_FILTERS, filterTree, progressOf } from '../treeFilter.js'

const statusFilter = ref('')

// 网页只看得到一个项目：直接从大业务开始；只有看得到多个项目时（全局的 key）才保留「项目」这一层
const nodes = computed(() => {
  const filtered = filterTree(tree.value, statusFilter.value)
  return filtered.length === 1 && tree.value.length === 1 ? filtered[0].children || [] : filtered
})

function toNode(p) {
  return {
    kind: 'project',
    id: p.id,
    name: p.name,
    children: (p.businesses || []).map((d) => ({
      kind: 'business',
      id: d.id,
      name: d.name,
      children: (d.capabilities || []).map((doc) => {
        const children = (doc.blocks || []).map((b) => ({
          kind: 'block',
          id: b.id,
          name: b.title,
          status: b.status,
          version: b.current_published_version,
          execution_status: b.execution_status,
        }))
        return {
          kind: 'capability',
          id: doc.id,
          name: doc.title,
          version: doc.current_version,
          progress: progressOf(children),
          children,
        }
      }),
    })),
  }
}

const {
  data: treeData,
  loading,
  error: pageError,
  reload: load,
} = useAsync(async () => (await resources.tree()).map(toNode))
useAutoRefresh(load)
const tree = computed(() => treeData.value || [])
const hasModules = computed(() => {
  let n = 0
  const walk = (x) => (x.kind === 'block' ? (n += 1) : (x.children || []).forEach(walk))
  tree.value.forEach(walk)
  return n > 0
})

</script>

<template>
  <div class="page tree-page">
    <PageHeader title="文档树" />

    <div class="chips" role="tablist" aria-label="按执行状态筛选">
      <button
        v-for="[v, text] in TREE_FILTERS"
        :key="v"
        type="button"
        class="chip"
        :class="{ on: statusFilter === v }"
        role="tab"
        :aria-selected="statusFilter === v"
        @click="statusFilter = v"
      >
        {{ text }}
      </button>
    </div>

    <AsyncState
      :loading="loading"
      :error="pageError"
      :empty="!tree.length"
      loading-text="正在加载文档树…"
      empty-title="还没有内容"
      @retry="load"
    >
      <ul class="tree">
        <TreeNode v-for="n in nodes" :key="`${n.kind}-${n.id}`" :node="n" />
      </ul>
      <EmptyState v-if="!hasModules" title="还没有模块" />
      <EmptyState v-else-if="statusFilter && !nodes.length" title="没有符合筛选的模块" />
    </AsyncState>
  </div>
</template>

<style scoped>
.tree {
  margin-top: var(--sp-4);
}
</style>

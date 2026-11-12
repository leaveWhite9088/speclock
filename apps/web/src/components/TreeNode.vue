<script setup>
/**
 * TreeNode —— 文档树递归节点（项目 → 大业务 → 小业务 → 模块），纯展示：只展开 / 收起，
 * 没有任何新建 / 重命名 / 删除操作（写入由 Agent 经审核单 + Commit 完成）。
 */
import { ref, computed } from 'vue'
import VersionChip from './VersionChip.vue'
import ExecStatusBadge from './ExecStatusBadge.vue'
import SurfaceStatus from './SurfaceStatus.vue'
import BlockStatusBadge from './BlockStatusBadge.vue'

const props = defineProps({
  node: { type: Object, required: true },
})

const collapsed = ref(false)
const isBlock = computed(() => props.node.kind === 'block')
const hasKids = computed(() => !!(props.node.children && props.node.children.length))

const link = computed(() => {
  const n = props.node
  if (n.kind === 'capability') return `/capabilities/${n.id}`
  if (n.kind === 'block') return `/blocks/${n.id}`
  return ''
})
</script>

<template>
  <li class="tnode" :class="`k-${node.kind}`">
    <div class="trow">
      <button
        v-if="hasKids"
        type="button"
        class="caret"
        :aria-label="collapsed ? '展开' : '收起'"
        @click="collapsed = !collapsed"
      >
        {{ collapsed ? '▸' : '▾' }}
      </button>
      <span v-else class="caret-sp"></span>

      <RouterLink v-if="link" class="tname" :to="link">{{ node.name }}</RouterLink>
      <button v-else type="button" class="tname tname-btn" @click="collapsed = !collapsed">
        {{ node.name }}
      </button>

      <span class="tmeta">
        <template v-if="node.kind === 'capability'">
          <VersionChip v-if="node.version" :version="node.version" />
          <span
            v-if="node.progress && node.progress.total"
            class="progress"
            :class="{ done: node.progress.verified === node.progress.total }"
          >
            {{ node.progress.verified }}/{{ node.progress.total }}
          </span>
        </template>
        <template v-if="isBlock">
          <span class="bid mono">#{{ node.id }}</span>
          <VersionChip
            v-if="node.version"
            :version="node.version"
            :status="node.status === 'archived' ? 'draft' : 'published'"
          />
          <BlockStatusBadge v-if="node.status !== 'published'" :status="node.status" />
          <ExecStatusBadge :status="node.execution_status" />
          <SurfaceStatus :works="node.works || []" />
        </template>
      </span>
    </div>

    <ul v-if="!collapsed && hasKids" class="tkids">
      <TreeNode v-for="c in node.children" :key="`${c.kind}-${c.id}`" :node="c" />
    </ul>
  </li>
</template>

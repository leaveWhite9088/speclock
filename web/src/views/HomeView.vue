<script setup>
/**
 * HomeView（/）—— 文档树导航页：项目 → 大业务 → 小业务 → 模块 四级可展开树，
 * 纯展示（没有任何修改操作）；模块节点显示版本印章与状态徽标。
 */
import { ref, computed, watch } from 'vue'
import { resources } from '../api/resources.js'
import { useAsync } from '../composables/useAsync.js'
import TreeNode from '../components/TreeNode.vue'
import AsyncState from '../components/AsyncState.vue'
import { useAutoRefresh } from '../composables/useAutoRefresh.js'

const PROJECT_KEY = 'speclock_project'


const selectedProjectId = ref(Number(localStorage.getItem(PROJECT_KEY)) || null)
const onlyPending = ref(false)

function filterPending(node) {
  if (node.kind === 'block') {
    return node.status !== 'archived' && node.version && node.execution_status !== 'verified' ? node : null
  }
  const children = (node.children || []).map(filterPending).filter(Boolean)
  return children.length ? { ...node, children } : null
}

const visibleTree = computed(() => {
  let t = tree.value
  if (selectedProjectId.value) t = t.filter((n) => n.id === selectedProjectId.value)
  if (onlyPending.value) t = t.map(filterPending).filter(Boolean)
  return t
})

function pickProject(id) {
  selectedProjectId.value = id
  localStorage.setItem(PROJECT_KEY, String(id))
}

function toNode(p) {
  return {
    kind: 'project',
    id: p.id,
    name: p.name,
    children: (p.businesses || []).map((d) => ({
      kind: 'business',
      id: d.id,
      name: d.name,
      children: (d.capabilities || []).map((doc) => ({
        kind: 'capability',
        id: doc.id,
        name: doc.title,
        version: doc.current_version,
        children: (doc.blocks || []).map((b) => ({
          kind: 'block',
          id: b.id,
          name: b.title,
          status: b.status,
          version: b.current_published_version,
          execution_status: b.execution_status,
        })),
      })),
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

// 选中项目已不存在（被删 / 首次进入）时回落到第一个项目
watch(tree, (t) => {
  if (t.length && !t.some((n) => n.id === selectedProjectId.value)) pickProject(t[0].id)
})
</script>

<template>
  <div class="page tree-page">
    <p class="page-eyebrow">SpecLock · Registry</p>
    <div class="tree-head">
      <h1 class="page-title">文档树</h1>
      <div class="tree-head-ops">
        <label class="pending-filter">
          <input type="checkbox" v-model="onlyPending" />
          只看未验收
        </label>
        <select
          v-if="tree.length"
          class="input project-picker"
          :value="selectedProjectId"
          @change="pickProject(Number($event.target.value))"
          aria-label="选择项目"
        >
          <option v-for="p in tree" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>
    </div>
    <p class="page-desc">
      项目是文档隔离单元：每个项目有自己独立的一套 大业务 → 小业务 → 模块。这里只做展示，
      所有修改都由 Agent 经「审核单」完成。
    </p>

    <AsyncState
      :loading="loading"
      :error="pageError"
      :empty="!tree.length"
      loading-text="正在加载文档树…"
      empty-title="还没有内容"
      empty-text="文档树是空的。让 Agent 创建审核单、你确认后，由它提交 Commit 来建立 大业务 → 小业务 → 模块。"
      @retry="load"
    >
      <div class="tree">
        <ul class="tree-root">
          <TreeNode v-for="n in visibleTree" :key="`project-${n.id}`" :node="n" />
        </ul>
      </div>
    </AsyncState>
  </div>
</template>

<style scoped>
.tree-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
}

.tree-head-ops {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.pending-filter {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--text-sm);
  color: var(--ink-2);
  cursor: pointer;
  white-space: nowrap;
}

.project-picker {
  width: auto;
  min-width: 160px;
  font-weight: 500;
}

.page-err {
  margin-top: var(--sp-3);
}

.loading {
  margin-top: var(--sp-6);
}

.tree {
  margin-top: var(--sp-5);
}

.tree-root {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.trow-new {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 4px var(--sp-2);
}

.trow-new .input {
  max-width: 260px;
  padding: 4px var(--sp-2);
}

.empty {
  margin-top: var(--sp-5);
  padding: var(--sp-6);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
  border-style: dashed;
}

.empty-title {
  font-size: var(--text-lg);
  font-weight: 600;
}

.composer {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
}

.composer .input {
  max-width: 260px;
}
</style>

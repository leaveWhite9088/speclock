<script setup>
/**
 * AppBreadcrumb —— 全局面包屑 + 返回上一页。
 * 从 GET /tree 推导完整路径：项目 › 大业务 › 文档 › 模块（› 附加页）。
 * 项目/大业务没有独立页面，点击跳到文档树并选中该项目；文档进文档页；
 * 当前级展示为纯文本。append 用于编辑/版本对比这类模块的子页面。
 */
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client.js'

const props = defineProps({
  blockId: { type: Number, default: null },
  documentId: { type: Number, default: null },
  append: { type: String, default: '' },
})

const router = useRouter()
const items = ref([])

onMounted(async () => {
  try {
    const tree = await api.get('/tree')
    items.value = findTrail(tree) || []
  } catch {
    items.value = []
  }
})

function findTrail(tree) {
  const wantDoc = Number(props.documentId)
  const wantBlock = Number(props.blockId)
  for (const p of tree) {
    for (const d of p.domains || []) {
      for (const doc of d.documents || []) {
        const head = [
          { label: p.name, projectId: p.id },
          { label: d.name, projectId: p.id },
        ]
        if (wantDoc && doc.id === wantDoc) {
          const trail = [...head, { label: doc.title, to: null }]
          if (props.append) {
            trail[trail.length - 1].to = `/documents/${doc.id}`
            trail.push({ label: props.append, to: null })
          }
          return trail
        }
        if (wantBlock) {
          const b = (doc.blocks || []).find((x) => x.id === wantBlock)
          if (b) {
            const trail = [
              ...head,
              { label: doc.title, to: `/documents/${doc.id}` },
              { label: b.title, to: props.append ? `/blocks/${b.id}` : null },
            ]
            if (props.append) trail.push({ label: props.append, to: null })
            return trail
          }
        }
      }
    }
  }
  return null
}

function goProject(projectId) {
  localStorage.setItem('speclock_project', String(projectId))
  router.push('/')
}

function onClick(item) {
  if (item.to) router.push(item.to)
  else if (item.projectId) goProject(item.projectId)
}

function goBack() {
  if (window.history.state && window.history.state.back) {
    router.back()
    return
  }
  // 直接打开页面（无历史）时，回到上一级
  const parent = items.value[items.value.length - 2]
  if (!parent) router.push('/')
  else onClick(parent)
}
</script>

<template>
  <div class="crumbs-bar">
    <button type="button" class="btn btn-mini back-btn" @click="goBack">← 返回</button>
    <nav class="crumbs" aria-label="面包屑">
      <template v-for="(item, i) in items" :key="i">
        <span v-if="i" class="sep" aria-hidden="true">›</span>
        <span v-if="i === items.length - 1" class="crumb-current" aria-current="page">
          {{ item.label }}
        </span>
        <a v-else class="crumb-link" href="#" @click.prevent="onClick(item)">
          {{ item.label }}
        </a>
      </template>
    </nav>
  </div>
</template>

<style scoped>
.crumbs-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
}

.back-btn {
  flex: none;
}

.crumbs {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
  font-size: var(--text-sm);
  min-width: 0;
}

.sep {
  color: var(--ink-2);
}

.crumb-link {
  color: var(--ink-2);
  transition: color var(--dur) var(--ease);
}

.crumb-link:hover {
  color: var(--contract);
}

.crumb-current {
  color: var(--ink);
  font-weight: 500;
}
</style>

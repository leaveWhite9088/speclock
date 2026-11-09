<script setup>
/**
 * AppBreadcrumb —— 全局面包屑 + 返回上一页。
 * 从 GET /tree 推导完整路径：项目 › 大业务 › 小业务 › 模块（› 附加页）。
 * 项目/大业务没有独立页面，点击跳到文档树并选中该项目；小业务进小业务页；
 * 当前级展示为纯文本。append 用于编辑/版本对比这类模块的子页面。
 */
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { resources } from '../api/resources.js'

const props = defineProps({
  blockId: { type: Number, default: null },
  capabilityId: { type: Number, default: null },
  append: { type: String, default: '' },
})

const router = useRouter()
const items = ref([])

onMounted(async () => {
  try {
    const tree = await resources.tree()
    items.value = findTrail(tree) || []
  } catch {
    items.value = []
  }
})

function findTrail(tree) {
  const wantDoc = Number(props.capabilityId)
  const wantBlock = Number(props.blockId)
  for (const p of tree) {
    for (const d of p.businesses || []) {
      for (const doc of d.capabilities || []) {
        const head = [
          { label: p.name, projectId: p.id },
          { label: d.name, projectId: p.id },
        ]
        if (wantDoc && doc.id === wantDoc) {
          const trail = [...head, { label: doc.title, to: null }]
          if (props.append) {
            trail[trail.length - 1].to = `/capabilities/${doc.id}`
            trail.push({ label: props.append, to: null })
          }
          return trail
        }
        if (wantBlock) {
          const b = (doc.blocks || []).find((x) => x.id === wantBlock)
          if (b) {
            const trail = [
              ...head,
              { label: doc.title, to: `/capabilities/${doc.id}` },
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
  router.push('/tree')
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
  if (!parent) router.push('/tree')
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
/* .crumbs-bar / .back-btn / .crumbs / .sep / .crumb-link / .crumb-current
   均为全局（styles/base.css） */
</style>

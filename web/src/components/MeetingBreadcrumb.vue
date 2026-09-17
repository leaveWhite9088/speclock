<script setup>
/**
 * MeetingBreadcrumb —— 会议模块面包屑 + 返回上一页（与 AppBreadcrumb 同款
 * crumbs-bar/back-btn 机制，样式全部来自全局 base.css）：
 * 会议记录 › 业务线 › 会议 › 文件。items: [{ label, to? }]；
 * 无 to 的层级（业务线没有独立页面）渲染为纯文本，末级为当前页。
 *
 * 返回行为与文档树一致：有浏览历史则 router.back()，否则回面包屑父级
 * （无父级时回 /meetings 模块首页）。
 */
import { useRouter } from 'vue-router'

const props = defineProps({
  items: { type: Array, required: true },
})

const router = useRouter()

function goBack() {
  if (window.history.state && window.history.state.back) {
    router.back()
    return
  }
  // 直接打开页面（无历史）时，回到面包屑父级
  const parent = props.items[props.items.length - 2]
  router.push(parent?.to || '/meetings')
}
</script>

<template>
  <div class="crumbs-bar">
    <button type="button" class="btn btn-mini back-btn" @click="goBack">← 返回</button>
    <nav class="crumbs" aria-label="面包屑">
      <template v-for="(item, i) in items" :key="i">
        <span v-if="i" class="sep" aria-hidden="true">›</span>
        <RouterLink v-if="item.to" class="crumb-link" :to="item.to">{{ item.label }}</RouterLink>
        <span v-else :class="i === items.length - 1 ? 'crumb-current' : 'crumb-plain'">
          {{ item.label }}
        </span>
      </template>
    </nav>
  </div>
</template>

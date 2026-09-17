<script setup>
/**
 * MeetingBreadcrumb —— 会议模块面包屑：会议记录 › 业务线 › 会议 › 文件。
 * items: [{ label, to? }]；无 to 的层级（业务线没有独立页面）渲染为纯文本，
 * 末级为当前页。样式用全局 crumbs 体系（styles/base.css，与 AppBreadcrumb 同源）。
 */
defineProps({
  items: { type: Array, required: true },
})
</script>

<template>
  <nav class="crumbs mcrumbs" aria-label="面包屑">
    <template v-for="(item, i) in items" :key="i">
      <span v-if="i" class="sep" aria-hidden="true">›</span>
      <RouterLink v-if="item.to" class="crumb-link" :to="item.to">{{ item.label }}</RouterLink>
      <span v-else :class="i === items.length - 1 ? 'crumb-current' : 'crumb-plain'">
        {{ item.label }}
      </span>
    </template>
  </nav>
</template>

<style scoped>
.mcrumbs {
  margin-bottom: var(--sp-2);
}
</style>

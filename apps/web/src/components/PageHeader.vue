<script setup>
// 页面头部：标题 + 右侧操作（筛选等）；下方可放一行摘要。不放说明文字——界面本身要说清楚。
defineProps({
  title: { type: String, required: true },
})
</script>

<template>
  <header class="page-header">
    <div class="head-row">
      <h1 class="page-title"><slot name="title">{{ title }}</slot></h1>
      <div v-if="$slots.actions" class="head-actions"><slot name="actions" /></div>
    </div>
    <slot />
  </header>
</template>

<style scoped>
.head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
</style>

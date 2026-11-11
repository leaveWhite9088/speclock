<script setup>
// 页面头部：英文小标题 + 标题 + 说明；右侧 / 下方可放操作（筛选等）。
defineProps({
  eyebrow: { type: String, default: '' },
  title: { type: String, required: true },
  desc: { type: String, default: '' },
})
</script>

<template>
  <header class="page-header">
    <p v-if="eyebrow" class="page-eyebrow">{{ eyebrow }}</p>
    <div class="head-row">
      <h1 class="page-title"><slot name="title">{{ title }}</slot></h1>
      <div v-if="$slots.actions" class="head-actions"><slot name="actions" /></div>
    </div>
    <p v-if="desc" class="page-desc">{{ desc }}</p>
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

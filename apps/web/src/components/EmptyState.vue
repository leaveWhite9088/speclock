<script setup>
// 统一的「空」状态：告诉用户这里的内容是怎么来的，而不是一片空白。
defineProps({
  title: { type: String, default: '' },
  text: { type: String, default: '' },
})
</script>

<template>
  <div class="empty-state">
    <p v-if="title" class="empty-title">{{ title }}</p>
    <p v-if="text" class="muted">{{ text }}</p>
    <slot />
  </div>
</template>

<style scoped>
.empty-state {
  margin-top: var(--sp-5);
  padding: var(--sp-6) 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-2);
  border-top: 1px solid var(--hairline);
}

.empty-title {
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: 600;
}
</style>

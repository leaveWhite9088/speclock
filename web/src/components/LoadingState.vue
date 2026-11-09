<script setup>
// 统一的「加载中」占位。
defineProps({ text: { type: String, default: '加载中…' } })
</script>

<template>
  <p class="loading-state muted" role="status" aria-live="polite">{{ text }}</p>
</template>

<style scoped>
.loading-state {
  padding: var(--sp-5) 0;
  font-size: var(--text-sm);
}
</style>

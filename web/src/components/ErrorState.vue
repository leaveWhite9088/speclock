<script setup>
// 统一的「出错」展示：说明原因，可以重试。
defineProps({
  message: { type: String, required: true },
  retryable: { type: Boolean, default: true },
})
defineEmits(['retry'])
</script>

<template>
  <div class="card error-state" role="alert">
    <p class="error-text msg">{{ message }}</p>
    <button v-if="retryable" type="button" class="btn" @click="$emit('retry')">重试</button>
  </div>
</template>

<style scoped>
.error-state {
  margin-top: var(--sp-4);
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.msg {
  white-space: pre-line;
}
</style>

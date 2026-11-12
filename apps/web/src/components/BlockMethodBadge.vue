<script setup>
/**
 * BlockMethodBadge —— 从 "GET /api/x" 形式的 API 名解析 HTTP 方法并着色。
 */
import { computed } from 'vue'

const props = defineProps({
  api: { type: String, default: '' },
})

const method = computed(
  () => (props.api || '').trim().split(/\s+/)[0]?.toUpperCase() || '',
)
</script>

<template>
  <span class="mbadge mono" :class="`m-${method.toLowerCase()}`">{{
    method || '?'
  }}</span>
</template>

<style scoped>
.mbadge {
  display: inline-block;
  min-width: 46px;
  text-align: center;
  padding: 0 var(--sp-2);
  border-radius: 999px;
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  user-select: none;
  background: var(--side);
}

.m-get {
  color: var(--contract);
  background: var(--contract-wash);
}

.m-post {
  color: var(--success);
  background: var(--success-wash);
}

.m-put,
.m-patch {
  color: var(--warning);
  background: var(--warning-wash);
}

.m-delete {
  color: var(--danger);
  background: var(--danger-wash);
}
</style>

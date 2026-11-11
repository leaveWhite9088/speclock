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
  padding: 1px 6px;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  border: 1px solid currentColor;
  user-select: none;
}

.m-get {
  color: var(--contract);
  background: var(--contract-wash);
}

.m-post {
  color: var(--success);
}

.m-put,
.m-patch {
  color: var(--warning);
}

.m-delete {
  color: var(--danger);
}
</style>

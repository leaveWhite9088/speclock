<script setup>
/**
 * BlockStatusBadge —— 模块状态徽标：草稿 / 已发布 / 已归档。
 */
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, required: true },
})

const TEXT = { draft: '草稿', published: '已发布', archived: '已归档' }
const text = computed(() => TEXT[props.status] || props.status)
</script>

<template>
  <span class="stbadge" :class="`st-${status}`">{{ text }}</span>
</template>

<style scoped>
.stbadge {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  line-height: 1.6;
  white-space: nowrap;
  user-select: none;
}

.st-draft {
  color: var(--ink-2);
  border: 1px dashed var(--ink-2);
}

.st-published {
  color: var(--contract);
  background: var(--contract-wash);
  border: 1px solid var(--contract);
}

.st-archived {
  color: var(--ink-2);
  background: var(--paper);
  border: 1px solid var(--hairline);
}
</style>

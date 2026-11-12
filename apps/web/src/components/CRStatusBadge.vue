<script setup>
// 审核单状态徽标。
import { CR_STATUS, label } from '../labels.js'

defineProps({ status: { type: String, required: true } })
</script>

<template>
  <span class="cr-badge" :class="`is-${status}`">{{ label(CR_STATUS, status) }}</span>
</template>

<style scoped>
.cr-badge {
  display: inline-block;
  padding: 0 var(--sp-2);
  border-radius: 999px;
  font-size: var(--text-xs);
  line-height: 1.6;
  white-space: nowrap;
  background: var(--side);
  color: var(--ink-2);
}

.is-pending_review {
  background: var(--warning-wash);
  color: var(--warning);
}

.is-approved {
  background: var(--contract-wash);
  color: var(--contract);
}

.is-applied {
  background: var(--success-wash);
  color: var(--success);
}

.is-rejected {
  background: var(--danger-wash);
  color: var(--danger);
}

.is-superseded {
  opacity: 0.7;
}
</style>

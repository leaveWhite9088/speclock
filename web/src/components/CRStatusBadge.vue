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
  padding: 1px 8px;
  border-radius: 999px;
  font-size: var(--text-xs, 12px);
  font-weight: 500;
  white-space: nowrap;
  background: var(--paper);
  color: var(--ink-2);
  border: 1px solid var(--hairline);
}

.is-pending_review {
  background: #fff6e0;
  color: #8a5a00;
  border-color: #f0d9a0;
}

.is-approved {
  background: var(--contract-wash);
  color: var(--contract);
  border-color: transparent;
}

.is-applied {
  background: #e6f5ea;
  color: #1d6b34;
  border-color: transparent;
}

.is-rejected {
  background: #fdeaea;
  color: #a02828;
  border-color: transparent;
}

.is-superseded {
  opacity: 0.7;
}
</style>

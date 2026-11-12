<script setup>
// 执行状态徽标（与后端 executions.py 的状态一一对应）。
import { EXEC_STATUS, label } from '../labels.js'

defineProps({ status: { type: String, default: '' } })
</script>

<template>
  <span v-if="status" class="exec-badge" :class="`is-${status}`">{{ label(EXEC_STATUS, status) }}</span>
</template>

<style scoped>
.exec-badge {
  display: inline-block;
  font-size: var(--text-xs);
  line-height: 1.6;
  padding: 0 var(--sp-2);
  border-radius: 999px;
  color: var(--ink-2);
  background: var(--side);
  white-space: nowrap;
}

.is-in_progress {
  color: var(--contract);
  background: var(--contract-wash);
}

.is-implemented {
  color: var(--warning);
  background: var(--warning-wash);
}

/* 被阻塞：在等人答复，黄色；失败：红色 */
.is-blocked {
  color: var(--warning);
  background: var(--warning-wash);
}

.is-failed {
  color: var(--danger);
  background: var(--danger-wash);
}

.is-verified {
  color: var(--success);
  background: var(--success-wash);
}

.is-superseded {
  opacity: 0.7;
}
</style>

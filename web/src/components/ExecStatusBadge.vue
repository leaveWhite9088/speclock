<script setup>
// 执行状态徽标（与后端 executions.py 的状态一一对应）。
defineProps({ status: { type: String, default: '' } })

const TEXT = {
  pending: '待领取',
  in_progress: '进行中',
  blocked: '被阻塞',
  failed: '失败',
  implemented: '待验收',
  verified: '已验收',
  superseded: '已被取代',
}
</script>

<template>
  <span v-if="status" class="exec-badge" :class="`is-${status}`">{{ TEXT[status] || status }}</span>
</template>

<style scoped>
.exec-badge {
  display: inline-block;
  font-size: var(--text-xs);
  line-height: 1.5;
  padding: 0 var(--sp-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--hairline);
  color: var(--ink-2);
  background: var(--paper);
  white-space: nowrap;
}

.is-in_progress {
  border-color: var(--contract);
  color: var(--contract);
  background: var(--contract-wash);
}

.is-implemented {
  border-color: var(--warning);
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 7%, var(--card));
}

.is-blocked,
.is-failed {
  border-color: var(--danger);
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 7%, var(--card));
}

.is-verified {
  border-color: #1f8a4c;
  color: #1f8a4c;
  background: #e6f5ea;
}

.is-superseded {
  opacity: 0.7;
}
</style>

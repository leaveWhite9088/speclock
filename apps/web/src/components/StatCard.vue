<script setup>
// 数字概览里的一格：一个大数字 + 名称；可选的进度条。不带边框——几格并排，中间只有细线。
defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], required: true },
  sub: { type: String, default: '' },
  percent: { type: Number, default: null },
  to: { type: String, default: '' },
})
</script>

<template>
  <component :is="to ? 'RouterLink' : 'div'" :to="to || undefined" class="stat" :title="sub || undefined">
    <span class="stat-value">{{ value }}</span>
    <span class="stat-label">{{ label }}</span>
    <span v-if="percent !== null" class="stat-bar" role="presentation">
      <span class="stat-fill" :style="{ width: `${Math.min(100, Math.max(0, percent))}%` }"></span>
    </span>
  </component>
</template>

<style scoped>
.stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sp-2) var(--sp-4);
  color: var(--ink);
}

a.stat:hover .stat-label {
  color: var(--contract);
}

.stat-value {
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: 600;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.stat-label {
  font-size: var(--text-sm);
  color: var(--ink-2);
}

.stat-bar {
  display: block;
  height: 3px;
  margin-top: var(--sp-1);
  background: var(--hairline);
  border-radius: 2px;
  overflow: hidden;
}

.stat-fill {
  display: block;
  height: 100%;
  background: var(--clay);
}
</style>

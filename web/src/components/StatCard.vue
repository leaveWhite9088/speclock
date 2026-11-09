<script setup>
// 数字概览里的一张小卡片：一个大数字 + 说明；可选的进度条。
defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], required: true },
  sub: { type: String, default: '' },
  percent: { type: Number, default: null },
  to: { type: String, default: '' },
})
</script>

<template>
  <component :is="to ? 'RouterLink' : 'div'" :to="to || undefined" class="card stat">
    <span class="stat-label muted">{{ label }}</span>
    <span class="stat-value mono">{{ value }}</span>
    <span v-if="sub" class="stat-sub muted">{{ sub }}</span>
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
  padding: var(--sp-3) var(--sp-4);
  color: var(--ink);
}

a.stat:hover {
  border-color: var(--ink-2);
}

.stat-label,
.stat-sub {
  font-size: var(--text-xs);
}

.stat-value {
  font-size: var(--text-xl);
  font-weight: 600;
  line-height: 1.3;
}

.stat-bar {
  display: block;
  height: 4px;
  margin-top: var(--sp-1);
  background: var(--paper);
  border-radius: 2px;
  overflow: hidden;
}

.stat-fill {
  display: block;
  height: 100%;
  background: var(--success);
}
</style>

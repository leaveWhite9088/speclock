<script setup>
// 一个模块版本各个端（前端 / 后端 / 数据…）各自的执行状态。只有一个端（没声明端的模块）时什么都不显示——
// 那时模块上的执行状态徽标就是全部信息。
import ExecStatusBadge from './ExecStatusBadge.vue'

defineProps({ works: { type: Array, default: () => [] } })
</script>

<template>
  <span v-if="works.length > 1" class="surface-status">
    <span v-for="w in works" :key="w.work_id" class="surface-item">
      <span class="surface-name">{{ w.surface || '默认' }}</span>
      <ExecStatusBadge :status="w.status" />
    </span>
  </span>
</template>

<style scoped>
.surface-status {
  display: inline-flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  align-items: center;
}

.surface-item {
  display: inline-flex;
  gap: var(--sp-1);
  align-items: center;
}

.surface-name {
  font-size: var(--text-xs);
  color: var(--ink-2);
}
</style>

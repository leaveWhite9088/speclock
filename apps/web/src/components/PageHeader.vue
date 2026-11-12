<script setup>
// 页面头部：标题 + 右侧操作（筛选等）；下方可放一行摘要。不放说明文字——界面本身要说清楚。
import { useRouter } from 'vue-router'

defineProps({
  title: { type: String, required: true },
})

const router = useRouter()
// 只有真的有上一页（站内跳转过来）才显示返回
function canBack() {
  return !!window.history.state?.back
}
</script>

<template>
  <header class="page-header">
    <div class="head-row">
      <button v-if="canBack()" type="button" class="back-btn" aria-label="返回上一页" title="返回上一页" @click="router.back()">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg>
      </button>
      <h1 class="page-title"><slot name="title">{{ title }}</slot></h1>
      <div v-if="$slots.actions" class="head-actions"><slot name="actions" /></div>
    </div>
    <slot />
  </header>
</template>

<style scoped>
.head-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.back-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  margin-right: calc(var(--sp-2) * -1);
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--ink-2);
  cursor: pointer;
}

.back-btn:hover {
  background: var(--hover);
  color: var(--ink);
}

.page-title {
  flex: 1 1 auto;
  min-width: 0;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
</style>

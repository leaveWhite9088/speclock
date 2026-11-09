<script setup>
/**
 * 总览首页的一块：标题 + 数量 + 列表（插槽）+ 「查看全部」。
 * tone：alert（需要你行动，最醒目）/ watch（事后过目）/ normal。
 * 没有内容时显示「一切正常」类的说明，而不是消失，这样人知道这块是检查过的。
 */
import LoadingState from './LoadingState.vue'

defineProps({
  title: { type: String, required: true },
  hint: { type: String, default: '' },
  count: { type: Number, default: 0 },
  tone: { type: String, default: 'normal' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  emptyText: { type: String, default: '一切正常' },
  to: { type: String, default: '' },
  toLabel: { type: String, default: '查看全部' },
})
</script>

<template>
  <section class="card att" :class="[`tone-${tone}`, { 'has-items': count > 0 }]">
    <header class="att-head">
      <h2 class="att-title">{{ title }}</h2>
      <span class="att-count" :class="{ zero: !count }">{{ count }}</span>
      <RouterLink v-if="to && count" :to="to" class="att-all">{{ toLabel }} →</RouterLink>
    </header>
    <p v-if="hint" class="att-hint muted">{{ hint }}</p>

    <LoadingState v-if="loading" />
    <p v-else-if="error" class="error-text att-error">{{ error }}</p>
    <p v-else-if="!count" class="att-empty muted">{{ emptyText }}</p>
    <ul v-else class="att-list"><slot /></ul>
  </section>
</template>

<style scoped>
.att {
  padding: var(--sp-4) var(--sp-5);
}

.att-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.att-title {
  font-size: var(--text-md);
  font-weight: 600;
}

.att-count {
  min-width: 22px;
  padding: 0 var(--sp-2);
  text-align: center;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 20px;
  border-radius: 999px;
  background: var(--contract-wash);
  color: var(--contract);
}

.att-count.zero {
  background: var(--paper);
  color: var(--ink-2);
}

.att-all {
  margin-left: auto;
  font-size: var(--text-sm);
}

.att-hint {
  margin-top: var(--sp-1);
  font-size: var(--text-xs);
}

.att-empty,
.att-error {
  margin-top: var(--sp-3);
  font-size: var(--text-sm);
}

.att-list {
  margin-top: var(--sp-2);
}

/* 需要你行动：左侧色条 + 浅色底 */
.tone-alert.has-items {
  border-color: var(--warning);
  box-shadow: inset 3px 0 0 var(--warning);
  background: color-mix(in srgb, var(--warning) 4%, var(--card));
}

.tone-alert.has-items .att-count {
  background: var(--warning);
  color: #fff;
}

/* 事后过目：蓝色色条 */
.tone-watch.has-items {
  box-shadow: inset 3px 0 0 var(--contract);
}
</style>

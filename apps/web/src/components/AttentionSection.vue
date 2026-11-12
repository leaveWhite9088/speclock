<script setup>
/**
 * 总览里的一组：标题 + 数量，可以展开 / 收起；没有内容时只剩一行灰色的「标题 0」，不占地方。
 * tone="alert"（需要你行动）的数量用陶土色圆点标出来；有内容的 alert 组默认展开。
 */
import LoadingState from './LoadingState.vue'

defineProps({
  title: { type: String, required: true },
  count: { type: Number, default: 0 },
  tone: { type: String, default: 'normal' },
  open: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  to: { type: String, default: '' },
})
</script>

<template>
  <section class="att" :class="[`tone-${tone}`]">
    <LoadingState v-if="loading" />
    <p v-else-if="error" class="error-text att-error">{{ error }}</p>
    <div v-else-if="!count" class="att-none">
      <span class="att-name">{{ title }}</span>
      <span class="count">0</span>
    </div>
    <details v-else class="fold att-fold" :open="open || undefined">
      <summary>
        <span class="att-name">{{ title }}</span>
        <span class="count">{{ count }}</span>
        <RouterLink v-if="to" :to="to" class="more" @click.stop>全部</RouterLink>
      </summary>
      <ul class="list att-list"><slot /></ul>
    </details>
  </section>
</template>

<style scoped>
.att {
  margin-top: var(--sp-4);
}

.att-none {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  padding: var(--sp-2) 0 var(--sp-2) calc(6px + var(--sp-2));
  font-size: var(--text-lg);
  color: var(--ink-2);
}

.att-none .count {
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.tone-alert .att-fold .count {
  color: var(--contract);
  font-weight: 600;
}

.att-list {
  margin-top: var(--sp-1);
}

.att-error {
  margin-top: var(--sp-2);
}
</style>

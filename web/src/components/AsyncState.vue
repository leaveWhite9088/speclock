<script setup>
/**
 * 把「加载中 / 出错 / 空 / 正常内容」四种状态收在一起：
 *
 *   <AsyncState :loading="loading" :error="error" :empty="!data?.length"
 *               empty-title="还没有审核单" empty-text="…" @retry="reload">
 *     …正常内容…
 *   </AsyncState>
 *
 * 需要自定义空状态时用 #empty 插槽。
 */
import LoadingState from './LoadingState.vue'
import ErrorState from './ErrorState.vue'
import EmptyState from './EmptyState.vue'

defineProps({
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  empty: { type: Boolean, default: false },
  emptyTitle: { type: String, default: '' },
  emptyText: { type: String, default: '' },
  loadingText: { type: String, default: '加载中…' },
})
defineEmits(['retry'])
</script>

<template>
  <LoadingState v-if="loading" :text="loadingText" />
  <ErrorState v-else-if="error" :message="error" @retry="$emit('retry')" />
  <template v-else-if="empty">
    <slot name="empty">
      <EmptyState :title="emptyTitle" :text="emptyText" />
    </slot>
  </template>
  <slot v-else />
</template>

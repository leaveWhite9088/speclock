<script setup>
// 把 key 显示成人能读懂的样子：备注（角色）。查不到信息时显示 hint 本身。
import { computed } from 'vue'
import { useKeyNames } from '../api/keyNames.js'

const props = defineProps({ hint: { type: String, default: '' } })
const { keyInfo } = useKeyNames()

const info = computed(() => keyInfo(props.hint))
const name = computed(() => info.value.label || props.hint || '—')
</script>

<template>
  <span class="key-chip" :title="hint">
    <span class="key-name">{{ name }}</span>
    <span v-if="info.role && info.role !== name" class="key-role">{{ info.role }}</span>
  </span>
</template>

<style scoped>
.key-chip {
  display: inline-flex;
  align-items: baseline;
  gap: var(--sp-1);
  white-space: nowrap;
}

.key-role {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--ink-2);
}
</style>

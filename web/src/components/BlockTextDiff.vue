<script setup>
/**
 * BlockTextDiff —— unified diff 文本渲染：等宽字体，新增绿行 / 删除红行。
 */
import { computed } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
})

const lines = computed(() => {
  if (!props.text) return []
  const arr = props.text.split('\n')
  if (arr.length && arr[arr.length - 1] === '') arr.pop()
  return arr
})

function cls(line) {
  if (line.startsWith('+++') || line.startsWith('---')) return 'line-file'
  if (line.startsWith('@@')) return 'line-hunk'
  if (line.startsWith('+')) return 'line-add'
  if (line.startsWith('-')) return 'line-del'
  return ''
}
</script>

<template>
  <pre v-if="lines.length" class="diff mono"><code><span
      v-for="(l, i) in lines"
      :key="i"
      class="dl"
      :class="cls(l)"
    >{{ l || ' ' }}</span></code></pre>
  <p v-else class="muted">无差异。</p>
</template>

<style scoped>
.diff {
  margin: 0;
  padding: var(--sp-3);
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  overflow-x: auto;
  font-size: var(--text-xs);
  line-height: 1.6;
}

.dl {
  display: block;
  white-space: pre;
  padding: 0 var(--sp-2);
}

.line-add {
  color: var(--success);
  background: rgba(21, 122, 78, 0.08);
}

.line-del {
  color: var(--danger);
  background: rgba(196, 53, 28, 0.08);
}

.line-hunk {
  color: var(--contract);
}

.line-file {
  color: var(--ink-2);
}
</style>

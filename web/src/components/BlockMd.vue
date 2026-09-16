<script setup>
/**
 * BlockMd —— Markdown 渲染（marked）。编辑预览与只读快照共用同一份排版。
 */
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps({
  source: { type: String, default: '' },
})

const html = computed(() => marked.parse(props.source || ''))
</script>

<template>
  <div class="md" v-html="html"></div>
</template>

<style scoped>
.md {
  font-size: var(--text-md);
  line-height: 1.7;
}

.md :deep(h1),
.md :deep(h2),
.md :deep(h3),
.md :deep(h4) {
  margin: var(--sp-4) 0 var(--sp-2);
  font-weight: 600;
  line-height: 1.35;
}

.md :deep(h1) {
  font-size: var(--text-lg);
}

.md :deep(h2) {
  font-size: var(--text-md);
}

.md :deep(h3),
.md :deep(h4) {
  font-size: var(--text-sm);
}

.md :deep(p) {
  margin: var(--sp-2) 0;
}

.md :deep(ul),
.md :deep(ol) {
  margin: var(--sp-2) 0;
  padding-left: var(--sp-5);
}

.md :deep(ul) {
  list-style: disc;
}

.md :deep(ol) {
  list-style: decimal;
}

.md :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.92em;
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  padding: 0 4px;
}

.md :deep(pre) {
  background: var(--paper);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  padding: var(--sp-3);
  overflow-x: auto;
}

.md :deep(pre code) {
  background: none;
  border: none;
  padding: 0;
}

.md :deep(blockquote) {
  margin: var(--sp-2) 0;
  padding-left: var(--sp-3);
  border-left: 2px solid var(--hairline);
  color: var(--ink-2);
}

.md :deep(table) {
  border-collapse: collapse;
  margin: var(--sp-2) 0;
}

.md :deep(th),
.md :deep(td) {
  border: 1px solid var(--hairline);
  padding: var(--sp-1) var(--sp-2);
  font-size: var(--text-sm);
}

.md :deep(a) {
  color: var(--contract);
}
</style>

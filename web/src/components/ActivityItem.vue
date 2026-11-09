<script setup>
/**
 * 一条活动：谁 · 做了什么 · 对象（可点击）· 多久以前，下面一行小字是摘要（理由 / 原话 / 备注）。
 * 总览和活动时间线共用。
 */
import { computed } from 'vue'
import { actionLabel, activityNote, parseTarget } from '../activity.js'
import KeyChip from './KeyChip.vue'
import TimeAgo from './TimeAgo.vue'

const props = defineProps({
  item: { type: Object, required: true },
  expandable: { type: Boolean, default: false },
})

const target = computed(() => parseTarget(props.item.target))
const note = computed(() => activityNote(props.item))
const detailText = computed(() => {
  const d = props.item.detail || {}
  return Object.keys(d).length ? JSON.stringify(d, null, 2) : ''
})
</script>

<template>
  <li class="act">
    <div class="act-line">
      <KeyChip :hint="item.actor" />
      <span class="act-action">{{ actionLabel(item) }}</span>
      <RouterLink v-if="target.to" :to="target.to" class="act-target">{{ target.text }}</RouterLink>
      <span v-else class="act-target plain">{{ target.text }}</span>
      <TimeAgo class="act-time muted" :value="item.created_at" />
    </div>
    <p v-if="note" class="act-note muted">{{ note }}</p>
    <details v-if="expandable && detailText" class="act-detail">
      <summary class="muted">详细内容</summary>
      <pre class="mono">{{ detailText }}</pre>
    </details>
  </li>
</template>

<style scoped>
.act {
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--hairline);
  font-size: var(--text-sm);
}

.act:last-child {
  border-bottom: none;
}

.act-line {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.act-action {
  font-weight: 500;
}

.act-target.plain {
  color: var(--ink-2);
}

.act-time {
  margin-left: auto;
  font-size: var(--text-xs);
}

.act-note {
  margin-top: 2px;
  font-size: var(--text-xs);
  overflow-wrap: anywhere;
}
.act-detail {
  margin-top: 2px;
  font-size: var(--text-xs);
}

.act-detail summary {
  cursor: pointer;
}

.act-detail pre {
  margin: var(--sp-1) 0 0;
  padding: var(--sp-2) var(--sp-3);
  background: var(--paper);
  border-radius: var(--radius-sm);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>

<script setup>
/**
 * VersionChip —— SpecLock 的签名元素：semver 版本印章。
 *
 * 用法：
 *   <VersionChip version="1.2.0" />                    已发布（契约蓝实线）
 *   <VersionChip version="1.3.0" status="draft" />     草稿（灰虚线）
 *
 * version 传 "1.2.0" 或 "v1.2.0" 均可，展示统一补 v 前缀。
 */
import { computed } from 'vue'

const props = defineProps({
  version: { type: String, required: true },
  status: {
    type: String,
    default: 'published',
    validator: (v) => ['published', 'draft'].includes(v),
  },
})

const label = computed(() =>
  props.version.startsWith('v') ? props.version : `v${props.version}`,
)

const statusText = {
  published: '已发布',
  draft: '草稿',
}
</script>

<template>
  <span class="vchip" :class="`is-${status}`" :title="statusText[status]">
    <span class="vchip-mark" aria-hidden="true"></span>{{ label }}
  </span>
</template>

<style scoped>
/* 版本号：安静的等宽小字，已发布是强调色，草稿 / 归档是灰色虚线 */
.vchip {
  display: inline-flex;
  align-items: center;
  padding: 0 var(--sp-2);
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1.7;
  white-space: nowrap;
  user-select: none;
}

.vchip-mark {
  display: none;
}

.is-published {
  color: var(--contract);
  background: var(--contract-wash);
}

.is-draft {
  color: var(--ink-2);
  border: 1px dashed var(--hairline-2);
  background: transparent;
}
</style>

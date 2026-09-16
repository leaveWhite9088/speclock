<script setup>
/**
 * VersionChip —— SpecLock 的签名元素：semver 版本印章。
 *
 * 用法：
 *   <VersionChip version="1.2.0" />                    已发布（契约蓝实线）
 *   <VersionChip version="1.3.0" status="draft" />     草稿（灰虚线）
 *   <VersionChip version="2.0.0" status="breaking" />  破坏性变更（红实线）
 *
 * version 传 "1.2.0" 或 "v1.2.0" 均可，展示统一补 v 前缀。
 */
import { computed } from 'vue'

const props = defineProps({
  version: { type: String, required: true },
  status: {
    type: String,
    default: 'published',
    validator: (v) => ['published', 'draft', 'breaking'].includes(v),
  },
})

const label = computed(() =>
  props.version.startsWith('v') ? props.version : `v${props.version}`,
)

const statusText = {
  published: '已发布',
  draft: '草稿',
  breaking: '破坏性变更',
}
</script>

<template>
  <span class="vchip" :class="`is-${status}`" :title="statusText[status]">
    <span class="vchip-mark" aria-hidden="true"></span>{{ label }}
  </span>
</template>

<style scoped>
.vchip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 1px 7px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  font-weight: 500;
  letter-spacing: 0.02em;
  line-height: 1.6;
  white-space: nowrap;
  user-select: none;
}

.vchip-mark {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
}

.is-published {
  color: var(--contract);
  border: 1px solid var(--contract);
  background: var(--contract-wash);
}

.is-draft {
  color: var(--ink-2);
  border: 1px dashed var(--ink-2);
  background: transparent;
}

.is-draft .vchip-mark {
  background: transparent;
  border: 1px solid currentColor;
}

.is-breaking {
  color: var(--danger);
  border: 1px solid var(--danger);
  background: transparent;
}
</style>

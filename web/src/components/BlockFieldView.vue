<script setup>
/**
 * BlockFieldView —— 只读递归字段行（已发布快照渲染用）。
 */
defineProps({
  fields: { type: Array, required: true },
  depth: { type: Number, default: 0 },
})
</script>

<template>
  <template v-for="(f, i) in fields" :key="`${f.name}-${i}`">
    <tr>
      <td>
        <span class="mono fname" :style="{ paddingLeft: depth * 20 + 'px' }">
          {{ f.name
          }}<span v-if="f.children && f.children.length" class="muted"> ▾</span>
        </span>
      </td>
      <td><span class="ftype mono">{{ f.type }}</span></td>
      <td>{{ f.required ? '必填' : '可选' }}</td>
      <td class="muted">{{ f.description }}</td>
    </tr>
    <BlockFieldView
      v-if="f.children && f.children.length"
      :fields="f.children"
      :depth="depth + 1"
    />
  </template>
</template>

<style scoped>
td {
  padding: var(--sp-1) var(--sp-2) var(--sp-1) 0;
  font-size: var(--text-sm);
  vertical-align: top;
}

.ftype {
  color: var(--contract);
  font-size: var(--text-xs);
}
</style>

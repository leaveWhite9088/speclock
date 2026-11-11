<script setup>
/**
 * BlockDeltaGroups —— 结构化 delta 分组表（发布预览与 diff 页共用）。
 * groups: [{api_key, api_name, changes:[{kind, scope, path, detail, description}]}]
 * itemsDelta: 规则 / 验收条件的 delta（delta 里的 rules_* 与 acceptance_* 数组，
 *   条目形如 "R-1 销售额口径"；没有任何变更的节不渲染）
 */
import { computed } from 'vue'

const props = defineProps({
  groups: { type: Array, default: () => [] },
  itemsDelta: { type: Object, default: null },
})

const KIND_LABEL = { added: '新增', modified: '修改', removed: '删除' }
const SCOPE_LABEL = { api: 'API', request: '请求体', response: '响应体' }

const ITEM_SECTIONS = [
  { key: 'rules', title: '业务规则变更' },
  { key: 'acceptance', title: '验收条件变更' },
]
const ITEM_KINDS = [
  { kind: 'added', cls: 'added', label: '新增' },
  { kind: 'modified', cls: 'modified', label: '修改' },
  { kind: 'renamed', cls: 'modified', label: '改名' },
  { kind: 'removed', cls: 'removed', label: '删除' },
]

// "R-1 销售额口径" → { id: 'R-1', name: '销售额口径' }（老快照无 id 时整串当名称）
function splitItem(text) {
  const m = /^((?:R|AC)-\d+)\s+(.*)$/.exec(text)
  return m ? { id: m[1], name: m[2] } : { id: '', name: text }
}

const itemSections = computed(() => {
  const d = props.itemsDelta
  if (!d) return []
  return ITEM_SECTIONS.map((sec) => ({
    ...sec,
    rows: ITEM_KINDS.flatMap((k) =>
      (d[`${sec.key}_${k.kind}`] || []).map((text) => ({
        ...k,
        ...splitItem(text),
        rowKey: `${k.kind}:${text}`,
      })),
    ),
  })).filter((sec) => sec.rows.length)
})
</script>

<template>
  <div class="delta-groups">
    <template v-if="groups.length">
      <div v-for="g in groups" :key="g.api_key" class="card delta-card">
        <h4 class="delta-head">
          {{ g.api_name }} <span class="mono muted">{{ g.api_key }}</span>
        </h4>
        <table class="delta-table">
          <thead>
            <tr>
              <th>变更</th>
              <th>位置</th>
              <th>字段路径</th>
              <th>类型 / 必填</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(ch, i) in g.changes" :key="i" :class="`chg-${ch.kind}`">
              <td>
                <span class="chg-tag" :class="`chg-tag-${ch.kind}`">{{
                  KIND_LABEL[ch.kind] || ch.kind
                }}</span>
              </td>
              <td>{{ SCOPE_LABEL[ch.scope] || ch.scope }}</td>
              <td class="mono path">{{ ch.path || '（整个 API）' }}</td>
              <td class="mono">{{ ch.detail }}</td>
              <td class="muted">{{ ch.description }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
    <p v-else class="muted">API 无结构变更。</p>

    <template v-for="sec in itemSections" :key="sec.key">
      <h4 class="rules-head">{{ sec.title }}</h4>
      <table class="delta-table rules-table">
        <thead>
          <tr>
            <th>变更</th>
            <th>编号</th>
            <th>名称</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in sec.rows" :key="row.rowKey" :class="`chg-${row.cls}`">
            <td>
              <span class="chg-tag" :class="`chg-tag-${row.cls}`">{{ row.label }}</span>
            </td>
            <td class="mono">{{ row.id }}</td>
            <td>{{ row.name }}</td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>

<style scoped>
.delta-card {
  padding: var(--sp-3) var(--sp-4);
  margin-bottom: var(--sp-3);
}

.delta-head {
  font-size: var(--text-sm);
  font-weight: 600;
  margin-bottom: var(--sp-2);
}

.rules-head {
  margin: var(--sp-4) 0 var(--sp-2);
  font-size: var(--text-sm);
  font-weight: 600;
}

.delta-table {
  width: 100%;
  border-collapse: collapse;
}

.delta-table th {
  text-align: left;
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--ink-2);
  padding: 0 var(--sp-2) var(--sp-1) 0;
  border-bottom: 1px solid var(--hairline);
}

.delta-table td {
  padding: var(--sp-1) var(--sp-2) var(--sp-1) 0;
  font-size: var(--text-sm);
  vertical-align: top;
  border-bottom: 1px solid var(--hairline);
}

.path {
  font-size: var(--text-xs);
}

.chg-tag {
  display: inline-block;
  padding: 0 6px;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  border: 1px solid currentColor;
  white-space: nowrap;
}

.chg-tag-added {
  color: var(--success);
}

.chg-tag-modified {
  color: var(--warning);
}

.chg-tag-removed {
  color: var(--danger);
}

.chg-added .path,
.chg-added .mono {
  color: var(--success);
}

.chg-modified .path {
  color: var(--warning);
}

.chg-removed .path,
.chg-removed .mono {
  color: var(--danger);
}
</style>

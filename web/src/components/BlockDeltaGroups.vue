<script setup>
/**
 * BlockDeltaGroups —— 结构化 delta 分组表（发布预览与 diff 页共用）。
 * groups: [{api_key, api_name, changes:[{kind, scope, path, detail, description}]}]
 * rulesDelta: {rules_added, rules_modified, rules_removed}（无规则变更时不渲染该节）
 */
import { computed } from 'vue'

const props = defineProps({
  groups: { type: Array, default: () => [] },
  rulesDelta: { type: Object, default: null },
})

const KIND_LABEL = { added: '新增', modified: '修改', removed: '删除' }
const SCOPE_LABEL = { api: 'API', request: '请求体', response: '响应体' }

const hasRules = computed(
  () =>
    props.rulesDelta &&
    (props.rulesDelta.rules_added?.length ||
      props.rulesDelta.rules_modified?.length ||
      props.rulesDelta.rules_removed?.length),
)
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

    <template v-if="hasRules">
      <h4 class="rules-head">业务规则变更</h4>
      <table class="delta-table rules-table">
        <thead>
          <tr>
            <th>变更</th>
            <th>规则名</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="name in rulesDelta.rules_added" :key="'a' + name" class="chg-added">
            <td><span class="chg-tag chg-tag-added">新增</span></td>
            <td>{{ name }}</td>
          </tr>
          <tr
            v-for="name in rulesDelta.rules_modified"
            :key="'m' + name"
            class="chg-modified"
          >
            <td><span class="chg-tag chg-tag-modified">修改</span></td>
            <td>{{ name }}</td>
          </tr>
          <tr
            v-for="name in rulesDelta.rules_removed"
            :key="'r' + name"
            class="chg-removed"
          >
            <td><span class="chg-tag chg-tag-removed">删除</span></td>
            <td>{{ name }}</td>
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

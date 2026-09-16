<script setup>
/**
 * BlockApiDetail —— 已发布版本的单个 API 只读详情（方法章 + 端点语义 + 字段表）。
 */
import BlockMethodBadge from './BlockMethodBadge.vue'
import BlockFieldView from './BlockFieldView.vue'

defineProps({
  api: { type: Object, required: true },
})
</script>

<template>
  <div class="api-detail">
    <div class="ad-head">
      <BlockMethodBadge :api="api.api" />
      <span class="mono api-path">{{ api.api }}</span>
      <strong>{{ api.name }}</strong>
    </div>
    <p v-if="api.desc" class="muted desc">端点语义：{{ api.desc }}</p>

    <h4 class="kind-head">请求体</h4>
    <table v-if="api.request && api.request.length" class="field-table">
      <thead>
        <tr>
          <th>字段名</th>
          <th>类型</th>
          <th>必填</th>
          <th>说明</th>
        </tr>
      </thead>
      <tbody>
        <BlockFieldView :fields="api.request" :depth="0" />
      </tbody>
    </table>
    <p v-else class="muted">无请求体字段。</p>

    <h4 class="kind-head">响应体</h4>
    <table v-if="api.response && api.response.length" class="field-table">
      <thead>
        <tr>
          <th>字段名</th>
          <th>类型</th>
          <th>必填</th>
          <th>说明</th>
        </tr>
      </thead>
      <tbody>
        <BlockFieldView :fields="api.response" :depth="0" />
      </tbody>
    </table>
    <p v-else class="muted">无响应体字段。</p>
  </div>
</template>

<style scoped>
.ad-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.api-path {
  font-size: var(--text-sm);
}

.desc {
  margin-top: var(--sp-1);
  font-size: var(--text-sm);
}

.kind-head {
  margin: var(--sp-3) 0 var(--sp-2);
  font-size: var(--text-sm);
  font-weight: 600;
}

.field-table {
  width: 100%;
  border-collapse: collapse;
}

.field-table th {
  text-align: left;
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--ink-2);
  padding: 0 var(--sp-3) var(--sp-1) 0;
  border-bottom: 1px solid var(--hairline);
}

.field-table th:nth-child(2),
.field-table th:nth-child(3) {
  width: 1%;
  white-space: nowrap;
}
</style>

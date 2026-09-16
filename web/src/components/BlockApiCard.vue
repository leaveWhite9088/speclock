<script setup>
/**
 * BlockApiCard —— 草稿编辑器里的单个 API 卡片。
 * 收起态只读摘要行（防误触），展开态可编辑名称 / API 名 / desc / 请求响应字段。
 */
import { ref, computed } from 'vue'
import BlockMethodBadge from './BlockMethodBadge.vue'
import BlockFieldRows from './BlockFieldRows.vue'

const props = defineProps({
  api: { type: Object, required: true },
  index: { type: Number, required: true },
})
const emit = defineEmits(['remove'])

const collapsed = ref(false)

function countFields(fields) {
  return (fields || []).reduce((n, f) => n + 1 + countFields(f.children), 0)
}

const stats = computed(
  () =>
    `请求 ${countFields(props.api.request)} 字段 / 响应 ${countFields(props.api.response)} 字段`,
)

function addRow(kind) {
  props.api[kind].push({
    name: '',
    type: 'string',
    required: false,
    description: '',
    children: [],
  })
}
</script>

<template>
  <div class="card api-card">
    <div class="api-head">
      <span class="idx mono">#{{ index + 1 }}</span>
      <template v-if="collapsed">
        <strong class="api-name">{{ api.name || '（未命名）' }}</strong>
        <span class="mono apikey">{{ api.api || '（未填 API 名）' }}</span>
        <BlockMethodBadge :api="api.api" />
        <span class="muted stats">{{ stats }}</span>
      </template>
      <template v-else>
        <input
          class="input api-name-input"
          v-model="api.name"
          placeholder="名称（中文显示名）"
        />
        <input
          class="input mono api-key-input"
          v-model="api.api"
          placeholder="API 名，如 GET /api/daily-report"
          spellcheck="false"
        />
        <BlockMethodBadge :api="api.api" />
      </template>
      <span class="head-ops">
        <button type="button" class="btn btn-mini" @click="collapsed = !collapsed">
          {{ collapsed ? '展开' : '收起' }}
        </button>
        <button type="button" class="btn btn-mini btn-danger" @click="emit('remove')">
          删除此 API
        </button>
      </span>
    </div>

    <div v-if="!collapsed" class="api-body">
      <label class="label desc-label" :class="{ missing: !(api.desc || '').trim() }">
        端点语义 desc <span class="star" aria-hidden="true">*</span>
        <input
          class="input"
          v-model="api.desc"
          placeholder="谁调用、为什么、副作用/幂等 —— 字段表看不出来的信息"
        />
      </label>

      <h4 class="kind-head">请求体</h4>
      <table class="field-table">
        <thead>
          <tr>
            <th>字段名</th>
            <th>类型</th>
            <th>必填</th>
            <th>说明</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <BlockFieldRows :fields="api.request" :depth="0" />
        </tbody>
      </table>
      <button type="button" class="btn btn-mini" @click="addRow('request')">
        + 加字段行
      </button>

      <h4 class="kind-head">响应体</h4>
      <table class="field-table">
        <thead>
          <tr>
            <th>字段名</th>
            <th>类型</th>
            <th>必填</th>
            <th>说明</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <BlockFieldRows :fields="api.response" :depth="0" />
        </tbody>
      </table>
      <button type="button" class="btn btn-mini" @click="addRow('response')">
        + 加字段行
      </button>
    </div>
  </div>
</template>

<style scoped>
.api-card {
  padding: var(--sp-4) var(--sp-5);
  background: var(--paper);
  border: 1px solid #d8dde6;
  border-left: 3px solid var(--contract);
  border-radius: var(--radius);
  box-shadow: 0 1px 2px rgba(28, 35, 51, 0.06);
}

.api-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.idx {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--contract);
  border: 1px solid var(--contract);
  border-radius: var(--radius-sm);
  padding: 1px var(--sp-2);
}

.api-name {
  font-size: var(--text-sm);
}

.apikey {
  font-size: var(--text-sm);
}

.stats {
  font-size: var(--text-xs);
}

.api-name-input {
  width: 180px;
}

.api-key-input {
  flex: 1;
  min-width: 220px;
}

.head-ops {
  margin-left: auto;
  display: inline-flex;
  gap: var(--sp-2);
}

.btn-mini {
  padding: 3px var(--sp-2);
  font-size: var(--text-xs);
}

.api-body {
  margin-top: var(--sp-3);
  border-top: 1px solid var(--hairline);
  padding-top: var(--sp-3);
}

.desc-label {
  font-size: var(--text-sm);
}

.star {
  color: var(--danger);
}

.missing .input {
  border-color: var(--danger);
}

.kind-head {
  margin: var(--sp-4) 0 var(--sp-2);
  font-size: var(--text-sm);
  font-weight: 600;
}

.field-table {
  width: 100%;
  border-collapse: collapse;
  margin-bottom: var(--sp-2);
}

.field-table th {
  text-align: left;
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--ink-2);
  padding: 0 var(--sp-2) var(--sp-1) 0;
  border-bottom: 1px solid var(--hairline);
}
</style>

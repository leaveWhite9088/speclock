<script setup>
// 回执看板：AI 通过 ack_block 声明「已按 模块@版本 实现」的记录流。
import { onMounted, ref } from 'vue'
import { api } from '../api/client.js'
import VersionChip from '../components/VersionChip.vue'

const loading = ref(true)
const error = ref('')
const acks = ref([])

function fmtTime(iso) {
  return iso ? String(iso).replace('T', ' ').slice(0, 19) : '-'
}

function errText(e) {
  const d = e?.detail ?? e
  return typeof d === 'string' ? d : JSON.stringify(d, null, 2)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    acks.value = await api.get('/acks')
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page acks-page">
    <p class="page-eyebrow">Acks</p>
    <h1 class="page-title">「已完成」回执看板</h1>
    <p class="page-desc">
      AI 实现完一个模块版本后调用 ack_block 留下回执。回执是单次声明，权威完成状态以模块页的「标记完成」为准。
    </p>

    <p v-if="loading" class="muted">加载中…</p>

    <div v-else-if="error" class="card state-card">
      <p class="error-text">{{ error }}</p>
      <button type="button" class="btn" @click="load">重试</button>
    </div>

    <div v-else-if="!acks.length" class="card state-card">
      <p class="muted">
        还没有回执。AI 通过 MCP 或 REST 调用 ack_block 声明「已按 模块@版本 实现」后，记录会出现在这里。
      </p>
      <RouterLink to="/mcp" class="btn">查看 AI 接入方式</RouterLink>
    </div>

    <div v-else class="card table-wrap">
      <table class="ack-table">
        <thead>
          <tr>
            <th>#</th>
            <th>模块</th>
            <th>版本</th>
            <th>Agent Key</th>
            <th>任务</th>
            <th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in acks" :key="a.id">
            <td class="mono muted">{{ a.id }}</td>
            <td>
              <RouterLink :to="`/blocks/${a.block_id}`">{{ a.block_title }}</RouterLink>
            </td>
            <td><VersionChip :version="a.version" /></td>
            <td class="mono key-cell">{{ a.agent_key }}</td>
            <td class="task-cell">{{ a.task_desc }}</td>
            <td class="muted time-cell">{{ fmtTime(a.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.acks-page {
  max-width: 960px;
}

.state-card {
  margin-top: var(--sp-5);
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

.table-wrap {
  margin-top: var(--sp-5);
  overflow-x: auto;
}

.ack-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
  min-width: 640px;
}

.ack-table th {
  text-align: left;
  font-weight: 500;
  font-size: var(--text-xs);
  color: var(--ink-2);
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--hairline);
  white-space: nowrap;
}

.ack-table td {
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--hairline);
  vertical-align: top;
}

.ack-table tbody tr:last-child td {
  border-bottom: none;
}

.key-cell {
  font-size: var(--text-xs);
  white-space: nowrap;
}

.task-cell {
  min-width: 200px;
  word-break: break-word;
}

.time-cell {
  font-size: var(--text-xs);
  white-space: nowrap;
}
</style>

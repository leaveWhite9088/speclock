<script setup>
// 密钥管理：human key 管管理端，agent key 供 AI 只读接入（可绑定项目隔离）。
// 明文仅在创建时返回一次；删除立即生效；最后一把 human key 受后端保护。
import { computed, onMounted, ref } from 'vue'
import { api, keyHint } from '../api/client.js'

const loading = ref(true)
const error = ref('')
const keys = ref([])
const projects = ref([])

// 新建表单
const newPrefix = ref('human')
const newLabel = ref('')
const newProjectId = ref('')
const creating = ref(false)
const createError = ref('')

// 创建成功的一次性明文
const created = ref(null) // { key, hint, notice }
const copied = ref(false)

// 删除确认
const pendingDelete = ref(null) // key id
const deleting = ref(false)
const rowError = ref({})

const currentHint = computed(() => keyHint())
const projectNames = computed(() => {
  const m = {}
  for (const p of projects.value) m[p.id] = p.name
  return m
})

function projectLabel(k) {
  if (!k.project_id) return '全部'
  return projectNames.value[k.project_id] || '已删除项目'
}

function fmtTime(iso) {
  return iso ? String(iso).replace('T', ' ').slice(0, 19) : '-'
}

function errText(e) {
  const d = e?.detail ?? e
  return typeof d === 'string' ? d : JSON.stringify(d, null, 2)
}

async function copyKey() {
  if (!created.value) return
  try {
    await navigator.clipboard.writeText(created.value.key)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = created.value.key
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

async function createKey() {
  creating.value = true
  createError.value = ''
  try {
    const body = { prefix: newPrefix.value, label: newLabel.value.trim() }
    if (newPrefix.value === 'agent' && newProjectId.value) {
      body.project_id = Number(newProjectId.value)
    }
    const r = await api.post('/keys', body)
    created.value = r
    newLabel.value = ''
  } catch (e) {
    createError.value = errText(e)
  } finally {
    creating.value = false
  }
}

async function dismissCreated() {
  created.value = null
  await load()
}

async function deleteKey(k) {
  deleting.value = true
  rowError.value = { ...rowError.value, [k.id]: '' }
  try {
    await api.delete(`/keys/${k.id}`)
    pendingDelete.value = null
    // 删除的是当前正在使用的 key：下一次请求会 401 并自动回登录页，这里直接刷新列表
    await load()
  } catch (e) {
    rowError.value = { ...rowError.value, [k.id]: errText(e) }
  } finally {
    deleting.value = false
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    ;[keys.value, projects.value] = await Promise.all([
      api.get('/keys'),
      api.get('/projects'),
    ])
  } catch (e) {
    error.value = errText(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page keys-page">
    <p class="page-eyebrow">API Keys</p>
    <h1 class="page-title">密钥管理</h1>
    <p class="page-desc">
      human key 用于管理端（UI / 写接口），agent key 用于 AI 只读接入。密钥仅在创建时可见一次——系统只存
      SHA-256 哈希，无法找回。删除立即生效：被删的 key 下次请求即 401。最后一把 human key 不可删除。
    </p>

    <!-- 创建成功：一次性明文 -->
    <div v-if="created" class="created-banner">
      <p class="created-title">新密钥仅此一次可见，立即复制保存：</p>
      <p class="created-key mono">{{ created.key }}</p>
      <div class="created-actions">
        <button type="button" class="btn" @click="copyKey">
          {{ copied ? '已复制 ✓' : '复制密钥' }}
        </button>
        <button type="button" class="btn" @click="dismissCreated">已保存，关闭</button>
        <span class="muted created-warn">关闭后将永远无法再次查看该 key。</span>
      </div>
    </div>

    <!-- 新建密钥 -->
    <section class="card form-card">
      <h2 class="form-title">新建密钥</h2>
      <div class="form-grid">
        <div>
          <label class="label" for="new-prefix">类型</label>
          <select id="new-prefix" v-model="newPrefix" class="input">
            <option value="human">human（管理端）</option>
            <option value="agent">agent（AI 只读）</option>
          </select>
        </div>
        <div>
          <label class="label" for="new-project">绑定项目</label>
          <select
            id="new-project"
            v-model="newProjectId"
            class="input"
            :disabled="newPrefix === 'human'"
          >
            <option value="">全部项目（不隔离）</option>
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </div>
        <div class="form-label-cell">
          <label class="label" for="new-label">标签</label>
          <input
            id="new-label"
            v-model="newLabel"
            class="input"
            type="text"
            placeholder="如：张三 / claude-code"
          />
        </div>
        <div class="form-submit">
          <button
            type="button"
            class="btn btn-primary"
            :disabled="creating"
            @click="createKey"
          >
            {{ creating ? '生成中…' : '生成密钥' }}
          </button>
        </div>
      </div>
      <p class="muted form-hint">
        项目绑定仅对 agent key 生效：绑定后该 key 只能读取所选项目的文档；human key 是管理端，始终全局。
      </p>
      <p v-if="createError" class="error-text form-error">{{ createError }}</p>
    </section>

    <!-- 现有密钥 -->
    <section class="list-section">
      <h2 class="list-title">现有密钥（{{ keys.length }} 把）</h2>

      <p v-if="loading" class="muted">加载中…</p>

      <div v-else-if="error" class="card state-card">
        <p class="error-text">{{ error }}</p>
        <button type="button" class="btn" @click="load">重试</button>
      </div>

      <div v-else class="card table-wrap">
        <table class="key-table">
          <thead>
            <tr>
              <th>类型</th>
              <th>标签</th>
              <th>项目</th>
              <th>Key</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="k in keys" :key="k.id">
              <td>
                <span class="prefix-badge" :class="`is-${k.prefix}`">{{ k.prefix }}</span>
              </td>
              <td>{{ k.label || '-' }}</td>
              <td>
                <span :class="{ muted: !k.project_id }">{{ projectLabel(k) }}</span>
              </td>
              <td class="mono key-hint-cell">
                {{ k.hint }}
                <span v-if="k.hint === currentHint" class="muted">（当前正在使用）</span>
              </td>
              <td class="muted time-cell">{{ fmtTime(k.created_at) }}</td>
              <td class="ops-cell">
                <template v-if="pendingDelete === k.id">
                  <span class="confirm-text">
                    {{ k.hint === currentHint ? '这是你当前正在使用的 key，删除后将跳回登录页。' : '删除立即生效，使用该 key 的客户端将立即 401。' }}
                  </span>
                  <button
                    type="button"
                    class="btn btn-danger"
                    :disabled="deleting"
                    @click="deleteKey(k)"
                  >
                    {{ deleting ? '删除中…' : '确认删除' }}
                  </button>
                  <button
                    type="button"
                    class="btn"
                    :disabled="deleting"
                    @click="pendingDelete = null"
                  >
                    取消
                  </button>
                </template>
                <button
                  v-else
                  type="button"
                  class="btn btn-danger"
                  @click="pendingDelete = k.id"
                >
                  删除
                </button>
                <p v-if="rowError[k.id]" class="error-text row-error">{{ rowError[k.id] }}</p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.keys-page {
  max-width: 960px;
}

.state-card {
  padding: var(--sp-5);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
}

/* ---------- 一次性明文横幅 ---------- */

.created-banner {
  margin-top: var(--sp-5);
  padding: var(--sp-4) var(--sp-5);
  border: 1px solid var(--warning);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--warning) 6%, var(--card));
}

.created-title {
  font-weight: 600;
  font-size: var(--text-sm);
}

.created-key {
  margin-top: var(--sp-2);
  font-size: var(--text-md);
  word-break: break-all;
  user-select: all;
}

.created-actions {
  margin-top: var(--sp-3);
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

.created-warn {
  font-size: var(--text-xs);
}

/* ---------- 新建表单 ---------- */

.form-card {
  margin-top: var(--sp-5);
  padding: var(--sp-4) var(--sp-5);
}

.form-title {
  font-size: var(--text-lg);
  font-weight: 600;
  margin-bottom: var(--sp-4);
}

.form-grid {
  display: grid;
  grid-template-columns: 180px 220px 1fr auto;
  gap: var(--sp-3);
  align-items: end;
}

.form-hint {
  margin-top: var(--sp-3);
  font-size: var(--text-xs);
}

.form-error {
  margin-top: var(--sp-2);
}

/* ---------- 密钥列表 ---------- */

.list-section {
  margin-top: var(--sp-6);
}

.list-title {
  font-size: var(--text-lg);
  font-weight: 600;
  margin-bottom: var(--sp-3);
}

.table-wrap {
  overflow-x: auto;
}

.key-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-sm);
  min-width: 720px;
}

.key-table th {
  text-align: left;
  font-weight: 500;
  font-size: var(--text-xs);
  color: var(--ink-2);
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--hairline);
  white-space: nowrap;
}

.key-table td {
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--hairline);
  vertical-align: top;
}

.key-table tbody tr:last-child td {
  border-bottom: none;
}

.prefix-badge {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  padding: 1px var(--sp-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--hairline);
  white-space: nowrap;
}

.prefix-badge.is-human {
  color: var(--contract);
  border-color: var(--contract);
  background: var(--contract-wash);
}

.prefix-badge.is-agent {
  color: var(--ink-2);
  background: var(--paper);
}

.key-hint-cell {
  font-size: var(--text-xs);
  white-space: nowrap;
}

.time-cell {
  font-size: var(--text-xs);
  white-space: nowrap;
}

.ops-cell {
  white-space: nowrap;
}

.confirm-text {
  display: block;
  white-space: normal;
  font-size: var(--text-xs);
  color: var(--danger);
  max-width: 220px;
  margin-bottom: var(--sp-2);
}

.row-error {
  white-space: normal;
  max-width: 260px;
  margin-top: var(--sp-2);
}

@media (max-width: 900px) {
  .form-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>

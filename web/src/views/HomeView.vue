<script setup>
/**
 * HomeView（/）—— 文档树导航页：项目 → 大业务 → 文档 → 模块 四级可展开树，
 * 每级带 新建 / 重命名 / 删除 操作；模块节点显示版本印章与状态徽标。
 */
import { ref, computed, onMounted } from 'vue'
import { api } from '../api/client.js'
import TreeNode from '../components/TreeNode.vue'

const PROJECT_KEY = 'speclock_project'

const tree = ref([])
const loading = ref(true)
const pageError = ref('')
const nodeError = ref(null)
const pending = ref(false)

const addingProject = ref(false)
const projectName = ref('')

const selectedProjectId = ref(Number(localStorage.getItem(PROJECT_KEY)) || null)

const visibleTree = computed(() => {
  if (!selectedProjectId.value) return tree.value
  return tree.value.filter((n) => n.id === selectedProjectId.value)
})

function pickProject(id) {
  selectedProjectId.value = id
  localStorage.setItem(PROJECT_KEY, String(id))
}

function toNode(p) {
  return {
    kind: 'project',
    id: p.id,
    name: p.name,
    children: (p.domains || []).map((d) => ({
      kind: 'domain',
      id: d.id,
      name: d.name,
      children: (d.documents || []).map((doc) => ({
        kind: 'document',
        id: doc.id,
        name: doc.title,
        docType: doc.doc_type,
        version: doc.current_version,
        children: (doc.blocks || []).map((b) => ({
          kind: 'block',
          id: b.id,
          name: b.title,
          status: b.status,
          version: b.current_published_version,
          completed: b.completed,
        })),
      })),
    })),
  }
}

async function load() {
  loading.value = true
  pageError.value = ''
  try {
    const raw = await api.get('/tree')
    tree.value = raw.map(toNode)
    // 选中项目已不存在（被删/首次进入）时回落到第一个项目
    if (tree.value.length && !tree.value.some((n) => n.id === selectedProjectId.value)) {
      pickProject(tree.value[0].id)
    }
  } catch (e) {
    pageError.value = fmtErr(e)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function fmtErr(e) {
  const d = e && e.detail
  if (!d) return '请求失败，请检查网络后重试。'
  if (typeof d === 'string') return d
  let text = d.error || JSON.stringify(d)
  if (Array.isArray(d.published_blocks) && d.published_blocks.length) {
    text += `（已发布模块：${d.published_blocks.map((b) => b.title).join('、')}）`
  }
  if (Array.isArray(d.missing) && d.missing.length) {
    text += `：${d.missing.join('；')}`
  }
  return text
}

const CREATE = {
  project: (p) => api.post('/projects', { name: p.name }),
  domain: (p) => api.post('/domains', { project_id: p.parentId, name: p.name }),
  document: (p) => api.post('/documents', { domain_id: p.parentId, title: p.name }),
  block: (p) => api.post('/blocks', { document_id: p.parentId, title: p.name }),
}

async function onOp(payload) {
  nodeError.value = null
  pageError.value = ''
  pending.value = true
  try {
    let res = null
    if (payload.action === 'create') res = await CREATE[payload.kind](payload)
    else if (payload.action === 'rename')
      await api.put(`/${payload.kind}s/${payload.id}`, { name: payload.name })
    else if (payload.action === 'delete')
      await api.delete(`/${payload.kind}s/${payload.id}`)
    await load()
    return res
  } catch (e) {
    // 409 守卫等错误：展示后端原文，定位到发起操作的节点下
    nodeError.value = { key: payload.errorKey, text: fmtErr(e) }
    return null
  } finally {
    pending.value = false
  }
}

async function submitProject() {
  const name = projectName.value.trim()
  if (!name) return
  addingProject.value = false
  const res = await onOp({ action: 'create', kind: 'project', name, errorKey: 'project-new' })
  if (res && res.id) pickProject(res.id)
  projectName.value = ''
}
</script>

<template>
  <div class="page tree-page">
    <p class="page-eyebrow">SpecLock · Registry</p>
    <div class="tree-head">
      <h1 class="page-title">文档树</h1>
      <div class="tree-head-ops">
        <select
          v-if="tree.length"
          class="input project-picker"
          :value="selectedProjectId"
          @change="pickProject(Number($event.target.value))"
          aria-label="选择项目"
        >
          <option v-for="p in tree" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <button
          type="button"
          class="btn btn-primary"
          @click="((addingProject = true), (projectName = ''))"
        >
          新建项目
        </button>
      </div>
    </div>
    <p class="page-desc">
      项目是文档隔离单元：每个项目有自己独立的一套 大业务 → 文档 → 模块；在「密钥管理」页把
      agent key 绑定到项目后，该 key 只能读取本项目文档。
    </p>

    <p v-if="pageError" class="error-text page-err" role="alert">{{ pageError }}</p>

    <div v-if="loading" class="muted loading">正在加载文档树…</div>

    <div v-else-if="!tree.length" class="card empty">
      <p class="empty-title">还没有项目</p>
      <p class="muted">
        项目是文档树的第一层。先建一个项目，再往里加 大业务 → 文档 → 模块。
      </p>
      <button
        type="button"
        class="btn btn-primary"
        @click="((addingProject = true), (projectName = ''))"
      >
        新建第一个项目
      </button>
      <div v-if="addingProject" class="composer">
        <input
          class="input"
          v-model="projectName"
          placeholder="项目名称"
          @keyup.enter="submitProject"
          @keyup.esc="addingProject = false"
        />
        <button
          type="button"
          class="btn btn-primary"
          :disabled="pending"
          @click="submitProject"
        >
          创建项目
        </button>
        <button type="button" class="btn" @click="addingProject = false">取消</button>
      </div>
      <p
        v-if="nodeError && nodeError.key === 'project-new'"
        class="error-text"
        role="alert"
      >
        {{ nodeError.text }}
      </p>
    </div>

    <div v-else class="tree">
      <ul class="tree-root">
        <TreeNode
          v-for="n in visibleTree"
          :key="`project-${n.id}`"
          :node="n"
          :node-error="nodeError"
          :pending="pending"
          @op="onOp"
        />
        <li v-if="addingProject" class="trow-new">
          <span class="caret-sp"></span>
          <input
            class="input"
            v-model="projectName"
            placeholder="项目名称"
            @keyup.enter="submitProject"
            @keyup.esc="addingProject = false"
          />
          <button
            type="button"
            class="btn btn-primary"
            :disabled="pending"
            @click="submitProject"
          >
            创建项目
          </button>
          <button type="button" class="btn" @click="addingProject = false">取消</button>
        </li>
      </ul>
      <p
        v-if="nodeError && nodeError.key === 'project-new'"
        class="error-text"
        role="alert"
      >
        {{ nodeError.text }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.tree-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
}

.tree-head-ops {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.project-picker {
  width: auto;
  min-width: 160px;
  font-weight: 500;
}

.page-err {
  margin-top: var(--sp-3);
}

.loading {
  margin-top: var(--sp-6);
}

.tree {
  margin-top: var(--sp-5);
}

.tree-root {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.trow-new {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 4px var(--sp-2);
}

.trow-new .input {
  max-width: 260px;
  padding: 4px var(--sp-2);
}

.empty {
  margin-top: var(--sp-5);
  padding: var(--sp-6);
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--sp-3);
  border-style: dashed;
}

.empty-title {
  font-size: var(--text-lg);
  font-weight: 600;
}

.composer {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
}

.composer .input {
  max-width: 260px;
}
</style>

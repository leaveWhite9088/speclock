<script setup>
/**
 * TreeNode —— 文档树递归节点（项目 → 大业务 → 文档 → 模块）。
 * 节点本地维护 展开/重命名/新建子级/删除确认 的 UI 状态，
 * 真正的 API 调用以 'op' 事件上抛给 HomeView 执行，失败后错误原文回显在本节点下。
 */
import { ref, computed } from 'vue'
import VersionChip from './VersionChip.vue'
import BlockStatusBadge from './BlockStatusBadge.vue'

const props = defineProps({
  node: { type: Object, required: true },
  nodeError: { type: Object, default: null },
  pending: { type: Boolean, default: false },
})
const emit = defineEmits(['op'])

// 行内输入框出现时自动聚焦
const vFocus = { mounted: (el) => el.focus() }

const collapsed = ref(false)
const mode = ref('') // '' | 'rename' | 'add'
const draft = ref('')
const confirming = ref(false)

const CHILD_KIND = { project: 'domain', domain: 'document', document: 'block' }
const CHILD_LABEL = { project: '大业务', domain: '文档', document: '模块' }

const key = computed(() => `${props.node.kind}-${props.node.id}`)
const canAdd = computed(() => !!CHILD_KIND[props.node.kind])
const isBlock = computed(() => props.node.kind === 'block')

const errorHere = computed(() =>
  props.nodeError && props.nodeError.key === key.value ? props.nodeError.text : '',
)

const link = computed(() => {
  const n = props.node
  if (n.kind === 'document') return `/documents/${n.id}`
  if (n.kind === 'block') return n.version ? `/blocks/${n.id}` : `/blocks/${n.id}/edit`
  return ''
})

const deleteLabel = computed(() =>
  isBlock.value && props.node.status !== 'draft' ? '归档' : '删除',
)

const deleteText = computed(() => {
  const n = props.node
  switch (n.kind) {
    case 'project':
      return `删除项目「${n.name}」？其下全部 大业务 / 文档 / 模块 与绑定该项目的密钥将一并删除；若有已发布模块将被拒绝。`
    case 'domain':
      return `删除大业务「${n.name}」？其下若有已发布模块将被拒绝（409）。`
    case 'document':
      return `删除文档「${n.name}」？其下若有已发布模块将被拒绝（409）。`
    default:
      return n.status === 'draft'
        ? `删除草稿模块「${n.name}」？草稿将被直接删除。`
        : `归档已发布模块「${n.name}」？agent 将立即读不到它，历史版本保留可查。`
  }
})

function startRename() {
  draft.value = props.node.name
  mode.value = 'rename'
  confirming.value = false
}

function startAdd() {
  draft.value = ''
  mode.value = 'add'
  collapsed.value = false
  confirming.value = false
}

function cancel() {
  mode.value = ''
  confirming.value = false
}

function submitRename() {
  const name = draft.value.trim()
  if (!name || name === props.node.name) return cancel()
  emit('op', {
    action: 'rename',
    kind: props.node.kind,
    id: props.node.id,
    name,
    errorKey: key.value,
  })
  mode.value = ''
}

function submitAdd() {
  const name = draft.value.trim()
  if (!name) return
  emit('op', {
    action: 'create',
    kind: CHILD_KIND[props.node.kind],
    parentId: props.node.id,
    name,
    errorKey: key.value,
  })
  mode.value = ''
}

function confirmDelete() {
  emit('op', {
    action: 'delete',
    kind: props.node.kind,
    id: props.node.id,
    errorKey: key.value,
  })
  confirming.value = false
}
</script>

<template>
  <li class="tnode" :class="`k-${node.kind}`">
    <div class="trow">
      <button
        v-if="(node.children && node.children.length) || canAdd"
        type="button"
        class="caret"
        :aria-label="collapsed ? '展开' : '收起'"
        @click="collapsed = !collapsed"
      >
        {{ collapsed ? '▸' : '▾' }}
      </button>
      <span v-else class="caret-sp"></span>

      <template v-if="mode === 'rename'">
        <input
          class="input rename-input"
          v-model="draft"
          @keyup.enter="submitRename"
          @keyup.esc="cancel"
          v-focus
        />
        <button
          type="button"
          class="btn btn-mini btn-primary"
          :disabled="pending"
          @click="submitRename"
        >
          保存
        </button>
        <button type="button" class="btn btn-mini" @click="cancel">取消</button>
      </template>

      <template v-else>
        <RouterLink v-if="link" class="tname" :to="link">{{ node.name }}</RouterLink>
        <button v-else type="button" class="tname tname-btn" @click="collapsed = !collapsed">
          {{ node.name }}
        </button>

        <span class="tmeta">
          <template v-if="node.kind === 'document'">
            <span class="doc-type mono">{{ node.docType }}</span>
            <VersionChip v-if="node.version" :version="node.version" />
          </template>
          <template v-if="isBlock">
            <VersionChip
              v-if="node.version"
              :version="node.version"
              :status="node.status === 'archived' ? 'draft' : 'published'"
            />
            <BlockStatusBadge :status="node.status" />
            <span v-if="node.completed" class="done-badge">✓ 已完成</span>
          </template>
        </span>

        <span class="tops">
          <button v-if="!isBlock" type="button" class="btn btn-mini" @click="startRename">
            重命名
          </button>
          <button
            type="button"
            class="btn btn-mini"
            :class="{ 'btn-danger': !isBlock }"
            @click="confirming = true"
          >
            {{ deleteLabel }}
          </button>
          <button v-if="canAdd" type="button" class="btn btn-mini" @click="startAdd">
            新建{{ CHILD_LABEL[node.kind] }}
          </button>
        </span>
      </template>
    </div>

    <div v-if="confirming" class="confirm-strip" role="alert">
      <span class="confirm-text">{{ deleteText }}</span>
      <button
        type="button"
        class="btn btn-mini btn-danger"
        :disabled="pending"
        @click="confirmDelete"
      >
        确认{{ deleteLabel }}
      </button>
      <button type="button" class="btn btn-mini" @click="cancel">取消</button>
    </div>

    <p v-if="errorHere" class="error-text terror" role="alert">{{ errorHere }}</p>

    <ul v-if="!collapsed && ((node.children && node.children.length) || mode === 'add')" class="tkids">
      <TreeNode
        v-for="c in node.children || []"
        :key="`${c.kind}-${c.id}`"
        :node="c"
        :node-error="nodeError"
        :pending="pending"
        @op="(e) => emit('op', e)"
      />
      <li v-if="mode === 'add'" class="trow add-row">
        <span class="caret-sp"></span>
        <input
          class="input rename-input"
          v-model="draft"
          :placeholder="`${CHILD_LABEL[node.kind]}名称`"
          @keyup.enter="submitAdd"
          @keyup.esc="cancel"
          v-focus
        />
        <button
          type="button"
          class="btn btn-mini btn-primary"
          :disabled="pending"
          @click="submitAdd"
        >
          创建{{ CHILD_LABEL[node.kind] }}
        </button>
        <button type="button" class="btn btn-mini" @click="cancel">取消</button>
      </li>
    </ul>
  </li>
</template>


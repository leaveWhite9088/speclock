<script setup>
// 回执详情弹窗：上段版本上下文（版本/发布说明/delta 摘要/取代提示/跳转），
// 下段回执记录。遮罩 + 居中卡片，点遮罩 / Esc / 关闭按钮关闭。
import { computed, onMounted, onUnmounted } from 'vue'
import { useKeyNames } from '../api/keyNames.js'
import { fmtTime, parseTs } from '../time.js'
import VersionChip from './VersionChip.vue'

const { keyName } = useKeyNames()

const props = defineProps({
  title: { type: String, default: '回执' },
  // {block_id, version, change_note, published_by, published_at, current_version, prev_version?}
  context: { type: Object, default: null },
  acks: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  blockId: { type: [Number, String], default: null },
})
const emit = defineEmits(['close'])

const supersededBy = computed(() => {
  const c = props.context
  return c?.current_version && c.version !== c.current_version ? c.current_version : null
})

function intervalLabel(a) {
  const pub = props.context?.published_at
  if (!pub || !a.created_at) return ''
  const created = parseTs(a.created_at)
  const published = parseTs(pub)
  if (!created || !published) return ''
  const hours = (created - published) / 36e5
  if (!Number.isFinite(hours) || hours < 0) return ''
  return hours < 24 ? `${Math.round(hours)} 小时后` : `${Math.round(hours / 24)} 天后`
}

function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div class="modal-mask" @click.self="emit('close')">
      <div class="modal-card" role="dialog" aria-modal="true" :aria-label="title">
        <header class="modal-head">
          <h3 class="modal-title">{{ title }}</h3>
          <button
            type="button"
            class="modal-close"
            aria-label="关闭"
            @click="emit('close')"
          >
            ×
          </button>
        </header>

        <p v-if="loading" class="muted modal-loading">加载版本上下文…</p>

        <section v-else-if="context" class="modal-context">
          <div class="ctx-head">
            <VersionChip :version="context.version" />
            <span class="mono ctx-by">{{ keyName(context.published_by) }}</span>
            <span class="muted ctx-time">{{ fmtTime(context.published_at) }}</span>
          </div>
          <p class="ctx-note">{{ context.change_note || '无变更说明' }}</p>
          <p v-if="supersededBy" class="muted ctx-superseded">
            该版本已被 v{{ supersededBy }} 取代，此为历史回执
          </p>
          <div class="ctx-links">
            <RouterLink
              class="ctx-link"
              :to="`/blocks/${context.block_id}?version=${context.version}`"
              @click="emit('close')"
              >查看该版本 →</RouterLink
            >
            <RouterLink
              v-if="context.prev_version"
              class="ctx-link"
              :to="`/blocks/${context.block_id}/diff?from=${context.prev_version}&to=${context.version}`"
              @click="emit('close')"
              >查看 diff →</RouterLink
            >
          </div>
        </section>
        <section v-else-if="blockId" class="modal-context">
          <RouterLink class="ctx-link" :to="`/blocks/${blockId}`" @click="emit('close')"
            >去模块页 →</RouterLink
          >
        </section>

        <p v-if="!acks.length" class="muted">无回执记录。</p>
        <ul v-else class="modal-acks">
          <li v-for="(a, i) in acks" :key="i" class="modal-ack">
            <div class="modal-ack-head">
              <span class="mono modal-key">{{ keyName(a.agent_key) }}</span>
              <span v-if="intervalLabel(a)" class="ack-interval">
                {{ intervalLabel(a) }}
              </span>
              <span class="muted modal-time">{{ fmtTime(a.created_at) }}</span>
            </div>
            <p v-if="a.task_desc" class="modal-task">{{ a.task_desc }}</p>
          </li>
        </ul>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: color-mix(in srgb, var(--ink) 42%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-5);
}

.modal-card {
  width: 100%;
  max-width: 560px;
  max-height: 80vh;
  overflow: auto;
  background: var(--card);
  border: 1px solid var(--hairline);
  border-radius: var(--radius);
  box-shadow: 0 12px 40px color-mix(in srgb, var(--ink) 22%, transparent);
  padding: var(--sp-4) var(--sp-5);
}

.modal-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding-bottom: var(--sp-3);
  border-bottom: 1px solid var(--hairline);
}

.modal-title {
  font-size: var(--text-md);
  font-weight: 600;
  margin: 0;
}

.modal-close {
  margin-left: auto;
  appearance: none;
  background: none;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-sm);
  color: var(--ink-2);
  font: inherit;
  font-size: var(--text-md);
  line-height: 1;
  padding: 2px var(--sp-2);
  cursor: pointer;
  transition:
    color var(--dur) var(--ease),
    border-color var(--dur) var(--ease);
}

.modal-close:hover {
  color: var(--ink);
  border-color: var(--ink-2);
}

/* ---------- 上段：版本上下文 ---------- */

.modal-loading {
  margin-top: var(--sp-3);
  font-size: var(--text-sm);
}

.modal-context {
  margin-top: var(--sp-3);
  padding-bottom: var(--sp-3);
  border-bottom: 1px solid var(--hairline);
}

.ctx-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.ctx-by {
  font-size: var(--text-xs);
  color: var(--ink-2);
}

.ctx-time {
  margin-left: auto;
  font-size: var(--text-xs);
  white-space: nowrap;
}

.ctx-note {
  margin: var(--sp-2) 0 0;
  font-size: var(--text-sm);
  white-space: pre-wrap;
  word-break: break-word;
}

.ctx-superseded {
  margin: var(--sp-1) 0 0;
  font-size: var(--text-xs);
}

.ctx-links {
  margin-top: var(--sp-2);
  display: flex;
  gap: var(--sp-3);
}

.ctx-link {
  font-size: var(--text-sm);
}

/* ---------- 下段：回执记录 ---------- */

.modal-acks {
  margin: var(--sp-2) 0 0;
  padding: 0;
  list-style: none;
}

.modal-ack {
  padding: var(--sp-3) 0;
  border-bottom: 1px solid var(--hairline);
}

.modal-ack:last-child {
  border-bottom: none;
}

.modal-ack-head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
}

.modal-key {
  font-size: var(--text-sm);
}

.ack-interval {
  font-size: var(--text-xs);
  padding: 0 var(--sp-2);
  border-radius: var(--radius-sm);
  border: 1px solid var(--hairline);
  color: var(--ink-2);
  white-space: nowrap;
}

.modal-time {
  margin-left: auto;
  font-size: var(--text-xs);
  white-space: nowrap;
}

.modal-task {
  margin: var(--sp-1) 0 0;
  font-size: var(--text-sm);
  color: var(--ink-2);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>

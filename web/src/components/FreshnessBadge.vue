<script setup>
/**
 * 顶栏的刷新状态小指示：「● 已是最新」平时是灰绿色；刚发现新变化时短暂高亮「有新变化，已刷新」；
 * 连不上服务时变红；没有读活动日志的权限时说明是定时刷新。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useChangeSignal } from '../composables/useChangeSignal.js'

const { checkedAt, changedAt, mode, error } = useChangeSignal()

const now = ref(Date.now())
let timer = null
onMounted(() => (timer = setInterval(() => (now.value = Date.now()), 1000)))
onBeforeUnmount(() => timer && clearInterval(timer))

const justChanged = computed(() => changedAt.value && now.value - changedAt.value < 4000)

const state = computed(() => {
  if (error.value) return { cls: 'bad', text: '连不上服务', title: error.value }
  if (!checkedAt.value) return { cls: 'idle', text: '检查中…', title: '' }
  if (justChanged.value) return { cls: 'changed', text: '有新变化，已刷新', title: '' }
  if (mode.value === 'timer') {
    return { cls: 'ok', text: '定时刷新', title: '当前密钥没有读取活动日志的权限，页面每 30 秒左右自动刷新一次' }
  }
  return { cls: 'ok', text: '已是最新', title: '页面会在有新变化时自动刷新（每 5 秒检查一次）' }
})
</script>

<template>
  <span class="fresh" :class="state.cls" :title="state.title" role="status">
    <span class="dot" aria-hidden="true"></span>{{ state.text }}
  </span>
</template>

<style scoped>
.fresh {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-xs);
  color: var(--ink-2);
  white-space: nowrap;
}

.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ink-2);
}

.ok .dot {
  background: var(--success);
}

.changed {
  color: var(--contract);
  font-weight: 500;
}

.changed .dot {
  background: var(--contract);
}

.bad {
  color: var(--danger);
}

.bad .dot {
  background: var(--danger);
}
</style>

/**
 * 变化信号：全站只有一个定时器（在 App.vue 里启动），每几秒问一次「有没有新的、会改变数据的活动」
 * （/activity，排除读取，只取最新一条）。最新一条的 id 变了，version 就加一，各页面据此静默刷新。
 *
 * 为什么不是每页各自轮询：一次廉价的请求就能知道「有没有变化」，没变化时页面一个请求都不用发。
 *
 * 没有 audit.read 权限（读不了活动）时退化为定时刷新：每隔 FALLBACK_TICKS 次检查让 version 加一。
 */
import { ref } from 'vue'
import { getKey } from '../api/client.js'
import { resources } from '../api/resources.js'
import { errText } from '../errors.js'

export const FALLBACK_TICKS = 6

const latestId = ref(null)
const version = ref(0)
const checkedAt = ref(null) // 最近一次检查成功的时间（毫秒）
const changedAt = ref(null) // 最近一次发现变化的时间（毫秒）
const mode = ref('activity') // activity：靠活动日志判断；timer：没有权限，定时刷新
const error = ref('')
let fallbackTicks = 0

export async function checkOnce() {
  if (!getKey()) return // 还没拿到网页用的只读 key 就不查
  try {
    const rows = await resources.activity({ limit: 1, exclude_action: 'pull' })
    const id = rows[0]?.id ?? 0
    mode.value = 'activity'
    error.value = ''
    if (latestId.value !== null && id !== latestId.value) {
      version.value += 1
      changedAt.value = Date.now()
    }
    latestId.value = id
    checkedAt.value = Date.now()
  } catch (e) {
    if (e?.status === 403) {
      mode.value = 'timer'
      error.value = ''
      checkedAt.value = Date.now()
      fallbackTicks += 1
      if (fallbackTicks >= FALLBACK_TICKS) {
        fallbackTicks = 0
        version.value += 1
        changedAt.value = Date.now()
      }
    } else if (e?.status !== 401) {
      error.value = errText(e)
    }
  }
}

/** 页面用：读取信号状态 */
export function useChangeSignal() {
  return { version, checkedAt, changedAt, mode, error }
}

/** 测试用：回到初始状态 */
export function _resetChangeSignal() {
  latestId.value = null
  version.value = 0
  checkedAt.value = null
  changedAt.value = null
  mode.value = 'activity'
  error.value = ''
  fallbackTicks = 0
}

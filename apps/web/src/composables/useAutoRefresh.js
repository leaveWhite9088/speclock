import { watch } from 'vue'
import { useChangeSignal } from './useChangeSignal.js'

/**
 * 页面接入自动刷新：变化信号变了就调用 fn({ silent: true }) 静默刷新。
 * 静默 = 不把页面切回「加载中」，数据到了直接替换；失败时保留旧内容。
 * 页面里用户展开的东西、滚动位置都在页面自己的状态里，不会被刷新冲掉。
 */
export function useAutoRefresh(fn) {
  const { version } = useChangeSignal()
  watch(version, () => fn({ silent: true }))
}

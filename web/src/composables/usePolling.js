import { onBeforeUnmount, onMounted } from 'vue'

/**
 * 定时执行 fn（例如静默刷新）。页面不可见时暂停，重新可见时立刻补一次并继续。
 *
 *   const { pause, resume } = usePolling(() => reload({ silent: true }), 10000)
 *
 * 不会重叠：上一次还没结束就不会开始下一次。
 */
export function usePolling(fn, intervalMs, { immediate = false } = {}) {
  let timer = null
  let running = false
  let paused = false

  async function tick() {
    if (running) return
    running = true
    try {
      await fn()
    } catch {
      /* 轮询里的错误交给 fn 自己处理 */
    } finally {
      running = false
    }
  }

  function start() {
    stop()
    if (paused) return
    timer = setInterval(() => {
      if (typeof document === 'undefined' || !document.hidden) tick()
    }, intervalMs)
  }

  function stop() {
    if (timer) clearInterval(timer)
    timer = null
  }

  function onVisibility() {
    if (typeof document !== 'undefined' && !document.hidden && !paused) tick()
  }

  function pause() {
    paused = true
    stop()
  }

  function resume() {
    paused = false
    start()
  }

  onMounted(() => {
    if (immediate) tick()
    start()
    document.addEventListener('visibilitychange', onVisibility)
  })

  onBeforeUnmount(() => {
    stop()
    document.removeEventListener('visibilitychange', onVisibility)
  })

  return { pause, resume }
}

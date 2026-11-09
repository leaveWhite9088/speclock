import { onMounted, ref, watch } from 'vue'
import { errText } from '../errors.js'

/**
 * 异步取数的统一封装：loading / error / data / reload。
 *
 *   const { data, loading, error, reload } = useAsync(() => resources.crs.list(status.value), {
 *     watch: [status],       // 这些 ref 变化时自动重新取
 *   })
 *
 * - 连续触发多次时，只采用最后一次的结果（避免慢请求覆盖新结果）；
 * - reload({ silent: true }) 静默刷新：不把页面切回「加载中」，用于自动刷新；
 * - 出错时 error 是给人看的中文文案（见 errors.js）。
 */
export function useAsync(fn, { watch: sources = [], immediate = true, initial = null } = {}) {
  const data = ref(initial)
  const loading = ref(immediate)
  const error = ref('')
  let ticket = 0

  async function reload({ silent = false } = {}) {
    const mine = ++ticket
    if (!silent) {
      loading.value = true
      error.value = ''
    }
    try {
      const result = await fn()
      if (mine !== ticket) return
      data.value = result
      error.value = ''
    } catch (e) {
      if (mine !== ticket) return
      // 静默刷新失败时保留旧数据和旧状态，不打扰用户；非静默才展示错误
      if (!silent) error.value = errText(e)
    } finally {
      if (mine === ticket) loading.value = false
    }
  }

  if (immediate) onMounted(() => reload())
  if (sources.length) watch(sources, () => reload())

  return { data, loading, error, reload }
}

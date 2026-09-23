// key hint（agent-…1a2b）→ key 名称（label）的展示映射。
// 数据来自 /keys（admin 接口）；key 已删除或 hint 冲突时回退显示 hint 本身。
import { ref } from 'vue'
import { api } from './client.js'

const names = ref(new Map())
let loading = null

export function useKeyNames() {
  if (!loading) {
    loading = api
      .get('/keys')
      .then((list) => {
        const dup = {}
        for (const k of list) dup[k.hint] = (dup[k.hint] || 0) + 1
        const m = new Map()
        for (const k of list) {
          if (k.label && dup[k.hint] === 1) m.set(k.hint, k.label)
        }
        names.value = m
      })
      .catch(() => {})
  }
  function keyName(hint) {
    return names.value.get(hint) || hint
  }
  return { keyName }
}

// key hint（agent-…1a2b）→ key 信息（备注 label、角色 role）的展示映射。
// 数据来自 /keys（需要 key.manage 的接口）；没有权限、key 已删除或 hint 冲突时回退显示 hint 本身。
import { ref } from 'vue'
import { api } from './client.js'

const infos = ref(new Map())
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
          if (dup[k.hint] === 1) m.set(k.hint, { label: k.label || '', role: k.role || '' })
        }
        infos.value = m
      })
      .catch(() => {})
  }
  function keyInfo(hint) {
    return infos.value.get(hint) || { label: '', role: '' }
  }
  function keyName(hint) {
    return keyInfo(hint).label || hint
  }
  return { keyName, keyInfo }
}

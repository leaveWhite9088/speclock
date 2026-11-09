/**
 * 复核时看新旧文字：去掉公共的开头和结尾，剩下中间被改的那一小段标成「删掉 / 新增」。
 * 内部整理的复核只处理小幅改动，这样已经足够清楚，不需要完整的 LCS。
 */

export function charDiff(oldText, newText) {
  const a = String(oldText ?? '')
  const b = String(newText ?? '')
  if (a === b) return [{ kind: 'same', text: a }]
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start += 1
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA -= 1
    endB -= 1
  }
  const out = []
  if (start) out.push({ kind: 'same', text: a.slice(0, start) })
  if (endA > start) out.push({ kind: 'del', text: a.slice(start, endA) })
  if (endB > start) out.push({ kind: 'add', text: b.slice(start, endB) })
  if (endA < a.length) out.push({ kind: 'same', text: a.slice(endA) })
  return out
}

/** 一条改动的位置说明：模块 · 规则 R-2 · 详述 */
export function changeWhere(c) {
  const kind = c.kind === 'ac' ? '验收条件' : '规则'
  const field = c.field === 'name' ? '名称' : '详述'
  return `${c.block_title || `模块 #${c.block_id}`} · ${kind} ${c.item_id} · ${field}`
}

/**
 * 搜索结果的展示辅助：高亮片段、分组、跳转链接。
 */

export const HIT_TYPES = [
  { type: 'module', label: '模块' },
  { type: 'rule', label: '业务规则' },
  { type: 'acceptance', label: '验收条件' },
  { type: 'api', label: 'API' },
  { type: 'cr', label: '审核单' },
]

/** 把文字按关键词切成 [{text, hit}]，用于高亮（不区分大小写，保留原文大小写） */
export function highlightSegments(text, q) {
  const s = String(text ?? '')
  const needle = String(q ?? '').trim().toLowerCase()
  if (!needle) return [{ text: s, hit: false }]
  const low = s.toLowerCase()
  const out = []
  let pos = 0
  for (;;) {
    const i = low.indexOf(needle, pos)
    if (i < 0) break
    if (i > pos) out.push({ text: s.slice(pos, i), hit: false })
    out.push({ text: s.slice(i, i + needle.length), hit: true })
    pos = i + needle.length
  }
  if (pos < s.length) out.push({ text: s.slice(pos), hit: false })
  return out.length ? out : [{ text: s, hit: false }]
}

/** 按类型分组，保持 HIT_TYPES 的顺序，空组不出现 */
export function groupHits(hits = []) {
  return HIT_TYPES.map((t) => ({ ...t, hits: hits.filter((h) => h.type === t.type) })).filter((g) => g.hits.length)
}

/** 命中项的跳转地址：规则 / 验收条件直达到模块页里对应的那一行 */
export function hitLink(hit) {
  if (hit.type === 'cr') return `/change-requests/${hit.cr_id}`
  const base = `/blocks/${hit.block_id}?version=${hit.version}`
  if (hit.type === 'rule' || hit.type === 'acceptance') return hit.item_id ? `${base}#item-${hit.item_id}` : base
  return base
}

/** 命中项所在位置的一行说明：大业务 / 小业务 / 模块 vX */
export function hitPath(hit) {
  if (hit.type === 'cr') return `审核单 #${hit.cr_id}`
  return `${hit.business} / ${hit.capability_title} / ${hit.block_title} v${hit.version}`
}

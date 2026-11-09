/**
 * 文档树的筛选与进度（纯函数）：按模块当前版本的执行状态过滤，小业务显示「已验收 / 总数」。
 */

export const TREE_FILTERS = [
  ['', '全部模块'],
  ['open', '未验收'],
  ['stuck', '卡住（被阻塞 / 失败）'],
  ['pending', '待领取'],
  ['in_progress', '进行中'],
  ['implemented', '待验收'],
  ['verified', '已验收'],
]

/** 只有已发布、有当前版本的模块才参与筛选 */
function isLive(block) {
  return block.kind === 'block' && block.status === 'published' && !!block.version
}

export function matchesFilter(block, filter) {
  if (!filter) return true
  if (!isLive(block)) return false
  const s = block.execution_status
  if (filter === 'open') return s !== 'verified'
  if (filter === 'stuck') return s === 'blocked' || s === 'failed'
  return s === filter
}

/** 保留命中的模块，以及包含命中模块的上层节点；没有筛选条件时原样返回 */
export function filterTree(nodes, filter) {
  if (!filter) return nodes
  const walk = (node) => {
    if (node.kind === 'block') return matchesFilter(node, filter) ? node : null
    const children = (node.children || []).map(walk).filter(Boolean)
    return children.length ? { ...node, children } : null
  }
  return nodes.map(walk).filter(Boolean)
}

/** 一组模块里：已发布的数量与其中已验收的数量 */
export function progressOf(blocks = []) {
  const live = blocks.filter(isLive)
  return { total: live.length, verified: live.filter((b) => b.execution_status === 'verified').length }
}

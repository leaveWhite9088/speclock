/**
 * 总览首页的数据整理：把审核单、待办、文档树拼成「现在有什么需要人关注的」。
 * 纯函数，方便测试；页面只负责取数和展示。
 */
import { parseTs } from './time.js'

const DAY = 24 * 3600 * 1000

function ts(iso) {
  return parseTs(iso)?.getTime() ?? 0
}

function countBy(list, key) {
  const out = {}
  for (const x of list) out[x[key]] = (out[x[key]] || 0) + 1
  return out
}

/** 文档树里的模块统计：已发布模块数、其中当前版本已验收的数量 */
export function moduleStats(tree = []) {
  let published = 0
  let verified = 0
  for (const p of tree)
    for (const biz of p.businesses || [])
      for (const cap of biz.capabilities || [])
        for (const b of cap.blocks || []) {
          if (b.status !== 'published') continue
          published += 1
          if (b.execution_status === 'verified') verified += 1
        }
  return { published, verified }
}

export function buildOverview({ crs = [], work = [], tree = [], now = Date.now(), internalDays = 7 } = {}) {
  // 等我确认：最久的排最前
  const pending = crs
    .filter((c) => c.status === 'pending_review')
    .sort((a, b) => ts(a.submitted_at || a.created_at) - ts(b.submitted_at || b.created_at))

  // Agent 自行判定的内部整理：最近 N 天，新的在前
  const internal = crs
    .filter((c) => c.kind === 'internal' && c.status !== 'draft')
    .filter((c) => now - ts(c.decided_at || c.submitted_at || c.created_at) <= internalDays * DAY)
    .sort((a, b) => ts(b.decided_at || b.created_at) - ts(a.decided_at || a.created_at))

  // 卡住的任务（被阻塞 / 失败）：等得最久的排最前
  const stuck = work
    .filter((w) => w.status === 'blocked' || w.status === 'failed')
    .sort((a, b) => ts(a.updated_at) - ts(b.updated_at))

  const waiting = work
    .filter((w) => w.status === 'implemented')
    .sort((a, b) => ts(a.updated_at) - ts(b.updated_at))

  const inProgress = work
    .filter((w) => w.status === 'in_progress')
    .sort((a, b) => ts(a.updated_at) - ts(b.updated_at))

  const mods = moduleStats(tree)
  return {
    pending,
    internal,
    stuck,
    waiting,
    inProgress,
    counts: {
      crs: countBy(crs, 'status'),
      work: countBy(work, 'status'),
      modules: mods.published,
      verifiedModules: mods.verified,
      verifiedPercent: mods.published ? Math.round((mods.verified / mods.published) * 100) : 0,
    },
    // 所有「需要人关注」的东西的总数：待确认 + 卡住 + 内部整理（事后过目）
    attention: pending.length + stuck.length + internal.length,
    isEmpty: !crs.length && !work.length && !mods.published,
  }
}

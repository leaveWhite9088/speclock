/**
 * 审计日志条目的展示辅助：把 target 字符串变成「文字 + 链接」，把 detail 里最有用的一句话挑出来。
 * 后端 target 的形式（见 speclock/*.py 里的 audit 调用）：
 *   cr:5  cr:5/commit:12  block:3@1.0.0  block:3/diff  block:3/history
 *   capability:2@1.1.0  capability:2/history  work:3@1.0.0（注意：work 后面是模块 id）
 *   apikey:agent-…1a2b  role:tester-agent  project:1  index  capabilities
 */

import { ACTIONS, label } from './labels.js'

export function parseTarget(target) {
  const t = String(target || '')
  let m

  if ((m = t.match(/^cr:(\d+)\/commit:(\d+)$/))) {
    return { text: `审核单 #${m[1]} 的 Commit`, to: `/change-requests/${m[1]}` }
  }
  if ((m = t.match(/^cr:(\d+)$/))) {
    return { text: `审核单 #${m[1]}`, to: `/change-requests/${m[1]}` }
  }
  if ((m = t.match(/^block:(\d+)(?:@([\d.]+))?(?:\/(diff|history))?$/))) {
    const ver = m[2] ? ` @${m[2]}` : ''
    const extra = m[3] === 'diff' ? '（对比）' : m[3] === 'history' ? '（历史）' : ''
    const to = m[2] ? `/blocks/${m[1]}?version=${m[2]}` : `/blocks/${m[1]}`
    return { text: `模块 #${m[1]}${ver}${extra}`, to }
  }
  if ((m = t.match(/^capability:(\d+)(?:@([\d.]+))?(?:\/history)?$/))) {
    return { text: `小业务 #${m[1]}${m[2] ? ` @${m[2]}` : ''}`, to: `/capabilities/${m[1]}` }
  }
  if ((m = t.match(/^work:(\d+)@([\d.]+)$/))) {
    return { text: `模块 #${m[1]} @${m[2]} 的任务`, to: `/blocks/${m[1]}?version=${m[2]}` }
  }
  if ((m = t.match(/^apikey:(.+)$/))) return { text: `密钥 ${m[1]}`, to: '/agents' }
  if ((m = t.match(/^role:(.+)$/))) return { text: `角色 ${m[1]}`, to: '/agents' }
  if ((m = t.match(/^project:(.+)$/))) return { text: `项目 ${m[1]}`, to: '' }
  if (t === 'index' || t === 'capabilities') return { text: '规格索引', to: '' }
  return { text: t || '—', to: '' }
}

/** 一句话摘要：理由 / 人的原话 / 备注 / 标题，取最有信息量的一个；没有就返回空串 */
export function activityNote(item) {
  const d = item?.detail || {}
  if (d.reason) return String(d.reason)
  if (d.evidence) return `「${d.evidence}」`
  if (d.note) return String(d.note)
  if (d.change_note) return String(d.change_note)
  if (d.title) return String(d.title)
  if (item?.action === 'key_create' && d.role) return `角色 ${d.role}${d.label ? `，备注 ${d.label}` : ''}`
  return ''
}

/** 动作的中文名。内部整理单由 Agent 自行判定生效，不叫「批准」，免得人误以为自己批准过 */
export function actionLabel(item) {
  if (item?.action === 'cr_approve' && item?.detail?.via === 'agent_declared') {
    return '内部整理生效（Agent 自行判定）'
  }
  return label(ACTIONS, item?.action)
}

/** 读取类动作（pull）占了日志的绝大部分，默认不展示 */
export function isRead(item) {
  return item?.action === 'pull'
}

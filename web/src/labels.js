/**
 * 全站统一的中文文案：状态名、动作名都集中在这里，页面和组件不再各写一份。
 * 查不到的键原样显示（后端新增了状态 / 动作时页面不会空白）。
 */

export const CR_STATUS = {
  draft: '草稿',
  pending_review: '待确认',
  approved: '已批准',
  applied: '已落地',
  rejected: '已驳回',
  superseded: '已被取代',
}

/** Commit 的状态（语义复核：字变了、意思没变的小改动要另一个角色复核通过才生效） */
export const COMMIT_STATUS = {
  applied: '已落地',
  pending_review: '待复核',
  review_rejected: '复核不通过',
  withdrawn: '已作废',
}

export const CR_KIND = {
  business: '业务变更',
  internal: '内部整理',
}

/** 批准 / 驳回的方式 */
export const DECISION_VIA = {
  cli: '命令行',
  natural_language: '对话中明确表态',
  api: '接口',
  agent_declared: 'Agent 自行判定（内部整理，未经人批准）',
}

export const EXEC_STATUS = {
  pending: '待领取',
  in_progress: '进行中',
  blocked: '被阻塞',
  failed: '失败',
  implemented: '待验收',
  verified: '已验收',
  superseded: '已被取代',
}

/** 执行记录的事件（状态转换） */
export const EXEC_EVENT = {
  created: '产生任务',
  claim: '领取',
  release: '放弃领取',
  blocked: '报告阻塞',
  failed: '报告失败',
  implemented: '提交实现',
  verified: '验收通过',
  verify_failed: '验收不通过',
  superseded: '被新版本取代',
}

export const BLOCK_STATUS = {
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
}

export const VERSION_STATUS = {
  current: '当前版本',
  deprecated: '已被取代',
}

export const LEVEL = {
  initial: '首个版本',
  major: '主要变更',
  minor: '新增内容',
  patch: '小修订',
}

/** 审计日志里的动作 */
export const ACTIONS = {
  pull: '读取',
  publish: '发布版本',
  commit: '提交 Commit',
  archive: '归档模块',
  restore: '恢复模块',
  move: '搬动模块',
  cr_create: '创建审核单',
  cr_update: '修改审核单',
  cr_submit: '提交审核单',
  cr_withdraw: '撤回审核单',
  cr_approve: '批准审核单',
  cr_reject: '驳回审核单',
  cr_applied: '审核单落地',
  cr_superseded: '审核单被取代',
  commit_review_requested: '提交待复核',
  commit_review_approved: '复核通过',
  commit_review_rejected: '复核不通过',
  exec_claim: '领取任务',
  exec_release: '放弃领取',
  exec_blocked: '报告阻塞',
  exec_failed: '报告失败',
  exec_implemented: '提交实现',
  exec_verified: '验收通过',
  exec_verify_failed: '验收不通过',
  exec_superseded: '任务被取代',
  key_create: '创建密钥',
  key_delete: '删除密钥',
  role_create: '创建角色',
  role_update: '修改角色',
  role_delete: '删除角色',
  project_create: '创建项目',
  rename: '重命名',
  delete: '删除',
}

export function label(map, key) {
  return map[key] || key || '—'
}

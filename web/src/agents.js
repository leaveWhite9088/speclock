/**
 * Agent 与密钥视图的数据整理（纯函数）：把「谁手里有什么权力」讲清楚。
 */

/** 值得人特别留意的权力：key 是 Core 的钥匙，所以 key.manage / cr.approve 标成醒目 */
export const POWER_TAGS = [
  { perm: 'key.manage', text: '能管理密钥', strong: true },
  { perm: 'cr.approve', text: '能批准审核单', strong: true },
  { perm: 'cr.internal', text: '能自行判定内部整理', strong: false },
  { perm: 'commit.write', text: '能改写规格', strong: false },
  { perm: 'exec.verify', text: '能验收', strong: false },
]

export function powerTags(permissions = []) {
  const have = new Set(permissions)
  return POWER_TAGS.filter((t) => have.has(t.perm))
}

/** 把 /keys 与 /roles、/projects 合并成页面要显示的行 */
export function describeKeys({ keys = [], roles = [], projects = [], me = '' } = {}) {
  const roleByName = new Map(roles.map((r) => [r.name, r]))
  const projectName = new Map(projects.map((p) => [p.id, p.name]))
  return keys.map((k) => {
    const role = roleByName.get(k.role)
    const permissions = role?.permissions || []
    return {
      id: k.id,
      hint: k.hint,
      label: k.label,
      role: k.role || '',
      kind: k.prefix === 'human' ? '人' : 'Agent',
      project: k.project_id == null ? '全局' : projectName.get(k.project_id) || `项目 ${k.project_id}`,
      createdAt: k.created_at,
      lastActiveAt: k.last_active_at,
      isMe: !!me && k.hint === me,
      // 当前登录的这把 key 在网页上的浏览不记审计，不能因此说它「从未使用」
      neverUsed: !k.last_active_at && !(me && k.hint === me),
      actions7d: k.actions_7d || 0,
      reads7d: k.reads_7d || 0,
      power: powerTags(permissions),
      strongPower: powerTags(permissions).some((t) => t.strong),
    }
  })
}

/** 权限 × 角色矩阵：每行一个权限，每列一个角色 */
export function permissionMatrix({ roles = [], permissions = [] } = {}) {
  return {
    roles: roles.map((r) => ({ name: r.name, kind: r.kind, keyCount: r.key_count ?? 0, builtin: !!r.builtin })),
    rows: permissions.map((p) => ({
      name: p.name,
      description: p.description,
      humanOnly: !!p.human_only,
      cells: roles.map((r) => (r.permissions || []).includes(p.name)),
    })),
  }
}

/** 页面顶部的一句话概览 */
export function keySummary(rows) {
  const strong = rows.filter((r) => r.strongPower).length
  const unused = rows.filter((r) => r.neverUsed).length
  const parts = [`共 ${rows.length} 把密钥`]
  if (strong) parts.push(`${strong} 把拥有管理密钥或批准审核单的权力`)
  if (unused) parts.push(`${unused} 把从未使用过`)
  return parts.join('，') + '。'
}

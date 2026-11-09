import { describe, expect, it } from 'vitest'
import { describeKeys, keySummary, permissionMatrix, powerTags } from './agents.js'

const roles = [
  { name: 'admin', kind: 'human', permissions: ['key.manage', 'cr.approve', 'cr.internal', 'commit.write', 'spec.read'], key_count: 1, builtin: true },
  { name: 'executor-agent', kind: 'agent', permissions: ['spec.read', 'exec.write'], key_count: 2, builtin: true },
  { name: 'requirements-agent', kind: 'agent', permissions: ['cr.write', 'cr.internal', 'commit.write'], key_count: 1, builtin: true },
]
const projects = [{ id: 1, name: '社区小店' }]
const keys = [
  { id: 1, hint: 'human-…0001', label: 'admin', prefix: 'human', role: 'admin', project_id: null, created_at: '2026-11-01T00:00:00', last_active_at: '2026-11-09T10:00:00', actions_7d: 3, reads_7d: 0 },
  { id: 2, hint: 'agent-…aaaa', label: '后端执行', prefix: 'agent', role: 'executor-agent', project_id: 1, created_at: '2026-11-02T00:00:00', last_active_at: '2026-11-09T09:00:00', actions_7d: 12, reads_7d: 40 },
  { id: 3, hint: 'agent-…bbbb', label: '没用过', prefix: 'agent', role: 'executor-agent', project_id: 7, created_at: '2026-11-03T00:00:00', last_active_at: null },
]

describe('powerTags', () => {
  it('只列出值得留意的权力，管理密钥和批准是醒目的', () => {
    const tags = powerTags(['spec.read', 'key.manage', 'cr.internal'])
    expect(tags.map((t) => t.perm)).toEqual(['key.manage', 'cr.internal'])
    expect(tags.find((t) => t.perm === 'key.manage').strong).toBe(true)
    expect(tags.find((t) => t.perm === 'cr.internal').strong).toBe(false)
  })

  it('没有权限时为空', () => {
    expect(powerTags([])).toEqual([])
    expect(powerTags()).toEqual([])
  })
})

describe('describeKeys', () => {
  const rows = describeKeys({ keys, roles, projects })

  it('合并角色权限、项目名，区分人和 Agent', () => {
    expect(rows[0]).toMatchObject({ kind: '人', project: '全局', strongPower: true })
    expect(rows[1]).toMatchObject({ kind: 'Agent', project: '社区小店', strongPower: false, actions7d: 12, reads7d: 40 })
  })

  it('项目查不到时显示编号；从未使用的标出来；统计缺省为 0', () => {
    expect(rows[2].project).toBe('项目 7')
    expect(rows[2]).toMatchObject({ neverUsed: true, actions7d: 0, reads7d: 0 })
    expect(rows[1].neverUsed).toBe(false)
  })

  it('角色查不到时没有权力标签', () => {
    const r = describeKeys({ keys: [{ ...keys[1], role: '已删除的角色' }], roles, projects })[0]
    expect(r.power).toEqual([])
  })
})

describe('permissionMatrix', () => {
  const m = permissionMatrix({
    roles,
    permissions: [
      { name: 'key.manage', description: '管理密钥', human_only: true },
      { name: 'exec.write', description: '领取任务', human_only: false },
    ],
  })

  it('列是角色（带 key 数量），行是权限（标出人类专属）', () => {
    expect(m.roles.map((r) => [r.name, r.keyCount])).toEqual([['admin', 1], ['executor-agent', 2], ['requirements-agent', 1]])
    expect(m.rows.map((r) => [r.name, r.humanOnly])).toEqual([['key.manage', true], ['exec.write', false]])
  })

  it('单元格表示「这个角色有没有这个权限」', () => {
    expect(m.rows[0].cells).toEqual([true, false, false])
    expect(m.rows[1].cells).toEqual([false, true, false])
  })
})

describe('keySummary', () => {
  it('一句话概览', () => {
    expect(keySummary(describeKeys({ keys, roles, projects }))).toBe('共 3 把密钥，1 把拥有管理密钥或批准审核单的权力，1 把从未使用过。')
    expect(keySummary([])).toBe('共 0 把密钥。')
  })
})

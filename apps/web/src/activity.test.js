import { describe, expect, it } from 'vitest'
import { CATEGORIES, RANGES, actionLabel, activityNote, activityParams, groupByDay, isRead, parseTarget } from './activity.js'

describe('parseTarget', () => {
  it('审核单与 Commit', () => {
    expect(parseTarget('cr:5')).toEqual({ text: '审核单 #5', to: '/change-requests/5' })
    expect(parseTarget('cr:5/commit:12')).toEqual({ text: '审核单 #5 的 Commit', to: '/change-requests/5' })
  })

  it('模块：带版本、对比、历史', () => {
    expect(parseTarget('block:3')).toEqual({ text: '模块 #3', to: '/blocks/3' })
    expect(parseTarget('block:3@1.2.0')).toEqual({ text: '模块 #3 @1.2.0', to: '/blocks/3?version=1.2.0' })
    expect(parseTarget('block:3/diff').text).toBe('模块 #3（对比）')
    expect(parseTarget('block:3/history').text).toBe('模块 #3（历史）')
  })

  it('小业务', () => {
    expect(parseTarget('capability:2@1.1.0')).toEqual({ text: '小业务 #2 @1.1.0', to: '/capabilities/2' })
    expect(parseTarget('capability:2/history').to).toBe('/capabilities/2')
  })

  it('任务的 target 后面是模块 id', () => {
    expect(parseTarget('work:3@1.0.0')).toEqual({ text: '模块 #3 @1.0.0 的任务', to: '/blocks/3?version=1.0.0' })
    expect(parseTarget('work:3@1.0.0#前端')).toEqual({ text: '模块 #3 @1.0.0（前端） 的任务', to: '/blocks/3?version=1.0.0' })
  })

  it('密钥 / 角色 / 项目 / 索引', () => {
    expect(parseTarget('apikey:agent-…1a2b')).toEqual({ text: '密钥 agent-…1a2b', to: '/agents' })
    expect(parseTarget('role:tester-agent').text).toBe('角色 tester-agent')
    expect(parseTarget('project:1').to).toBe('')
    expect(parseTarget('index').text).toBe('规格索引')
  })

  it('不认识的 target 原样显示，空值显示破折号', () => {
    expect(parseTarget('something:else')).toEqual({ text: 'something:else', to: '' })
    expect(parseTarget('').text).toBe('—')
    expect(parseTarget(undefined).text).toBe('—')
  })
})

describe('activityNote', () => {
  it('理由优先，其次人的原话、备注、变更说明、标题', () => {
    expect(activityNote({ detail: { reason: '只是改名', evidence: 'x' } })).toBe('只是改名')
    expect(activityNote({ detail: { evidence: '同意，按这个来' } })).toBe('「同意，按这个来」')
    expect(activityNote({ detail: { note: '重新领取' } })).toBe('重新领取')
    expect(activityNote({ detail: { change_note: '初始发布' } })).toBe('初始发布')
    expect(activityNote({ detail: { title: '调整口径' } })).toBe('调整口径')
  })

  it('创建密钥：显示角色和备注', () => {
    expect(activityNote({ action: 'key_create', detail: { role: 'tester-agent', label: 'qa' } })).toBe(
      '角色 tester-agent，备注 qa',
    )
  })

  it('没有可用信息时返回空串；缺 detail 不报错', () => {
    expect(activityNote({ detail: {} })).toBe('')
    expect(activityNote({})).toBe('')
    expect(activityNote(null)).toBe('')
  })
})

describe('actionLabel', () => {
  it('内部整理的「批准」不叫批准', () => {
    expect(actionLabel({ action: 'cr_approve', detail: { via: 'agent_declared' } })).toBe('内部整理生效（Agent 自行判定）')
    expect(actionLabel({ action: 'cr_approve', detail: { via: 'natural_language' } })).toBe('批准审核单')
  })

  it('其他动作查文案表，未知动作原样显示', () => {
    expect(actionLabel({ action: 'exec_blocked' })).toBe('报告阻塞')
    expect(actionLabel({ action: 'brand_new' })).toBe('brand_new')
  })
})

describe('isRead', () => {
  it('只有 pull 算读取', () => {
    expect(isRead({ action: 'pull' })).toBe(true)
    expect(isRead({ action: 'publish' })).toBe(false)
  })
})

describe('activityParams', () => {
  const NOW = Date.parse('2026-11-09T12:00:00Z')

  it('默认：排除读取，每页 50 条', () => {
    expect(activityParams({}, NOW)).toMatchObject({ exclude_action: 'pull', limit: 50, actor: '', target_prefix: '', since: '', before_id: null })
  })

  it('类别对应后端的 action 参数', () => {
    expect(activityParams({ category: 'cr' }, NOW).action).toBe('cr_*')
    expect(activityParams({ category: 'exec' }, NOW).action).toBe('exec_*')
    expect(activityParams({ category: 'read' }, NOW).action).toBe('pull')
    expect(activityParams({ category: 'read' }, NOW).exclude_action).toBeUndefined()
    expect(activityParams({ category: '不存在' }, NOW).exclude_action).toBe('pull')
  })

  it('时间范围：最近 N 天 / 今天（本地零点）', () => {
    expect(activityParams({ range: '7d' }, NOW).since).toBe(new Date(NOW - 7 * 24 * 3600 * 1000).toISOString())
    expect(activityParams({ range: '30d' }, NOW).since).toBe(new Date(NOW - 30 * 24 * 3600 * 1000).toISOString())
    const today = new Date(activityParams({ range: 'today' }, NOW).since)
    expect([today.getHours(), today.getMinutes(), today.getSeconds()]).toEqual([0, 0, 0])
    expect(activityParams({ range: '' }, NOW).since).toBe('')
  })

  it('谁、对象、游标、页大小原样带上', () => {
    expect(activityParams({ actor: 'agent-…1a2b', target: 'block:3', beforeId: 120, limit: 20 }, NOW)).toMatchObject({
      actor: 'agent-…1a2b',
      target_prefix: 'block:3',
      before_id: 120,
      limit: 20,
    })
  })

  it('类别与时间范围都有「全部」选项', () => {
    expect(CATEGORIES[0].key).toBe('')
    expect(RANGES[0].key).toBe('')
  })
})

describe('groupByDay', () => {
  const at = (y, mo, d, h) => new Date(y, mo - 1, d, h, 0, 0).toISOString().replace('Z', '')
  const NOW = new Date(2026, 10, 9, 15, 0, 0).getTime() // 本地 2026-11-09 15:00

  it('今天 / 昨天 / 具体日期，保持原有顺序', () => {
    const items = [
      { id: 5, created_at: at(2026, 11, 9, 14) },
      { id: 4, created_at: at(2026, 11, 9, 9) },
      { id: 3, created_at: at(2026, 11, 8, 20) },
      { id: 2, created_at: at(2026, 11, 5, 8) },
      { id: 1, created_at: at(2026, 11, 5, 7) },
    ]
    const g = groupByDay(items, NOW)
    expect(g.map((x) => x.label)).toEqual(['今天', '昨天', '2026-11-05'])
    expect(g.map((x) => x.items.map((i) => i.id))).toEqual([[5, 4], [3], [2, 1]])
  })

  it('空列表返回空数组；缺时间的归到「未知时间」', () => {
    expect(groupByDay([], NOW)).toEqual([])
    expect(groupByDay([{ id: 1 }], NOW)[0].label).toBe('未知时间')
  })
})

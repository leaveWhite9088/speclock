import { describe, expect, it } from 'vitest'
import { actionLabel, activityNote, isRead, parseTarget } from './activity.js'

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

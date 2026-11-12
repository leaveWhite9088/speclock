import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ActivityItem from './ActivityItem.vue'
import AttentionSection from './AttentionSection.vue'
import FreshnessBadge from './FreshnessBadge.vue'
import StatCard from './StatCard.vue'
import TraceChain from './TraceChain.vue'
import { _resetChangeSignal, useChangeSignal } from '../composables/useChangeSignal.js'

vi.mock('../api/keyNames.js', () => ({
  useKeyNames: () => ({ keyInfo: () => ({ label: '需求 Agent', role: 'requirements-agent' }) }),
}))

const stubs = { RouterLink: { props: ['to'], template: '<a class="rl" :data-to="typeof to === \'string\' ? to : \'\'"><slot /></a>' } }
const mountWith = (comp, opts = {}) => mount(comp, { global: { stubs }, ...opts })

describe('AttentionSection', () => {
  it('没有内容时只剩一行「标题 0」，不能展开，也没有「全部」链接', () => {
    const w = mountWith(AttentionSection, { props: { title: '等我确认', count: 0, to: '/change-requests' } })
    expect(w.text()).toContain('等我确认')
    expect(w.find('.att-none .count').text()).toBe('0')
    expect(w.find('details').exists()).toBe(false)
    expect(w.find('.more').exists()).toBe(false)
  })

  it('有内容时是可展开的一组：标题、数量、列表和「全部」；open 时默认展开', () => {
    const props = { title: '等我确认', count: 2, tone: 'alert', to: '/change-requests' }
    const slots = { default: '<li class="row">甲</li><li class="row">乙</li>' }
    const w = mountWith(AttentionSection, { props: { ...props, open: true }, slots })
    expect(w.findAll('.row')).toHaveLength(2)
    expect(w.find('summary .count').text()).toBe('2')
    expect(w.find('.more').attributes('data-to')).toBe('/change-requests')
    expect(w.classes()).toContain('tone-alert')
    expect(w.find('details').attributes('open')).toBeDefined()
    expect(mountWith(AttentionSection, { props, slots }).find('details').attributes('open')).toBeUndefined()
  })

  it('加载中和出错时分别显示，互不影响其他块', () => {
    expect(mountWith(AttentionSection, { props: { title: 'x', loading: true } }).text()).toContain('加载中')
    const err = mountWith(AttentionSection, { props: { title: 'x', error: '没有权限：缺少 audit.read' } })
    expect(err.text()).toContain('没有权限：缺少 audit.read')
  })
})

describe('StatCard', () => {
  it('显示数字、名称和进度条（说明放在悬停提示里）；进度被限制在 0–100', () => {
    const w = mountWith(StatCard, { props: { label: '已验收', value: '33%', sub: '1 / 3', percent: 33 } })
    expect(w.text()).toContain('33%')
    expect(w.text()).toContain('已验收')
    expect(w.attributes('title')).toBe('1 / 3')
    expect(w.find('.stat-fill').attributes('style')).toContain('width: 33%')
    expect(mountWith(StatCard, { props: { label: 'x', value: 1, percent: 250 } }).find('.stat-fill').attributes('style')).toContain('width: 100%')
    expect(mountWith(StatCard, { props: { label: 'x', value: 1, percent: -5 } }).find('.stat-fill').attributes('style')).toContain('width: 0%')
  })

  it('没有进度时不画进度条；有 to 时是链接', () => {
    expect(mountWith(StatCard, { props: { label: 'x', value: 1 } }).find('.stat-bar').exists()).toBe(false)
    expect(mountWith(StatCard, { props: { label: 'x', value: 1, to: '/work' } }).find('.rl').exists()).toBe(true)
  })
})

describe('ActivityItem', () => {
  const item = {
    id: 1,
    actor: 'agent-…0001',
    action: 'cr_approve',
    target: 'cr:5',
    detail: { via: 'natural_language', evidence: '同意，按这个来' },
    created_at: new Date().toISOString().replace('Z', ''),
  }

  it('谁、做了什么、对象链接、摘要', () => {
    const w = mountWith(ActivityItem, { props: { item } })
    expect(w.text()).toContain('需求 Agent')
    expect(w.text()).toContain('批准审核单')
    expect(w.find('.rl').attributes('data-to')).toBe('/change-requests/5')
    expect(w.text()).toContain('「同意，按这个来」')
  })

  it('内部整理的「批准」显示为 Agent 自行判定', () => {
    const w = mountWith(ActivityItem, { props: { item: { ...item, detail: { via: 'agent_declared', reason: '只是改名' } } } })
    expect(w.text()).toContain('内部整理生效（Agent 自行判定）')
    expect(w.text()).toContain('只是改名')
  })

  it('expandable 时可以展开看原始详情；默认不展示', () => {
    expect(mountWith(ActivityItem, { props: { item } }).find('details').exists()).toBe(false)
    const w = mountWith(ActivityItem, { props: { item, expandable: true } })
    expect(w.find('details').exists()).toBe(true)
    expect(w.find('pre').text()).toContain('natural_language')
  })

  it('没有链接的对象显示为纯文字', () => {
    const w = mountWith(ActivityItem, { props: { item: { ...item, target: 'index', action: 'pull' } } })
    expect(w.find('.rl').exists()).toBe(false)
    expect(w.text()).toContain('规格索引')
  })
})

describe('FreshnessBadge', () => {
  beforeEach(() => _resetChangeSignal())

  it('还没检查过：检查中', () => {
    expect(mountWith(FreshnessBadge).text()).toContain('检查中')
  })

  it('检查过且没有变化：已是最新', () => {
    useChangeSignal().checkedAt.value = Date.now()
    const w = mountWith(FreshnessBadge)
    expect(w.text()).toContain('已是最新')
    expect(w.classes()).toContain('ok')
  })

  it('刚发现新变化：短暂高亮', () => {
    const s = useChangeSignal()
    s.checkedAt.value = Date.now()
    s.changedAt.value = Date.now()
    const w = mountWith(FreshnessBadge)
    expect(w.text()).toContain('有新变化，已刷新')
    expect(w.classes()).toContain('changed')
  })

  it('没有读活动日志的权限：说明是定时刷新', () => {
    const s = useChangeSignal()
    s.checkedAt.value = Date.now()
    s.mode.value = 'timer'
    expect(mountWith(FreshnessBadge).text()).toContain('定时刷新')
  })

  it('连不上服务：变红并说明原因', () => {
    const s = useChangeSignal()
    s.error.value = '连不上 SpecLock 服务'
    const w = mountWith(FreshnessBadge)
    expect(w.text()).toContain('连不上服务')
    expect(w.classes()).toContain('bad')
    expect(w.attributes('title')).toContain('连不上 SpecLock 服务')
  })
})

describe('TraceChain', () => {
  const commits = [
    {
      id: 1,
      seq: 1,
      note: '补充退款规则',
      covers: ['AC-1', 'AC-2'],
      createdBy: 'agent-…0001',
      createdAt: '2026-11-09T10:00:00',
      ops: [{ op: 'update_block', id: 3 }],
      createdStructure: [{ type: 'capability', typeText: '小业务', id: 11, title: '第二小业务' }],
      meta: [{ type: 'capability', typeText: '小业务', id: 10, title: '订单中心', fields: ['名称'] }],
      blocks: [
        { blockId: 3, title: '退款', version: '1.1.0', prevVersion: '1.0.0', level: 'minor', created: false, executionStatus: 'pending' },
        { blockId: 4, title: '订单内容', version: '1.0.0', prevVersion: '', level: 'initial', created: true, executionStatus: '' },
      ],
      capabilities: [{ id: 10, title: '订单中心', version: '1.2.0', prevVersion: '1.1.0', level: 'minor' }],
      archived: [{ id: 9, title: '旧模块' }],
      restored: [],
      moved: [{ id: 8, title: '搬走的模块' }],
    },
  ]

  it('显示 Commit、覆盖的验收条件、受影响的对象', () => {
    const w = mountWith(TraceChain, { props: { commits } })
    const t = w.text()
    expect(t).toContain('Commit #1')
    expect(t).toContain('补充退款规则')
    expect(t).toContain('AC-1、AC-2')
    expect(t).toContain('新建小业务')
    expect(t).toContain('第二小业务')
    expect(t).toContain('不产生新版本')
    expect(t).toContain('归档')
    expect(t).toContain('旧模块')
    expect(t).toContain('搬动')
    expect(t).toContain('搬走的模块')
  })

  it('更新的模块显示版本变化和执行状态；新建的模块没有「从」', () => {
    const w = mountWith(TraceChain, { props: { commits } })
    const effects = w.findAll('.effect')
    const update = effects.find((e) => e.text().includes('退款'))
    expect(update.text()).toContain('更新')
    expect(update.text()).toContain('→')
    expect(update.text()).toContain('待领取')
    const created = effects.find((e) => e.text().includes('订单内容'))
    expect(created.text()).toContain('新建')
    expect(created.text()).not.toContain('→')
  })

  it('可以展开 / 收起 ops', async () => {
    const w = mountWith(TraceChain, { props: { commits } })
    expect(w.find('.ops-pre').exists()).toBe(false)
    await w.find('button').trigger('click')
    expect(w.find('.ops-pre').text()).toContain('update_block')
    await w.find('button').trigger('click')
    expect(w.find('.ops-pre').exists()).toBe(false)
  })
})

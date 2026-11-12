import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AsyncState from './AsyncState.vue'
import CRStatusBadge from './CRStatusBadge.vue'
import ErrorState from './ErrorState.vue'
import ExecStatusBadge from './ExecStatusBadge.vue'
import KeyChip from './KeyChip.vue'
import PageHeader from './PageHeader.vue'
import TimeAgo from './TimeAgo.vue'

vi.mock('../api/keyNames.js', () => ({
  useKeyNames: () => ({
    keyInfo: (hint) =>
      hint === 'agent-…0001'
        ? { label: '后端执行 Agent', role: 'executor-agent' }
        : hint === 'human-…admin'
          ? { label: 'admin', role: 'admin' }
          : { label: '', role: '' },
  }),
}))

describe('AsyncState', () => {
  const content = '<p class="body">内容</p>'

  it('加载中只显示加载占位', () => {
    const w = mount(AsyncState, { props: { loading: true }, slots: { default: content } })
    expect(w.text()).toContain('加载中')
    expect(w.find('.body').exists()).toBe(false)
  })

  it('出错时显示原因，点重试发出事件', async () => {
    const w = mount(AsyncState, { props: { error: '没有权限：缺少 key.manage' }, slots: { default: content } })
    expect(w.text()).toContain('没有权限：缺少 key.manage')
    await w.find('button').trigger('click')
    expect(w.emitted('retry')).toHaveLength(1)
    expect(w.find('.body').exists()).toBe(false)
  })

  it('为空时显示引导文案', () => {
    const w = mount(AsyncState, {
      props: { empty: true, emptyTitle: '还没有审核单', emptyText: '让需求 Agent 整理一个' },
      slots: { default: content },
    })
    expect(w.text()).toContain('还没有审核单')
    expect(w.text()).toContain('让需求 Agent 整理一个')
    expect(w.find('.body').exists()).toBe(false)
  })

  it('空状态可以用插槽自定义', () => {
    const w = mount(AsyncState, {
      props: { empty: true },
      slots: { default: content, empty: '<p class="mine">自定义</p>' },
    })
    expect(w.find('.mine').exists()).toBe(true)
  })

  it('正常时显示内容；加载中优先于出错', () => {
    expect(mount(AsyncState, { slots: { default: content } }).find('.body').exists()).toBe(true)
    const both = mount(AsyncState, { props: { loading: true, error: 'x' }, slots: { default: content } })
    expect(both.text()).toContain('加载中')
    expect(both.text()).not.toContain('x')
  })
})

describe('ErrorState', () => {
  it('不可重试时不显示重试按钮；多行文案保留换行', () => {
    const w = mount(ErrorState, { props: { message: '第一行\n· 第二行', retryable: false } })
    expect(w.find('button').exists()).toBe(false)
    expect(w.text()).toContain('· 第二行')
  })
})

describe('状态徽标', () => {
  it('审核单状态显示中文，未知状态原样显示', () => {
    expect(mount(CRStatusBadge, { props: { status: 'pending_review' } }).text()).toBe('待确认')
    expect(mount(CRStatusBadge, { props: { status: 'weird' } }).text()).toBe('weird')
  })

  it('执行状态显示中文，空状态什么都不渲染', () => {
    expect(mount(ExecStatusBadge, { props: { status: 'implemented' } }).text()).toBe('待验收')
    expect(mount(ExecStatusBadge, { props: { status: '' } }).html()).toBe('<!--v-if-->')
  })
})

describe('PageHeader', () => {
  it('只有标题和操作插槽，不再有英文小标题和说明文字', () => {
    const w = mount(PageHeader, {
      props: { title: '待办' },
      slots: { actions: '<button class="act">筛选</button>' },
    })
    expect(w.find('h1').text()).toBe('待办')
    expect(w.find('.page-eyebrow').exists()).toBe(false)
    expect(w.find('.page-desc').exists()).toBe(false)
    expect(w.find('.act').exists()).toBe(true)
  })
})

describe('KeyChip', () => {
  it('查得到时显示备注和角色，悬停显示 hint', () => {
    const w = mount(KeyChip, { props: { hint: 'agent-…0001' } })
    expect(w.text()).toContain('后端执行 Agent')
    expect(w.text()).toContain('executor-agent')
    expect(w.attributes('title')).toBe('agent-…0001')
  })

  it('备注和角色相同（如 admin）时不重复显示', () => {
    const w = mount(KeyChip, { props: { hint: 'human-…admin' } })
    expect(w.text()).toBe('admin')
  })

  it('查不到时回退显示 hint；空值显示破折号', () => {
    expect(mount(KeyChip, { props: { hint: 'human-…ffff' } }).text()).toBe('human-…ffff')
    expect(mount(KeyChip, { props: { hint: '' } }).text()).toBe('—')
  })
})

describe('TimeAgo', () => {
  it('显示相对时间，悬停显示完整时间', () => {
    const iso = new Date(Date.now() - 5 * 60 * 1000).toISOString().replace('Z', '')
    const w = mount(TimeAgo, { props: { value: iso } })
    expect(w.text()).toBe('5 分钟前')
    expect(w.attributes('title')).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)
  })

  it('空值显示破折号', () => {
    expect(mount(TimeAgo, { props: { value: '' } }).text()).toBe('-')
  })
})

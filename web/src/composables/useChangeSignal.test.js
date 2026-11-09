import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'

vi.mock('../api/resources.js', () => ({ resources: { activity: vi.fn() } }))
vi.mock('../api/client.js', () => ({ getKey: vi.fn(() => 'human-key') }))

import { getKey } from '../api/client.js'
import { resources } from '../api/resources.js'
import { FALLBACK_TICKS, _resetChangeSignal, checkOnce, useChangeSignal } from './useChangeSignal.js'
import { useAutoRefresh } from './useAutoRefresh.js'

const rows = (id) => (id === null ? [] : [{ id }])

describe('useChangeSignal', () => {
  beforeEach(() => {
    _resetChangeSignal()
    resources.activity.mockReset()
    getKey.mockReturnValue('human-key')
  })

  it('第一次检查只记录基线，不算变化', async () => {
    resources.activity.mockResolvedValue(rows(10))
    await checkOnce()
    const s = useChangeSignal()
    expect(s.version.value).toBe(0)
    expect(s.checkedAt.value).toBeTruthy()
  })

  it('最新活动的 id 没变：不通知；变了：version 加一，并记下时间', async () => {
    const s = useChangeSignal()
    resources.activity.mockResolvedValue(rows(10))
    await checkOnce()
    await checkOnce()
    expect(s.version.value).toBe(0)
    resources.activity.mockResolvedValue(rows(11))
    await checkOnce()
    expect(s.version.value).toBe(1)
    expect(s.changedAt.value).toBeTruthy()
  })

  it('请求里排除了读取，只取一条', async () => {
    resources.activity.mockResolvedValue(rows(1))
    await checkOnce()
    expect(resources.activity).toHaveBeenCalledWith({ limit: 1, exclude_action: 'pull' })
  })

  it('空日志视为 0；之后出现第一条活动也算变化', async () => {
    const s = useChangeSignal()
    resources.activity.mockResolvedValue(rows(null))
    await checkOnce()
    resources.activity.mockResolvedValue(rows(1))
    await checkOnce()
    expect(s.version.value).toBe(1)
  })

  it('没有 audit.read 权限（403）：退化为定时刷新，每 N 次检查通知一次', async () => {
    const s = useChangeSignal()
    resources.activity.mockRejectedValue({ status: 403, detail: '缺少权限' })
    for (let i = 0; i < FALLBACK_TICKS - 1; i++) await checkOnce()
    expect(s.mode.value).toBe('timer')
    expect(s.version.value).toBe(0)
    await checkOnce()
    expect(s.version.value).toBe(1)
    expect(s.error.value).toBe('')
  })

  it('网络错误：记录错误，不通知；恢复后清掉错误', async () => {
    const s = useChangeSignal()
    resources.activity.mockRejectedValue(new TypeError('offline'))
    await checkOnce()
    expect(s.error.value).toContain('连不上')
    expect(s.version.value).toBe(0)
    resources.activity.mockResolvedValue(rows(1))
    await checkOnce()
    expect(s.error.value).toBe('')
  })

  it('没有登录时不发请求', async () => {
    getKey.mockReturnValue(null)
    await checkOnce()
    expect(resources.activity).not.toHaveBeenCalled()
  })
})

describe('useAutoRefresh', () => {
  beforeEach(() => {
    _resetChangeSignal()
    resources.activity.mockReset()
    getKey.mockReturnValue('human-key')
  })
  afterEach(() => vi.clearAllMocks())

  it('变化信号一来就静默刷新', async () => {
    const reload = vi.fn()
    mount(
      defineComponent({
        setup() {
          useAutoRefresh(reload)
          return () => h('div')
        },
      }),
    )
    resources.activity.mockResolvedValue(rows(1))
    await checkOnce()
    await nextTick()
    expect(reload).not.toHaveBeenCalled()
    resources.activity.mockResolvedValue(rows(2))
    await checkOnce()
    await nextTick()
    expect(reload).toHaveBeenCalledTimes(1)
    expect(reload).toHaveBeenCalledWith({ silent: true })
  })
})

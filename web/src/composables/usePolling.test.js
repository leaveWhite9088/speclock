import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'
import { usePolling } from './usePolling.js'

function host(setup) {
  let result
  const wrapper = mount(
    defineComponent({
      setup() {
        result = setup()
        return () => h('div')
      },
    }),
  )
  return { wrapper, result }
}

function setHidden(value) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => value })
  document.dispatchEvent(new Event('visibilitychange'))
}

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setHidden(false)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('按间隔执行，卸载后停止', async () => {
    const fn = vi.fn()
    const { wrapper } = host(() => usePolling(fn, 1000))
    await vi.advanceTimersByTimeAsync(3100)
    expect(fn).toHaveBeenCalledTimes(3)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(3000)
    expect(fn).toHaveBeenCalledTimes(3)
  })

  it('immediate 时挂载就执行一次', async () => {
    const fn = vi.fn()
    host(() => usePolling(fn, 1000, { immediate: true }))
    await vi.advanceTimersByTimeAsync(0)
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('页面不可见时暂停，重新可见时立刻补一次', async () => {
    const fn = vi.fn()
    host(() => usePolling(fn, 1000))
    setHidden(true)
    await vi.advanceTimersByTimeAsync(5000)
    expect(fn).toHaveBeenCalledTimes(0)
    setHidden(false)
    await vi.advanceTimersByTimeAsync(0)
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('上一次没结束就不会开始下一次', async () => {
    let release
    const fn = vi.fn(() => new Promise((res) => (release = res)))
    host(() => usePolling(fn, 1000))
    await vi.advanceTimersByTimeAsync(5000)
    expect(fn).toHaveBeenCalledTimes(1)
    release()
    await vi.advanceTimersByTimeAsync(1000)
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('pause / resume', async () => {
    const fn = vi.fn()
    const { result } = host(() => usePolling(fn, 1000))
    result.pause()
    await vi.advanceTimersByTimeAsync(3000)
    expect(fn).toHaveBeenCalledTimes(0)
    result.resume()
    await vi.advanceTimersByTimeAsync(1100)
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('fn 抛错不会让轮询停掉', async () => {
    const fn = vi.fn().mockRejectedValue(new Error('boom'))
    host(() => usePolling(fn, 1000))
    await vi.advanceTimersByTimeAsync(3100)
    expect(fn).toHaveBeenCalledTimes(3)
  })
})

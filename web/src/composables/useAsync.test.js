import { describe, expect, it } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { useAsync } from './useAsync.js'

function deferred() {
  let resolve
  const promise = new Promise((res) => {
    resolve = res
  })
  return { promise, resolve }
}

/** 在组件里跑 composable（它依赖 onMounted） */
function host(setup) {
  let result
  mount(
    defineComponent({
      setup() {
        result = setup()
        return () => h('div')
      },
    }),
  )
  return result
}

const tick = async () => {
  await Promise.resolve()
  await nextTick()
  await Promise.resolve()
}

describe('useAsync', () => {
  it('挂载后自动取数：loading → 有数据', async () => {
    const d = deferred()
    const result = host(() => useAsync(() => d.promise))
    expect(result.loading.value).toBe(true)
    d.resolve([1, 2])
    await tick()
    expect(result.loading.value).toBe(false)
    expect(result.data.value).toEqual([1, 2])
    expect(result.error.value).toBe('')
  })

  it('出错时给出中文文案，并可以重试', async () => {
    let calls = 0
    const result = host(() =>
      useAsync(async () => {
        calls += 1
        if (calls === 1) throw { status: 403, detail: '缺少权限：key.manage' }
        return 'ok'
      }),
    )
    await tick()
    expect(result.error.value).toBe('没有权限：缺少权限：key.manage')
    expect(result.loading.value).toBe(false)
    await result.reload()
    expect(result.error.value).toBe('')
    expect(result.data.value).toBe('ok')
  })

  it('连续触发时只采用最后一次的结果（慢请求不会覆盖新结果）', async () => {
    const first = deferred()
    const second = deferred()
    const queue = [first, second]
    const result = host(() => useAsync(() => queue.shift().promise))
    const again = result.reload() // 第二次请求
    second.resolve('新')
    await again
    first.resolve('旧') // 第一次请求更晚返回
    await tick()
    expect(result.data.value).toBe('新')
  })

  it('静默刷新：不闪「加载中」，失败时保留旧数据且不报错', async () => {
    let n = 0
    const result = host(() =>
      useAsync(async () => {
        n += 1
        if (n === 3) throw new TypeError('offline')
        return n
      }),
    )
    await tick()
    expect(result.data.value).toBe(1)
    const p = result.reload({ silent: true })
    expect(result.loading.value).toBe(false)
    await p
    expect(result.data.value).toBe(2)
    await result.reload({ silent: true }) // 第 3 次失败
    expect(result.data.value).toBe(2)
    expect(result.error.value).toBe('')
  })

  it('监听的 ref 变化时自动重新取数', async () => {
    const status = ref('a')
    const seen = []
    host(() =>
      useAsync(
        async () => {
          seen.push(status.value)
          return status.value
        },
        { watch: [status] },
      ),
    )
    await tick()
    status.value = 'b'
    await tick()
    expect(seen).toEqual(['a', 'b'])
  })

  it('silentWatch：监听到变化时静默重新取数（不闪加载中）', async () => {
    const status = ref('a')
    const result = host(() => useAsync(async () => status.value, { watch: [status], silentWatch: true }))
    await tick()
    status.value = 'b'
    await nextTick()
    expect(result.loading.value).toBe(false)
    await tick()
    expect(result.data.value).toBe('b')
  })

  it('immediate:false 时不自动取数', async () => {
    let called = false
    host(() => useAsync(async () => (called = true), { immediate: false }))
    await tick()
    expect(called).toBe(false)
  })
})

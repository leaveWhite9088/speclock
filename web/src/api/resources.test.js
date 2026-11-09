import { afterEach, describe, expect, it, vi } from 'vitest'
import { resources } from './resources.js'

function stubFetch() {
  const fetchMock = vi.fn().mockImplementation(async () => new Response('[]', { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  return () => fetchMock.mock.calls.at(-1)[0]
}

describe('resources', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('空的筛选参数不进查询串', async () => {
    const lastUrl = stubFetch()
    await resources.crs.list('')
    expect(lastUrl()).toBe('/api/v1/change-requests')
    await resources.crs.list('pending_review')
    expect(lastUrl()).toBe('/api/v1/change-requests?status=pending_review')
    await resources.work.list()
    expect(lastUrl()).toBe('/api/v1/work')
    await resources.work.list({ status: 'blocked', block_id: 3 })
    expect(lastUrl()).toBe('/api/v1/work?status=blocked&block_id=3')
  })

  it('查询参数按名字拼接', async () => {
    const lastUrl = stubFetch()
    await resources.blocks.diff(5, { from: '1.0.0', to: '1.1.0' })
    expect(lastUrl()).toBe('/api/v1/blocks/5/diff?from=1.0.0&to=1.1.0')
    await resources.activity({ limit: 50, actor_prefix: 'agent' })
    expect(lastUrl()).toBe('/api/v1/activity?limit=50&actor_prefix=agent')
  })

  it('各资源指向正确的路径', async () => {
    const lastUrl = stubFetch()
    const cases = [
      [() => resources.tree(), '/api/v1/tree'],
      [() => resources.archive(), '/api/v1/archive'],
      [() => resources.crs.get(7), '/api/v1/change-requests/7'],
      [() => resources.work.get(2), '/api/v1/work/2'],
      [() => resources.blocks.versions(4), '/api/v1/blocks/4/versions'],
      [() => resources.blocks.version(4, '1.2.0'), '/api/v1/blocks/4/versions/1.2.0'],
      [() => resources.capabilities.versions(6), '/api/v1/capabilities/6/versions'],
      [() => resources.keys(), '/api/v1/keys'],
      [() => resources.roles(), '/api/v1/roles'],
    ]
    for (const [call, url] of cases) {
      await call()
      expect(lastUrl()).toBe(url)
    }
  })
})

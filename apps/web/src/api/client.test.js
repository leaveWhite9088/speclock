import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, clearKey, getKey, keyHint, setKey } from './client.js'

function jsonResponse(status, body) {
  return new Response(body === undefined ? '' : JSON.stringify(body), { status })
}

describe('api client', () => {
  beforeEach(() => {
    clearKey()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('已有密钥时直接带上，baseURL 是 /api/v1', async () => {
    setKey('human-abc123')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await api.get('/tree')).toEqual({ ok: true })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/tree')
    expect(init.headers['X-API-Key']).toBe('human-abc123')
  })

  it('没有密钥时先从 /web/session 自动取一把，再带着它请求', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { key: 'human-web-1111' }))
      .mockResolvedValueOnce(jsonResponse(200, { ok: 1 }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await api.get('/x')).toEqual({ ok: 1 })
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/web/session')
    expect(fetchMock.mock.calls[1][1].headers['X-API-Key']).toBe('human-web-1111')
    expect(getKey()).toBe('human-web-1111')
  })

  it('服务端要求指明项目时，错误里带 code（网页据此显示项目选择页）', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(422, { detail: '有多个项目', code: 'web_project_required' })))
    await expect(api.get('/x')).rejects.toEqual({ status: 422, detail: '有多个项目', code: 'web_project_required' })
  })

  it('取不到只读密钥时抛出服务端的说明', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(404, { detail: '没有网页用的 key' })))
    await expect(api.get('/x')).rejects.toEqual({ status: 404, detail: '没有网页用的 key' })
  })

  it('POST 带 JSON', async () => {
    setKey('human-k')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal('fetch', fetchMock)
    await api.post('/x', { a: 1 })
    const init = fetchMock.mock.calls[0][1]
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe('{"a":1}')
  })

  it('非 2xx 抛出 { status, detail }，detail 取后端的说明', async () => {
    setKey('human-k')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(409, { detail: '冲突了' })))
    await expect(api.get('/x')).rejects.toEqual({ status: 409, detail: '冲突了' })
  })

  it('后端没给说明时用 HTTP 状态兜底', async () => {
    setKey('human-k')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(500)))
    await expect(api.get('/x')).rejects.toMatchObject({ status: 500 })
  })

  it('401：重新取一把密钥并重试一次', async () => {
    setKey('human-old')
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'unknown API key' }))
      .mockResolvedValueOnce(jsonResponse(200, { key: 'human-new' }))
      .mockResolvedValueOnce(jsonResponse(200, { ok: 2 }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await api.get('/x')).toEqual({ ok: 2 })
    expect(getKey()).toBe('human-new')
  })

  it('401 重试后还是 401：抛错，不循环', async () => {
    setKey('human-old')
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(401, {}))
        .mockResolvedValueOnce(jsonResponse(200, { key: 'human-new' }))
        .mockResolvedValueOnce(jsonResponse(401, {})),
    )
    await expect(api.get('/x')).rejects.toMatchObject({ status: 401 })
  })

  it('keyHint 与后端的脱敏形式一致', () => {
    expect(keyHint('human-1234567890abcdef')).toBe('human-…cdef')
    expect(keyHint('')).toBe('')
  })
})

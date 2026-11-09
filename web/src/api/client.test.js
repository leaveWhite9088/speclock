import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, clearKey, getKey, keyHint, setKey } from './client.js'

function jsonResponse(status, body) {
  return new Response(body === undefined ? '' : JSON.stringify(body), { status })
}

describe('api client', () => {
  beforeEach(() => {
    localStorage.clear()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('带上本地保存的密钥，baseURL 是 /api/v1', async () => {
    setKey('human-abc123')
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await api.get('/tree')).toEqual({ ok: true })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/tree')
    expect(init.headers['X-API-Key']).toBe('human-abc123')
  })

  it('没有密钥时不带 header；POST 带 JSON', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}))
    vi.stubGlobal('fetch', fetchMock)
    await api.post('/x', { a: 1 })
    const init = fetchMock.mock.calls[0][1]
    expect(init.headers['X-API-Key']).toBeUndefined()
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe('{"a":1}')
  })

  it('非 2xx 抛出 { status, detail }，detail 取后端的说明', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(409, { detail: '冲突了' })))
    await expect(api.get('/x')).rejects.toEqual({ status: 409, detail: '冲突了' })
  })

  it('后端没给说明时用 HTTP 状态兜底', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(500)))
    await expect(api.get('/x')).rejects.toMatchObject({ status: 500 })
  })

  it('401：清掉本地密钥并抛错', async () => {
    setKey('human-bad')
    vi.stubGlobal('location', { pathname: '/login', assign: vi.fn() })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, { detail: 'unknown API key' })))
    await expect(api.get('/x')).rejects.toMatchObject({ status: 401 })
    expect(getKey()).toBeNull()
  })

  it('keyHint 与后端的脱敏形式一致', () => {
    expect(keyHint('human-1234567890abcdef')).toBe('human-…cdef')
    expect(keyHint('')).toBe('')
    clearKey()
  })
})

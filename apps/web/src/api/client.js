/**
 * SpecLock API 客户端。
 *
 * 网页不用登录：第一次请求前从 /api/v1/web/session 自动拿到一把**只读** key
 * （服务端只发给本机同源的网页），放在内存里，之后每个请求带 X-API-Key。
 * key 失效（比如被吊销、库换了）时重新取一次再重试；还不行就抛错。
 *
 * 非 2xx 一律抛出 { status, detail } 形状的错误对象。
 *
 * 用法：
 *   const projects = await api.get('/projects')
 */

const BASE_URL = '/api/v1'

let currentKey = ''

export function getKey() {
  return currentKey
}

export function setKey(key) {
  currentKey = key || ''
}

export function clearKey() {
  currentKey = ''
}

/** 展示用脱敏形式，与后端 auth.key_hint 保持一致：human-…1a2b */
export function keyHint(key = currentKey) {
  if (!key) return ''
  const prefix = key.split('-', 1)[0]
  return `${prefix}-…${key.slice(-4)}`
}

async function readBody(res) {
  const text = await res.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function errorOf(res, data) {
  const detail =
    (data && typeof data === 'object' && data.detail) ||
    (typeof data === 'string' ? data : null) ||
    `请求失败（HTTP ${res.status}）`
  return { status: res.status, detail }
}

/** 没有 key 就向本机服务要一把只读 key；已经有了什么都不做。 */
export async function ensureSession() {
  if (currentKey) return
  let res
  try {
    res = await fetch(`${BASE_URL}/web/session`)
  } catch {
    throw { status: 0, detail: '连不上 SpecLock 服务，请确认 speclock serve 在运行' }
  }
  const data = await readBody(res)
  if (!res.ok) throw errorOf(res, data)
  setKey(data.key)
}

async function send(path, { method, body, headers }) {
  await ensureSession()
  return fetch(`${BASE_URL}${path}`, {
    method,
    headers: {
      'X-API-Key': currentKey,
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
}

async function request(path, { method = 'GET', body, headers = {} } = {}) {
  let res = await send(path, { method, body, headers })
  if (res.status === 401) {
    // key 失效：重新要一把，只重试一次
    clearKey()
    await ensureSession()
    res = await send(path, { method, body, headers })
    if (res.status === 401) {
      throw { status: 401, detail: '网页用的只读 key 无效，请重启 speclock serve' }
    }
  }
  const data = await readBody(res)
  if (!res.ok) throw errorOf(res, data)
  return data
}

export const api = {
  get: (path, options) => request(path, { ...options, method: 'GET' }),
  post: (path, body, options) => request(path, { ...options, method: 'POST', body }),
  put: (path, body, options) => request(path, { ...options, method: 'PUT', body }),
  patch: (path, body, options) => request(path, { ...options, method: 'PATCH', body }),
  delete: (path, options) => request(path, { ...options, method: 'DELETE' }),
}

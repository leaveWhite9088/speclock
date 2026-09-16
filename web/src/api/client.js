/**
 * SpecLock API 客户端。
 *
 * - baseURL 为相对路径 /api/v1（开发时由 vite proxy 转发到 127.0.0.1:8000）
 * - 自动从 localStorage 读取密钥并带 X-API-Key header
 * - 401：清除本地密钥并跳转 /login（说明密钥已失效或被吊销）
 * - 非 2xx 一律抛出 { status, detail } 形状的错误对象
 *
 * 用法：
 *   import { api } from '@/api/client.js'   // 或相对路径 ../api/client.js
 *   const projects = await api.get('/projects')
 *   await api.post('/blocks', { ... })
 */

const BASE_URL = '/api/v1'
const STORAGE_KEY = 'speclock_key'

export function getKey() {
  return localStorage.getItem(STORAGE_KEY)
}

export function setKey(key) {
  localStorage.setItem(STORAGE_KEY, key)
}

export function clearKey() {
  localStorage.removeItem(STORAGE_KEY)
}

/** 展示用脱敏形式，与后端 auth.key_hint 保持一致：human-…1a2b */
export function keyHint(key = getKey()) {
  if (!key) return ''
  const prefix = key.split('-', 1)[0]
  return `${prefix}-…${key.slice(-4)}`
}

async function request(path, { method = 'GET', body, headers = {} } = {}) {
  const key = getKey()
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: {
      ...(key ? { 'X-API-Key': key } : {}),
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (res.status === 401) {
    clearKey()
    // 守卫之外唯一的强制登出点：密钥无效时回到登录页
    if (window.location.pathname !== '/login') {
      window.location.assign('/login')
    }
    throw { status: 401, detail: '密钥无效或已被吊销，请重新登录' }
  }

  let data = null
  const text = await res.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }

  if (!res.ok) {
    const detail =
      (data && typeof data === 'object' && data.detail) ||
      (typeof data === 'string' ? data : null) ||
      `请求失败（HTTP ${res.status}）`
    throw { status: res.status, detail }
  }

  return data
}

export const api = {
  get: (path, options) => request(path, { ...options, method: 'GET' }),
  post: (path, body, options) =>
    request(path, { ...options, method: 'POST', body }),
  put: (path, body, options) =>
    request(path, { ...options, method: 'PUT', body }),
  patch: (path, body, options) =>
    request(path, { ...options, method: 'PATCH', body }),
  delete: (path, options) => request(path, { ...options, method: 'DELETE' }),
}

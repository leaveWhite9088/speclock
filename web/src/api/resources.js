/**
 * 按资源封装的请求：页面不再手拼 URL。只负责请求，不做展示相关的整形。
 * 对应后端的公开 REST 接口（/api/v1）。
 */
import { api } from './client.js'

function qs(params = {}) {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
  return parts.length ? `?${parts.join('&')}` : ''
}

export const resources = {
  /** 项目 → 大业务 → 小业务 → 模块 的完整树 */
  tree: () => api.get('/tree'),
  archive: () => api.get('/archive'),
  projects: () => api.get('/projects'),

  crs: {
    list: (status) => api.get(`/change-requests${qs({ status })}`),
    get: (id) => api.get(`/change-requests/${id}`),
  },

  work: {
    list: (params) => api.get(`/work${qs(params)}`),
    get: (id) => api.get(`/work/${id}`),
  },

  blocks: {
    versions: (id) => api.get(`/blocks/${id}/versions`),
    version: (id, version) => api.get(`/blocks/${id}/versions/${version}`),
    diff: (id, params) => api.get(`/blocks/${id}/diff${qs(params)}`),
  },

  capabilities: {
    versions: (id) => api.get(`/capabilities/${id}/versions`),
  },

  /** 审计日志（新的在前） */
  activity: (params) => api.get(`/activity${qs(params)}`),
  keys: () => api.get('/keys'),
  roles: () => api.get('/roles'),
}

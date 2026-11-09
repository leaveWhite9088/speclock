/**
 * 把请求错误转成给人看的话。api/client.js 抛出 { status, detail }；
 * 网络不通时 fetch 抛 TypeError（没有 status）。
 */

export const NETWORK_ERROR = '连不上 SpecLock 服务，请确认服务正在运行（默认 http://127.0.0.1:8000）。'

function detailText(detail) {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    // 后端的结构化错误：{ error, missing: [...] } / { error, problems: [...] } …
    const lines = []
    if (detail.error) lines.push(detail.error)
    for (const key of ['missing', 'problems']) {
      if (Array.isArray(detail[key])) lines.push(...detail[key].map((x) => `· ${x}`))
    }
    if (lines.length) return lines.join('\n')
    return JSON.stringify(detail, null, 2)
  }
  return ''
}

export function errText(e) {
  if (!e) return '请求失败，请稍后重试。'
  if (e instanceof TypeError || (e.status == null && e.detail == null)) return NETWORK_ERROR
  const text = detailText(e.detail ?? e)
  switch (e.status) {
    case 401:
      return text || '密钥无效或已失效，请重新登录。'
    case 403:
      return `没有权限：${text || '当前密钥的角色不允许这样做。'}`
    case 404:
      return text && !/not found/i.test(text) ? text : '没有找到这个内容（可能不存在，或当前密钥无权访问它所在的项目）。'
    default:
      return text || `请求失败（HTTP ${e.status}）。`
  }
}

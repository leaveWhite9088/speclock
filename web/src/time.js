/**
 * 时间工具：后端时间戳（created_at / published_at 等）由 UTC 生成，
 * 序列化为无时区后缀的 ISO 字符串（如 "2026-09-26T04:32:26.766346"）。
 * 统一按 UTC 解析，再按浏览器本地时区显示。
 */

/** 解析后端 ISO 时间字符串为 Date；无时区后缀按 UTC 处理；空值/非法值返回 null */
export function parseTs(iso) {
  if (!iso) return null
  const s = String(iso)
  const d = /([zZ]|[+-]\d{2}:?\d{2})$/.test(s) ? new Date(s) : new Date(s + 'Z')
  return Number.isNaN(d.getTime()) ? null : d
}

/** 格式化为本地时间 YYYY-MM-DD HH:mm:ss（24 小时制）；空值/非法值返回 '-' */
export function fmtTime(iso) {
  const d = parseTs(iso)
  if (!d) return '-'
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

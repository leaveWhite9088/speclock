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

/**
 * 相对时间：刚刚 / 5 分钟前 / 3 小时前 / 2 天前；超过 30 天显示日期。
 * now 可注入，方便测试。空值 / 非法值返回 '-'。
 */
export function fmtAgo(iso, now = Date.now()) {
  const d = parseTs(iso)
  if (!d) return '-'
  const sec = Math.round((now - d.getTime()) / 1000)
  if (sec < 0) return '刚刚'
  if (sec < 45) return '刚刚'
  const min = Math.round(sec / 60)
  if (min < 60) return `${min} 分钟前`
  const hour = Math.round(min / 60)
  if (hour < 24) return `${hour} 小时前`
  const day = Math.round(hour / 24)
  if (day <= 30) return `${day} 天前`
  return fmtTime(iso).slice(0, 10)
}

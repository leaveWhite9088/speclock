import { describe, expect, it } from 'vitest'
import { fmtAgo, parseTs } from './time.js'

const NOW = Date.parse('2026-11-09T12:00:00Z')

describe('parseTs', () => {
  it('无时区后缀按 UTC 解析', () => {
    expect(parseTs('2026-11-09T12:00:00').toISOString()).toBe('2026-11-09T12:00:00.000Z')
  })

  it('带时区后缀的原样解析', () => {
    expect(parseTs('2026-11-09T20:00:00+08:00').toISOString()).toBe('2026-11-09T12:00:00.000Z')
    expect(parseTs('2026-11-09T12:00:00Z').toISOString()).toBe('2026-11-09T12:00:00.000Z')
  })

  it('空值与非法值返回 null', () => {
    expect(parseTs('')).toBeNull()
    expect(parseTs(null)).toBeNull()
    expect(parseTs('不是时间')).toBeNull()
  })
})

describe('fmtAgo', () => {
  const ago = (sec) => new Date(NOW - sec * 1000).toISOString().replace('Z', '')

  it('一分钟内算刚刚；未来的时间也显示刚刚', () => {
    expect(fmtAgo(ago(5), NOW)).toBe('刚刚')
    expect(fmtAgo(ago(-30), NOW)).toBe('刚刚')
  })

  it('分钟 / 小时 / 天', () => {
    expect(fmtAgo(ago(5 * 60), NOW)).toBe('5 分钟前')
    expect(fmtAgo(ago(3 * 3600), NOW)).toBe('3 小时前')
    expect(fmtAgo(ago(2 * 86400), NOW)).toBe('2 天前')
  })

  it('超过 30 天显示日期', () => {
    expect(fmtAgo(ago(40 * 86400), NOW)).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })

  it('空值显示破折号', () => {
    expect(fmtAgo('', NOW)).toBe('-')
  })
})

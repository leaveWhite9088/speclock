import { describe, expect, it } from 'vitest'
import { withoutEmbed } from './embed.js'

describe('embed', () => {
  it('报告给外层页面的路径去掉 embed 参数，其他参数保留', () => {
    expect(withoutEmbed('/blocks/3?embed=1')).toBe('/blocks/3')
    expect(withoutEmbed('/search?q=退款&embed=1')).toBe('/search?q=%E9%80%80%E6%AC%BE')
    expect(withoutEmbed('/?embed=1#x')).toBe('/#x')
    expect(withoutEmbed('/tree')).toBe('/tree')
  })
})

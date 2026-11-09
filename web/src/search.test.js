import { describe, expect, it } from 'vitest'
import { groupHits, highlightSegments, hitLink, hitPath } from './search.js'

describe('highlightSegments', () => {
  it('切出命中的部分，保留原文大小写', () => {
    expect(highlightSegments('GET /api/Daily-Report', 'daily')).toEqual([
      { text: 'GET /api/', hit: false },
      { text: 'Daily', hit: true },
      { text: '-Report', hit: false },
    ])
  })

  it('多处命中', () => {
    const segs = highlightSegments('退款含运费，退款不含手续费', '退款')
    expect(segs.filter((s) => s.hit)).toHaveLength(2)
    expect(segs.map((s) => s.text).join('')).toBe('退款含运费，退款不含手续费')
  })

  it('没有关键词或没有命中时原文返回', () => {
    expect(highlightSegments('abc', '')).toEqual([{ text: 'abc', hit: false }])
    expect(highlightSegments('abc', 'x')).toEqual([{ text: 'abc', hit: false }])
    expect(highlightSegments(null, 'x')).toEqual([{ text: '', hit: false }])
  })

  it('关键词在开头和结尾', () => {
    expect(highlightSegments('退款', '退款')).toEqual([{ text: '退款', hit: true }])
  })
})

describe('groupHits', () => {
  const hits = [
    { type: 'cr', cr_id: 1 },
    { type: 'rule', item_id: 'R-1' },
    { type: 'module' },
    { type: 'rule', item_id: 'R-2' },
  ]

  it('按固定顺序分组，空组不出现', () => {
    const g = groupHits(hits)
    expect(g.map((x) => x.type)).toEqual(['module', 'rule', 'cr'])
    expect(g[1].hits.map((h) => h.item_id)).toEqual(['R-1', 'R-2'])
    expect(g[0].label).toBe('模块')
  })

  it('没有命中时返回空数组', () => {
    expect(groupHits([])).toEqual([])
    expect(groupHits()).toEqual([])
  })
})

describe('hitLink / hitPath', () => {
  const base = { block_id: 3, version: '1.2.0', business: '运营', capability_title: '经营日报', block_title: '数据采集' }

  it('规则和验收条件直达对应的行，其余到模块页', () => {
    expect(hitLink({ ...base, type: 'rule', item_id: 'R-2' })).toBe('/blocks/3?version=1.2.0#item-R-2')
    expect(hitLink({ ...base, type: 'acceptance', item_id: 'AC-1' })).toBe('/blocks/3?version=1.2.0#item-AC-1')
    expect(hitLink({ ...base, type: 'rule', item_id: '' })).toBe('/blocks/3?version=1.2.0')
    expect(hitLink({ ...base, type: 'api', item_id: 'GET /x' })).toBe('/blocks/3?version=1.2.0')
    expect(hitLink({ ...base, type: 'module' })).toBe('/blocks/3?version=1.2.0')
  })

  it('审核单到审核单页', () => {
    expect(hitLink({ type: 'cr', cr_id: 9 })).toBe('/change-requests/9')
  })

  it('位置说明', () => {
    expect(hitPath({ ...base, type: 'rule' })).toBe('运营 / 经营日报 / 数据采集 v1.2.0')
    expect(hitPath({ type: 'cr', cr_id: 9 })).toBe('审核单 #9')
  })
})

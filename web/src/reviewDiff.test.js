import { describe, expect, it } from 'vitest'
import { changeWhere, charDiff } from './reviewDiff.js'

const join = (segs, kinds) => segs.filter((s) => kinds.includes(s.kind)).map((s) => s.text).join('')

describe('charDiff', () => {
  it('只标出被改的那一小段', () => {
    const segs = charDiff('合计（不含退款）', '合计(不含退款)')
    expect(segs.filter((s) => s.kind !== 'same').map((s) => [s.kind, s.text])).toEqual([
      ['del', '（不含退款）'],
      ['add', '(不含退款)'],
    ])
  })

  it('两边拼回去分别是旧文字和新文字', () => {
    const segs = charDiff('每日 06:30 前完成采集', '每日 06:30 前完成采集，无缺失')
    expect(join(segs, ['same', 'del'])).toBe('每日 06:30 前完成采集')
    expect(join(segs, ['same', 'add'])).toBe('每日 06:30 前完成采集，无缺失')
  })

  it('错别字：中间一个字', () => {
    const segs = charDiff('无缺失门店', '无缺失门点')
    expect(segs).toEqual([
      { kind: 'same', text: '无缺失门' },
      { kind: 'del', text: '店' },
      { kind: 'add', text: '点' },
    ])
  })

  it('相同或空值不报错', () => {
    expect(charDiff('abc', 'abc')).toEqual([{ kind: 'same', text: 'abc' }])
    expect(charDiff(null, 'x')).toEqual([{ kind: 'add', text: 'x' }])
    expect(charDiff('x', undefined)).toEqual([{ kind: 'del', text: 'x' }])
  })
})

describe('changeWhere', () => {
  it('位置说明', () => {
    expect(changeWhere({ block_title: '退款', kind: 'rule', item_id: 'R-2', field: 'detail' })).toBe('退款 · 规则 R-2 · 详述')
    expect(changeWhere({ block_id: 3, kind: 'ac', item_id: 'AC-1', field: 'name' })).toBe('模块 #3 · 验收条件 AC-1 · 名称')
  })
})

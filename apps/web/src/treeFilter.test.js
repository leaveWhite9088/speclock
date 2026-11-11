import { describe, expect, it } from 'vitest'
import { TREE_FILTERS, filterTree, matchesFilter, progressOf } from './treeFilter.js'

const blk = (id, execution_status, over = {}) => ({
  kind: 'block',
  id,
  status: 'published',
  version: '1.0.0',
  execution_status,
  ...over,
})

const tree = [
  {
    kind: 'project',
    id: 1,
    children: [
      {
        kind: 'business',
        id: 1,
        children: [
          {
            kind: 'capability',
            id: 10,
            children: [blk(1, 'verified'), blk(2, 'pending'), blk(3, 'blocked'), blk(4, 'failed')],
          },
          {
            kind: 'capability',
            id: 11,
            children: [blk(5, 'implemented'), blk(6, 'in_progress'), blk(7, 'verified', { status: 'archived' }), blk(8, undefined, { status: 'draft', version: null })],
          },
        ],
      },
    ],
  },
]

const ids = (nodes) => {
  const out = []
  const walk = (n) => (n.kind === 'block' ? out.push(n.id) : (n.children || []).forEach(walk))
  nodes.forEach(walk)
  return out
}

describe('matchesFilter', () => {
  it('没有筛选条件时全部命中（含草稿和归档）', () => {
    expect(matchesFilter(blk(8, undefined, { status: 'draft' }), '')).toBe(true)
  })

  it('未验收 = 除已验收之外的所有已发布模块', () => {
    expect(matchesFilter(blk(1, 'pending'), 'open')).toBe(true)
    expect(matchesFilter(blk(1, 'verified'), 'open')).toBe(false)
  })

  it('卡住 = 被阻塞或失败', () => {
    expect(matchesFilter(blk(1, 'blocked'), 'stuck')).toBe(true)
    expect(matchesFilter(blk(1, 'failed'), 'stuck')).toBe(true)
    expect(matchesFilter(blk(1, 'in_progress'), 'stuck')).toBe(false)
  })

  it('其余按执行状态精确匹配；草稿和归档的模块永不命中', () => {
    expect(matchesFilter(blk(1, 'implemented'), 'implemented')).toBe(true)
    expect(matchesFilter(blk(1, 'pending'), 'implemented')).toBe(false)
    expect(matchesFilter(blk(1, 'verified', { status: 'archived' }), 'verified')).toBe(false)
    expect(matchesFilter(blk(1, 'pending', { version: null }), 'open')).toBe(false)
  })
})

describe('filterTree', () => {
  it('没有条件时原样返回', () => {
    expect(filterTree(tree, '')).toBe(tree)
  })

  it('保留命中的模块和它的上层节点，其余剪掉', () => {
    const t = filterTree(tree, 'stuck')
    expect(ids(t)).toEqual([3, 4])
    expect(t[0].children[0].children).toHaveLength(1) // 只剩第一个小业务
  })

  it('未验收：两个小业务都有命中', () => {
    expect(ids(filterTree(tree, 'open'))).toEqual([2, 3, 4, 5, 6])
  })

  it('没有任何命中时返回空数组', () => {
    expect(filterTree(tree, 'nothing-matches')).toEqual([])
  })

  it('筛选选项里有「全部」', () => {
    expect(TREE_FILTERS[0][0]).toBe('')
  })
})

describe('progressOf', () => {
  it('只统计已发布模块', () => {
    const caps = tree[0].children[0].children
    expect(progressOf(caps[0].children)).toEqual({ total: 4, verified: 1 })
    expect(progressOf(caps[1].children)).toEqual({ total: 2, verified: 0 })
    expect(progressOf([])).toEqual({ total: 0, verified: 0 })
    expect(progressOf()).toEqual({ total: 0, verified: 0 })
  })
})

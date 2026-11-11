import { describe, expect, it } from 'vitest'
import { buildTrace, indexTree, metaChanges, prevVersionOf } from './trace.js'

const tree = [
  {
    businesses: [
      {
        id: 1,
        name: '社区小店',
        capabilities: [
          { id: 10, title: '订单中心', blocks: [{ id: 100, title: '退款' }, { id: 101, title: '订单内容' }] },
          { id: 11, title: '第二小业务', blocks: [] },
        ],
      },
    ],
  },
]

const blockVersions = {
  100: [
    { version: '1.0.0', execution_status: 'verified' },
    { version: '1.1.0', execution_status: 'pending' },
  ],
}
const capVersions = {
  10: [{ version: '1.0.0' }, { version: '1.1.0' }, { version: '1.2.0' }],
}

const cr = {
  commits: [
    {
      id: 7,
      seq: 2,
      change_note: '补充退款规则',
      covers: ['AC-1'],
      created_by: 'agent-…aaaa',
      created_at: '2026-11-09T10:00:00',
      ops: [{ op: 'update_block' }],
      result: {
        created: { $cap: { type: 'capability', id: 11 }, $biz: { type: 'business', id: 1 }, $blk: { type: 'block', id: 5 } },
        blocks: [
          { block_id: 100, title: '退款', version: '1.1.0', level: 'minor', created: false },
          { block_id: 101, title: '订单内容', version: '1.0.0', level: 'initial', created: true },
        ],
        capability_versions: [{ capability_id: 10, version: '1.2.0', level: 'minor' }],
        archived_blocks: [101],
        restored_blocks: [],
        moved_blocks: [100],
      },
    },
  ],
}

describe('prevVersionOf', () => {
  it('取上一个版本；第一个版本和不存在的版本返回空串', () => {
    expect(prevVersionOf(capVersions[10], '1.2.0')).toBe('1.1.0')
    expect(prevVersionOf(capVersions[10], '1.0.0')).toBe('')
    expect(prevVersionOf(capVersions[10], '9.9.9')).toBe('')
    expect(prevVersionOf(undefined, '1.0.0')).toBe('')
  })
})

describe('indexTree', () => {
  it('按 id 索引大业务、小业务、模块', () => {
    const idx = indexTree(tree)
    expect(idx.businesses.get(1).title).toBe('社区小店')
    expect(idx.capabilities.get(10)).toMatchObject({ title: '订单中心', business: '社区小店' })
    expect(idx.blocks.get(100)).toMatchObject({ title: '退款', capabilityId: 10 })
  })
})

describe('metaChanges', () => {
  it('改名和改简述（大业务 / 小业务 / 模块）', () => {
    const out = metaChanges([
      { op: 'update_business', id: 1, name: '运营中心' },
      { op: 'update_capability', id: 10, title: '订单中心', summary: '新简述' },
      { op: 'update_capability', id: 11, summary: '只改简述' },
      { op: 'update_block', id: 100, title: '退款（新）', rule_ops: [] },
    ])
    expect(out.map((m) => [m.typeText, m.id, m.title, m.fields])).toEqual([
      ['大业务', 1, '运营中心', ['名称']],
      ['小业务', 10, '订单中心', ['名称', '简述']],
      ['小业务', 11, '', ['简述']],
      ['模块', 100, '退款（新）', ['名称']],
    ])
  })

  it('不改名的 update_block、其他 op、缺 ops 都不产生条目', () => {
    expect(metaChanges([{ op: 'update_block', id: 1, rule_ops: [] }, { op: 'archive_block', id: 1 }])).toEqual([])
    expect(metaChanges()).toEqual([])
    expect(metaChanges(null)).toEqual([])
  })

  it('buildTrace 里没带新名字时用文档树里的标题', () => {
    const c = {
      id: 1, seq: 1,
      ops: [{ op: 'update_capability', id: 10, summary: 'x' }],
      result: {},
    }
    const [t] = buildTrace({ cr: { commits: [c] }, tree })
    expect(t.meta[0]).toMatchObject({ typeText: '小业务', title: '订单中心', fields: ['简述'] })
  })
})

describe('buildTrace', () => {
  const [commit] = buildTrace({ cr, tree, blockVersions, capVersions })

  it('Commit 基本信息', () => {
    expect(commit).toMatchObject({ id: 7, seq: 2, note: '补充退款规则', covers: ['AC-1'], createdBy: 'agent-…aaaa' })
  })

  it('更新的模块：显示从哪个版本变到哪个版本，以及现在的执行状态', () => {
    expect(commit.blocks[0]).toMatchObject({
      blockId: 100,
      version: '1.1.0',
      prevVersion: '1.0.0',
      level: 'minor',
      created: false,
      executionStatus: 'pending',
    })
  })

  it('新建的模块没有上一个版本；没取到版本列表时执行状态为空', () => {
    expect(commit.blocks[1]).toMatchObject({ created: true, prevVersion: '', executionStatus: '' })
  })

  it('小业务版本变化', () => {
    expect(commit.capabilities).toEqual([
      { id: 10, title: '订单中心', version: '1.2.0', prevVersion: '1.1.0', level: 'minor' },
    ])
  })

  it('新建的大业务 / 小业务（模块不重复列在这里）', () => {
    expect(commit.createdStructure.map((x) => [x.typeText, x.title])).toEqual([
      ['小业务', '第二小业务'],
      ['大业务', '社区小店'],
    ])
  })

  it('归档 / 恢复 / 搬动的模块带上标题', () => {
    expect(commit.archived).toEqual([{ id: 101, title: '订单内容' }])
    expect(commit.restored).toEqual([])
    expect(commit.moved).toEqual([{ id: 100, title: '退款' }])
  })

  it('没有 Commit 或结果缺字段时不报错；查不到标题用编号', () => {
    expect(buildTrace({ cr: { commits: [] }, tree })).toEqual([])
    expect(buildTrace({})).toEqual([])
    const [c] = buildTrace({ cr: { commits: [{ id: 1, seq: 1, result: { archived_blocks: [999] } }] }, tree })
    expect(c.archived).toEqual([{ id: 999, title: '模块 #999' }])
    expect(c.blocks).toEqual([])
  })
})

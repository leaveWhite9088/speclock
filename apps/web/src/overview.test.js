import { describe, expect, it } from 'vitest'
import { buildOverview, moduleStats } from './overview.js'

const NOW = Date.parse('2026-11-09T12:00:00Z')
const ago = (hours) => new Date(NOW - hours * 3600 * 1000).toISOString().replace('Z', '')

const cr = (id, over = {}) => ({
  id,
  title: `单 ${id}`,
  status: 'applied',
  kind: 'business',
  created_at: ago(100),
  submitted_at: ago(99),
  decided_at: ago(98),
  acceptance: [{ id: 'AC-1' }],
  ...over,
})
const wk = (id, status, over = {}) => ({ id, status, block_id: id, updated_at: ago(1), ...over })

describe('buildOverview', () => {
  it('等我确认：只含 pending_review，最久的在前', () => {
    const o = buildOverview({
      now: NOW,
      crs: [
        cr(1, { status: 'pending_review', submitted_at: ago(2) }),
        cr(2, { status: 'pending_review', submitted_at: ago(30) }),
        cr(3, { status: 'applied' }),
        cr(4, { status: 'draft' }),
      ],
    })
    expect(o.pending.map((c) => c.id)).toEqual([2, 1])
  })

  it('内部整理：最近 7 天、非草稿，新的在前；超过 7 天的不显示', () => {
    const o = buildOverview({
      now: NOW,
      crs: [
        cr(1, { kind: 'internal', decided_at: ago(10) }),
        cr(2, { kind: 'internal', decided_at: ago(2) }),
        cr(3, { kind: 'internal', decided_at: ago(24 * 8) }), // 8 天前
        cr(4, { kind: 'internal', status: 'draft', decided_at: null, created_at: ago(1) }),
        cr(5, { kind: 'business', decided_at: ago(1) }),
      ],
    })
    expect(o.internal.map((c) => c.id)).toEqual([2, 1])
  })

  it('卡住的任务：被阻塞和失败，等得最久的在前；等验收和进行中各自独立', () => {
    const o = buildOverview({
      now: NOW,
      work: [
        wk(1, 'blocked', { updated_at: ago(1) }),
        wk(2, 'failed', { updated_at: ago(5) }),
        wk(3, 'implemented'),
        wk(4, 'in_progress'),
        wk(5, 'pending'),
        wk(6, 'verified'),
      ],
    })
    expect(o.stuck.map((w) => w.id)).toEqual([2, 1])
    expect(o.waiting.map((w) => w.id)).toEqual([3])
    expect(o.inProgress.map((w) => w.id)).toEqual([4])
    expect(o.counts.work).toEqual({ blocked: 1, failed: 1, implemented: 1, in_progress: 1, pending: 1, verified: 1 })
    // 6 个任务里 implemented + verified = 2 个已完成
    expect(o.counts).toMatchObject({ workTotal: 6, workDone: 2, workDonePercent: 33 })
  })

  it('需要关注的总数 = 待确认 + 卡住 + 内部整理', () => {
    const o = buildOverview({
      now: NOW,
      crs: [cr(1, { status: 'pending_review' }), cr(2, { kind: 'internal', decided_at: ago(1) })],
      work: [wk(1, 'blocked')],
    })
    expect(o.attention).toBe(3)
  })

  it('空数据：isEmpty 为真，不会报错', () => {
    const o = buildOverview({ now: NOW })
    expect(o.isEmpty).toBe(true)
    expect(o.attention).toBe(0)
    expect(o.counts.verifiedPercent).toBe(0)
  })

  it('有数据时 isEmpty 为假', () => {
    expect(buildOverview({ now: NOW, crs: [cr(1)] }).isEmpty).toBe(false)
  })
})

describe('moduleStats / 已验收占比', () => {
  const tree = [
    {
      businesses: [
        {
          capabilities: [
            {
              blocks: [
                { status: 'published', execution_status: 'verified' },
                { status: 'published', execution_status: 'pending' },
                { status: 'published', execution_status: 'verified' },
                { status: 'archived', execution_status: 'verified' },
                { status: 'draft' },
              ],
            },
          ],
        },
      ],
    },
  ]

  it('只统计已发布的模块', () => {
    expect(moduleStats(tree)).toEqual({ published: 3, verified: 2 })
  })

  it('占比四舍五入到整数', () => {
    expect(buildOverview({ now: NOW, tree }).counts).toMatchObject({
      modules: 3,
      verifiedModules: 2,
      verifiedPercent: 67,
    })
  })
})

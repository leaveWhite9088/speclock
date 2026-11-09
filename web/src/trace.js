/**
 * 追溯：把一张审核单的 Commit 落地结果整理成「审核单 → Commit → 受影响的模块 / 小业务
 * （版本怎么变的）→ 现在做到哪了」。buildTrace 是纯函数，loadTraceData 负责取数。
 */
import { resources } from './api/resources.js'

const TYPE_TEXT = { business: '大业务', capability: '小业务', block: '模块' }

/** ops 里的改名 / 改简述（不产生模块版本，但也是这次 Commit 做的事） */
export function metaChanges(ops = []) {
  const out = []
  for (const op of ops || []) {
    if (op.op === 'update_business' && op.name) {
      out.push({ type: 'business', typeText: '大业务', id: op.id, title: op.name, fields: ['名称'] })
    } else if (op.op === 'update_capability') {
      const fields = [op.title && '名称', op.summary && '简述'].filter(Boolean)
      if (fields.length) out.push({ type: 'capability', typeText: '小业务', id: op.id, title: op.title || '', fields })
    } else if (op.op === 'update_block') {
      const fields = [op.title && '名称', op.summary && '简述'].filter(Boolean)
      if (fields.length) out.push({ type: 'block', typeText: '模块', id: op.id, title: op.title || '', fields })
    }
  }
  return out
}

/** versions 按时间从旧到新；返回 version 的上一个版本号，没有则返回空串 */
export function prevVersionOf(versions = [], version) {
  const i = versions.findIndex((v) => v.version === version)
  return i > 0 ? versions[i - 1].version : ''
}

/** 文档树 → 方便按 id 查标题 */
export function indexTree(tree = []) {
  const businesses = new Map()
  const capabilities = new Map()
  const blocks = new Map()
  for (const p of tree)
    for (const biz of p.businesses || []) {
      businesses.set(biz.id, { title: biz.name })
      for (const cap of biz.capabilities || []) {
        capabilities.set(cap.id, { title: cap.title, business: biz.name })
        for (const b of cap.blocks || []) blocks.set(b.id, { title: b.title, capabilityId: cap.id })
      }
    }
  return { businesses, capabilities, blocks }
}

/**
 * cr：审核单详情（含 commits）；tree：文档树；
 * blockVersions：{ 模块 id: /blocks/{id}/versions 的结果 }；capVersions：{ 小业务 id: /capabilities/{id}/versions 的结果 }。
 */
export function buildTrace({ cr, tree = [], blockVersions = {}, capVersions = {} } = {}) {
  const idx = indexTree(tree)
  const blockTitle = (id) => idx.blocks.get(id)?.title || `模块 #${id}`
  const plain = (ids) => (ids || []).map((id) => ({ id, title: blockTitle(id) }))

  return (cr?.commits || []).map((c) => {
    const r = c.result || {}

    const blocks = (r.blocks || []).map((b) => {
      const versions = blockVersions[b.block_id] || []
      const entry = versions.find((v) => v.version === b.version)
      return {
        blockId: b.block_id,
        title: b.title || blockTitle(b.block_id),
        version: b.version,
        prevVersion: b.created ? '' : prevVersionOf(versions, b.version),
        level: b.level,
        created: !!b.created,
        executionStatus: entry?.execution_status || '',
      }
    })

    const capabilities = (r.capability_versions || []).map((cv) => ({
      id: cv.capability_id,
      title: idx.capabilities.get(cv.capability_id)?.title || `小业务 #${cv.capability_id}`,
      version: cv.version,
      prevVersion: prevVersionOf(capVersions[cv.capability_id] || [], cv.version),
      level: cv.level,
    }))

    // 本 Commit 新建的大业务 / 小业务（模块的新建体现在 blocks 里）
    const createdStructure = Object.values(r.created || {})
      .filter((x) => x.type === 'business' || x.type === 'capability')
      .map((x) => ({
        type: x.type,
        typeText: TYPE_TEXT[x.type],
        id: x.id,
        title: (x.type === 'business' ? idx.businesses : idx.capabilities).get(x.id)?.title || `#${x.id}`,
      }))

    return {
      id: c.id,
      seq: c.seq,
      note: c.change_note,
      covers: c.covers || [],
      createdBy: c.created_by,
      createdAt: c.created_at,
      ops: c.ops,
      status: c.status || 'applied',
      review: c.review && (c.review.changes || c.review.decision) ? c.review : null,
      createdStructure,
      meta: metaChanges(c.ops).map((m) => ({
        ...m,
        title:
          m.title ||
          (m.type === 'business' ? idx.businesses : m.type === 'capability' ? idx.capabilities : idx.blocks).get(m.id)?.title ||
          `#${m.id}`,
      })),
      blocks,
      capabilities,
      archived: plain(r.archived_blocks),
      restored: plain(r.restored_blocks),
      moved: plain(r.moved_blocks),
    }
  })
}

/** 取 buildTrace 需要的数据：文档树，以及这张审核单涉及到的每个模块 / 小业务的版本列表 */
export async function loadTraceData(cr) {
  const blockIds = new Set()
  const capIds = new Set()
  for (const c of cr?.commits || []) {
    for (const b of c.result?.blocks || []) blockIds.add(b.block_id)
    for (const cv of c.result?.capability_versions || []) capIds.add(cv.capability_id)
  }
  const blockList = [...blockIds]
  const capList = [...capIds]
  const [tree, ...rest] = await Promise.all([
    resources.tree(),
    ...blockList.map((id) => resources.blocks.versions(id)),
    ...capList.map((id) => resources.capabilities.versions(id)),
  ])
  const blockVersions = {}
  const capVersions = {}
  blockList.forEach((id, i) => (blockVersions[id] = rest[i]))
  capList.forEach((id, i) => (capVersions[id] = rest[blockList.length + i]))
  return { tree, blockVersions, capVersions }
}

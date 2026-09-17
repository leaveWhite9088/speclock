/** 会议记录模块的共享常量：文件类型 / 解析状态 / 条目类型的中文展示映射。 */

export const KIND_LABELS = {
  requirements: '精准需求',
  facts: '业务事实',
  confirm: '需求确认单',
  transcript: '转写稿',
  questions: '内部问题清单',
  glossary: '修正词表',
  other: '其他',
}

export const SHAREABLE_KINDS = [
  'requirements',
  'facts',
  'confirm',
  'transcript',
  'questions',
  'glossary',
]

export const PARSE_LABELS = {
  ok: '解析成功',
  failed: '解析失败',
  degraded: '部分解析',
  na: '整篇存储',
}

export const CHUNK_TYPE_LABELS = {
  req: '需求',
  fact: '事实',
  con: '约束',
  act: '行动项',
  q: '待澄清',
  prose: '散文',
}

export const STATUS_LABELS = {
  confirmed: '已确认',
  conflict: '有冲突',
  needs_clarification: '待澄清',
  deferred: '暂缓',
}

export const STATUS_OPTIONS = ['confirmed', 'conflict', 'needs_clarification', 'deferred']

/** 各条目类型的可编辑字段（quotes 只读，不在此列） */
export const ITEM_FIELDS = {
  req: ['statement', 'status', 'confirm', 'based_on'],
  con: ['statement', 'status', 'confirm', 'based_on'],
  act: ['statement', 'owner', 'status', 'confirm', 'based_on'],
  q: ['question', 'confirm', 'suggest'],
  fact: ['statement', 'category'],
}

export const FIELD_LABELS = {
  statement: '陈述',
  question: '问题',
  status: '状态',
  confirm: '确认单编号',
  based_on: '依据事实',
  owner: '负责人',
  suggest: '建议',
  category: '分类',
}

/** 切块文件允许新增的条目类型 */
export const ADDABLE_TYPES = {
  requirements: ['req', 'con', 'act', 'q'],
  facts: ['fact'],
}

export function fmtTime(iso) {
  return iso ? String(iso).replace('T', ' ').slice(0, 19) : '-'
}

export function errText(e) {
  const d = e && e.detail
  if (!d) return '请求失败，请检查网络后重试。'
  if (typeof d === 'string') return d
  return d.error || JSON.stringify(d)
}

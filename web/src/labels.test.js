import { describe, expect, it } from 'vitest'
import {
  ACTIONS,
  BLOCK_STATUS,
  CR_KIND,
  CR_STATUS,
  DECISION_VIA,
  EXEC_EVENT,
  EXEC_STATUS,
  label,
} from './labels.js'

describe('label', () => {
  it('命中时返回中文，未知键原样显示，空值显示破折号', () => {
    expect(label(CR_STATUS, 'pending_review')).toBe('待确认')
    expect(label(CR_STATUS, 'brand_new_status')).toBe('brand_new_status')
    expect(label(CR_STATUS, undefined)).toBe('—')
    expect(label(CR_STATUS, '')).toBe('—')
  })
})

describe('文案表覆盖后端的全部取值', () => {
  it('审核单状态', () => {
    for (const s of ['draft', 'pending_review', 'approved', 'applied', 'rejected', 'superseded']) {
      expect(CR_STATUS[s], s).toBeTruthy()
    }
  })

  it('执行状态与事件', () => {
    for (const s of ['pending', 'in_progress', 'blocked', 'failed', 'implemented', 'verified', 'superseded']) {
      expect(EXEC_STATUS[s], s).toBeTruthy()
    }
    for (const e of ['created', 'claim', 'release', 'blocked', 'failed', 'implemented', 'verified', 'verify_failed', 'superseded']) {
      expect(EXEC_EVENT[e], e).toBeTruthy()
    }
  })

  it('批准方式不再有按钮', () => {
    expect(Object.keys(DECISION_VIA).sort()).toEqual(['agent_declared', 'api', 'cli', 'natural_language'])
    expect(CR_KIND.internal).toBe('内部整理')
    expect(BLOCK_STATUS.archived).toBe('已归档')
  })

  it('审计动作：审核单、执行、密钥相关的都有中文名', () => {
    for (const a of [
      'pull', 'publish', 'commit', 'archive', 'restore', 'move',
      'cr_create', 'cr_update', 'cr_submit', 'cr_withdraw', 'cr_approve', 'cr_reject', 'cr_applied', 'cr_superseded',
      'exec_claim', 'exec_release', 'exec_blocked', 'exec_failed', 'exec_implemented', 'exec_verified',
      'exec_verify_failed', 'exec_superseded',
      'key_create', 'key_delete', 'role_create', 'role_update', 'role_delete', 'project_create', 'rename', 'delete',
    ]) {
      expect(ACTIONS[a], a).toBeTruthy()
    }
  })
})

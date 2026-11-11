import { describe, expect, it } from 'vitest'
import { parseProject } from './project.js'

describe('project', () => {
  it('地址里的 project 参数只认纯数字', () => {
    expect(parseProject('?project=3')).toBe(3)
    expect(parseProject('?embed=1&project=12')).toBe(12)
    expect(parseProject('')).toBeNull()
    expect(parseProject('?project=abc')).toBeNull()
    expect(parseProject('?project=1;drop')).toBeNull()
  })
})

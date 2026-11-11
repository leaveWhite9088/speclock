import { describe, expect, it } from 'vitest'
import { NETWORK_ERROR, errText } from './errors.js'

describe('errText', () => {
  it('网络不通（fetch 抛 TypeError）给出启动服务的提示', () => {
    expect(errText(new TypeError('Failed to fetch'))).toBe(NETWORK_ERROR)
  })

  it('没有 status 也没有 detail 的错误也当作网络问题', () => {
    expect(errText({})).toBe(NETWORK_ERROR)
  })

  it('字符串 detail 原样返回', () => {
    expect(errText({ status: 409, detail: '审核单是 draft' })).toBe('审核单是 draft')
  })

  it('结构化 detail：error 加上 missing / problems 列表', () => {
    const e = { status: 422, detail: { error: '模块结构不完备', missing: ['缺规则', '缺验收条件'] } }
    expect(errText(e)).toBe('模块结构不完备\n· 缺规则\n· 缺验收条件')
    expect(errText({ status: 422, detail: { error: '不完整', problems: ['AC-2 缺证据'] } })).toBe(
      '不完整\n· AC-2 缺证据',
    )
  })

  it('403 带上「没有权限」前缀，并保留后端说明', () => {
    expect(errText({ status: 403, detail: '当前密钥的角色缺少权限：key.manage' })).toBe(
      '没有权限：当前密钥的角色缺少权限：key.manage',
    )
    expect(errText({ status: 403, detail: '' })).toContain('没有权限')
  })

  it('404：后端只说 not found 时换成人话，有具体说明时保留', () => {
    expect(errText({ status: 404, detail: 'not found' })).toContain('没有找到')
    expect(errText({ status: 404, detail: 'block 9999 not found' })).toContain('没有找到')
    expect(errText({ status: 404, detail: '小业务 9 不存在' })).toBe('小业务 9 不存在')
  })

  it('其他状态码：有说明用说明，没有就报 HTTP 状态', () => {
    expect(errText({ status: 500, detail: '' })).toBe('请求失败（HTTP 500）。')
  })

  it('空值不会抛错', () => {
    expect(errText(null)).toContain('请求失败')
  })
})

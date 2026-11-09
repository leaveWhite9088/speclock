/**
 * 颜色对比度检查（WCAG AA：正文至少 4.5:1）。直接读 tokens.css，换色板时能第一时间发现。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// 测试从 web/ 目录运行
const tokens = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf-8')

function colors() {
  const out = {}
  for (const m of tokens.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) out[m[1]] = m[2]
  return out
}

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function ratio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const c = colors()

describe('对比度', () => {
  it('读到了色板', () => {
    expect(c.ink).toBeTruthy()
    expect(c.paper).toBeTruthy()
  })

  const pairs = [
    ['ink', 'card'],
    ['ink', 'paper'],
    ['ink-2', 'card'],
    ['ink-2', 'paper'],
    ['contract', 'card'],
    ['contract', 'contract-wash'],
    ['success', 'card'],
    ['danger', 'card'],
    ['warning', 'card'],
    ['card', 'contract'], // 主按钮：白字蓝底
  ]
  for (const [fg, bg] of pairs) {
    it(`${fg} 在 ${bg} 上 ≥ 4.5:1`, () => {
      expect(ratio(c[fg], c[bg])).toBeGreaterThanOrEqual(4.5)
    })
  }
})

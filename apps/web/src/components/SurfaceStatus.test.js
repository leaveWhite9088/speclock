import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SurfaceStatus from './SurfaceStatus.vue'

describe('SurfaceStatus', () => {
  it('只有一个端（没声明端的模块）时什么都不显示', () => {
    expect(mount(SurfaceStatus, { props: { works: [{ work_id: 1, surface: '', status: 'pending' }] } }).html()).toBe('<!--v-if-->')
    expect(mount(SurfaceStatus).html()).toBe('<!--v-if-->')
  })

  it('多个端时每个端各显示自己的状态', () => {
    const w = mount(SurfaceStatus, {
      props: {
        works: [
          { work_id: 1, surface: '前端', status: 'verified' },
          { work_id: 2, surface: '后端', status: 'blocked' },
        ],
      },
    })
    const items = w.findAll('.surface-item')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toContain('前端')
    expect(items[0].find('.exec-badge').classes()).toContain('is-verified')
    expect(items[1].text()).toContain('后端')
    expect(items[1].find('.exec-badge').classes()).toContain('is-blocked')
  })
})

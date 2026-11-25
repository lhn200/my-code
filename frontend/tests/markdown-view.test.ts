// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import MarkdownView from '@/components/MarkdownView.vue'

describe('MarkdownView', () => {
  it('渲染标题与列表', () => {
    const wrapper = mount(MarkdownView, {
      props: { source: '# 标题\n\n- 条目一\n- 条目二' },
    })

    expect(wrapper.find('h1').text()).toBe('标题')
    expect(wrapper.findAll('li')).toHaveLength(2)
  })

  it('过滤 script 与事件属性', () => {
    const wrapper = mount(MarkdownView, {
      props: {
        source: '正常文本<script>window.__hacked = true</script><img src="x" onerror="window.__hacked = true" />',
      },
    })

    const html = wrapper.html()
    expect(html).not.toContain('<script')
    expect(html).not.toContain('onerror')
    expect((window as unknown as Record<string, unknown>).__hacked).toBeUndefined()
  })

  it('空输入展示空状态', () => {
    const wrapper = mount(MarkdownView, { props: { source: '   ' } })
    expect(wrapper.text()).toContain('暂无求职建议')
  })
})

import { describe, expect, it } from 'vitest'
import { markdownHeadings, renderMarkdown } from './markdown'

describe('markdown', () => {
  it('渲染标题并给锚点 id，目录能对上', () => {
    const src = '## 第一部分：全书大纲\n\n### 1. 全书层\n\n### 第1卷 开局（第1-30章）'
    const html = renderMarkdown(src)
    expect(html).toContain('<h2 id="第一部分全书大纲">')
    expect(html).toContain('<h3 id="1-全书层">')

    const heads = markdownHeadings(src)
    expect(heads.map((h) => h.level)).toEqual([2, 3, 3])
    expect(heads[0].id).toBe('第一部分全书大纲')
    expect(heads[1].text).toBe('1. 全书层')
    expect(html).toContain(`id="${heads[2].id}"`)
  })

  it('渲染表格：支线表和对手阶梯表要能读', () => {
    const src = '| 支线 | 发起卷 | 交汇章 |\n| --- | --- | --- |\n| 旧案 | 1 | 27 |'
    const html = renderMarkdown(src)
    expect(html).toContain('<table>')
    expect(html).toContain('<th>支线</th>')
    expect(html).toContain('<td>旧案</td>')
  })

  it('渲染列表、嵌套列表和引用', () => {
    const html = renderMarkdown('- 第一卷\n  - 目标：拿到凭证\n  - 代价：失去名字\n- 第二卷\n\n> 一句话故事核')
    expect(html).toContain('<ul>')
    expect(html.match(/<ul>/g)?.length).toBeGreaterThanOrEqual(2)
    expect(html).toContain('<li>第一卷<ul>')
    expect(html).toContain('<blockquote>一句话故事核</blockquote>')
  })

  it('先转义 HTML，不执行模型输出里的标签', () => {
    const html = renderMarkdown('<script>alert(1)</script>\n\n**粗** 与 `代码`')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
    expect(html).toContain('<strong>粗</strong>')
    expect(html).toContain('<code>代码</code>')
  })

  it('代码块里的 # 不算标题', () => {
    const heads = markdownHeadings('```\n# 不是标题\n```\n## 真标题')
    expect(heads.map((h) => h.text)).toEqual(['真标题'])
  })
})

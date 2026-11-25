import { describe, expect, it } from 'vitest'
import { highlightSegments } from './highlight'

describe('highlightSegments', () => {
  it('没有关键词时原样返回', () => {
    expect(highlightSegments('他推开门。', '  ')).toEqual([{ text: '他推开门。', hit: false }])
  })

  it('多处命中各自成段，大小写不敏感', () => {
    expect(highlightSegments('Door 与 door', 'door')).toEqual([
      { text: 'Door', hit: true },
      { text: ' 与 ', hit: false },
      { text: 'door', hit: true },
    ])
  })

  it('关键词里的正则符号按字面匹配', () => {
    expect(highlightSegments('价 3.5 元', '3.5')).toEqual([
      { text: '价 ', hit: false },
      { text: '3.5', hit: true },
      { text: ' 元', hit: false },
    ])
  })

  it('没命中时整段返回', () => {
    expect(highlightSegments('他推开门。', '灯')).toEqual([{ text: '他推开门。', hit: false }])
  })
})

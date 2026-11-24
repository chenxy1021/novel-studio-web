import { describe, expect, it } from 'vitest'
import type { Location } from '@/mocks'
import { bearingOf, frameOf, tierName, tierOf } from './atlas'

function loc(patch: Partial<Location> & { name: string }): Location {
  return {
    id: patch.name,
    geo: '',
    structure: '',
    senses: '',
    owner: '',
    accessRules: '',
    occupied: '',
    state: '',
    stateAt: 0,
    events: '',
    familiar: '',
    mapX: 0,
    mapY: 0,
    terrain: '',
    text: '',
    ...patch,
  }
}

describe('atlas', () => {
  it('按地点名分层，名字没有线索的落中层', () => {
    expect(tierOf(loc({ name: '登记室', geo: '位于庇护所中区正中' }))).toBe(0)
    expect(tierOf(loc({ name: '内舱与舱门' }))).toBe(1)
    expect(tierOf(loc({ name: '外墙与狙击位' }))).toBe(3)
    expect(tierOf(loc({ name: '废墟带与尸潮走廊' }))).toBe(4)
    expect(tierOf(loc({ name: '新城' }))).toBe(4)
    expect(tierOf(loc({ name: '医疗棚', geo: '庇护所内，靠近外墙一侧' }))).toBe(2)
  })

  it('层级名用设定自己的词', () => {
    const corpus = '庇护所 内舱与舱门 中区 外墙 废墟带'
    expect(tierName(1, corpus)).toBe('内舱')
    expect(tierName(2, corpus)).toBe('中区')
    expect(tierName(3, corpus)).toBe('外墙')
    expect(tierName(4, corpus)).toBe('城外')
  })

  it('被两处以上地点提到的地点算范围', () => {
    const locations = [
      loc({ name: '庇护所', geo: '旧军工厂' }),
      loc({ name: '登记室', geo: '庇护所中区正中' }),
      loc({ name: '医疗棚', geo: '庇护所内，靠近外墙' }),
      loc({ name: '夹道', geo: '登记室北墙外' }),
    ]
    expect(frameOf(locations)?.name).toBe('庇护所')
  })

  it('方位词读不出或打平就不猜', () => {
    expect(bearingOf(loc({ name: '新城', geo: '庇护所以南' }))).toBe(90)
    expect(bearingOf(loc({ name: '废墟带', geo: '北通备用舱库，南接新城' }))).toBeNull()
    expect(bearingOf(loc({ name: '配给站', geo: '庇护所内' }))).toBeNull()
  })
})

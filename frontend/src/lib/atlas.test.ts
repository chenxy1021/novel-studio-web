import { describe, expect, it } from 'vitest'
import type { Location } from '@/mocks'
import { bearingOf, frameOf, layerOf, layersOf, mapMode, scopeOf } from './atlas'

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
    mapScope: '',
    mapLayer: '',
    mapBearing: '',
    terrain: '',
    text: '',
    ...patch,
  }
}

describe('atlas', () => {
  it('套娃世界：显式层级按序号由内到外，层名去掉序号', () => {
    const shelter = [
      loc({ name: '登记室', mapLayer: '0 核心' }),
      loc({ name: '医疗棚', mapLayer: '2 中区' }),
      loc({ name: '内舱', mapLayer: '1 内舱' }),
      loc({ name: '废墟带', mapLayer: '3 城外' }),
    ]
    const layers = layersOf(shelter)
    expect(layers.map((l) => l.name)).toEqual(['核心', '内舱', '中区', '城外'])
    expect(layerOf(shelter[1], layers)?.name).toBe('中区')
    expect(mapMode(shelter)).toBe('layers')
  })

  it('平面地理：两处有坐标就按坐标排，不看层级', () => {
    const realm = [
      loc({ name: '洛阳', mapX: 48, mapY: 40 }),
      loc({ name: '成都', mapX: 26, mapY: 58 }),
      loc({ name: '建业', mapX: 70, mapY: 52 }),
    ]
    expect(mapMode(realm)).toBe('coords')
    expect(layersOf(realm)).toEqual([])
  })

  it('既有坐标又有层时，以层为准', () => {
    const mixed = [
      loc({ name: '内城', mapX: 40, mapY: 40 }),
      loc({ name: '外城', mapX: 60, mapY: 60 }),
    ]
    expect(mapMode(mixed)).toBe('layers')
  })

  it('范围正文把地名和层写在一起时，按同一句定层', () => {
    const frame = loc({
      name: '庇护所',
      structure: '外墙（狙击位）、中区（配给站、登记室）、内舱（转移舱库、主任区）',
    })
    const plan = [loc({ name: '配给站', geo: '庇护所内' }), loc({ name: '主任区' })]
    const layers = layersOf(plan, frame)
    expect(layers.map((l) => l.name)).toEqual(['内舱', '中区'])
    expect(layerOf(plan[0], layers, frame)?.name).toBe('中区')
    expect(layerOf(plan[1], layers, frame)?.name).toBe('内舱')
  })

  it('没写 mapLayer 的书按名字里的空间词分层，层名取设定自己的词', () => {
    const sect = [
      loc({ name: '主殿' }),
      loc({ name: '内门演武场' }),
      loc({ name: '外门杂役院' }),
      loc({ name: '后山荒野' }),
    ]
    const layers = layersOf(sect)
    expect(layers.map((l) => l.name)).toEqual(['主殿', '内门', '外门', '荒野'])
    expect(layerOf(sect[2], layers)?.name).toBe('外门')
  })

  it('范围：显式 mapScope 优先，否则认 geo 里提到的地点名', () => {
    const city = [
      loc({ name: '北城', geo: '云京城北门内' }),
      loc({ name: '南市', geo: '云京城南', mapScope: '云京城' }),
    ]
    const names = city.map((x) => x.name)
    expect(scopeOf(city[0], names)).toBe('')
    expect(scopeOf(loc({ name: '码头', geo: '云京城外三里' }), ['云京城'])).toBe('云京城')
    expect(scopeOf(city[1], names)).toBe('云京城')
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

  it('方位认八个方向，打平或没写就不猜', () => {
    expect(bearingOf(loc({ name: '邪马台', geo: '洛阳东北' }))).toBe(-45)
    expect(bearingOf(loc({ name: '新城', geo: '庇护所以南' }))).toBe(90)
    expect(bearingOf(loc({ name: '港口', mapBearing: '西南' }))).toBe(135)
    expect(bearingOf(loc({ name: '废墟带', geo: '北通备用舱库，南接新城' }))).toBeNull()
    expect(bearingOf(loc({ name: '配给站', geo: '庇护所内' }))).toBeNull()
  })
})

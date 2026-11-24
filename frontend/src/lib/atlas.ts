import type { Location } from '@/mocks'

/** 空间层级：0 是册/中心，往外一层层是内层、中层、外围、城外。 */
export type Tier = 0 | 1 | 2 | 3 | 4

export const TIER_FALLBACK: Record<Tier, string> = {
  0: '核心',
  1: '内层',
  2: '中层',
  3: '外围',
  4: '城外',
}

export const TIER_NOTE: Record<Tier, string> = {
  0: '册与中心',
  1: '最里一道',
  2: '日常所在',
  3: '墙与关口',
  4: '无主之地',
}

/** 设定里可能用的同义词；先匹配到的那个当层级名，比通用名更有味。 */
const TIER_WORDS: Record<Tier, string[]> = {
  0: ['中心', '核心'],
  1: ['内舱', '内城', '内院', '内层'],
  2: ['中区', '中城', '中庭'],
  3: ['外墙', '城墙', '围墙'],
  4: ['墙外', '城外', '荒野'],
}

const NAME_TIER: [RegExp, Tier][] = [
  [/登记室|册房|档案室|议事厅|正厅/, 0],
  [/内舱|内城|内院|内层|地下|舱库|舱门|主任区/, 1],
  [/外墙|城墙|围墙|关隘|城门|哨塔|狙击/, 3],
  [/废墟|走廊|荒野|墙外|城外|尸潮/, 4],
  [/新城|远镇|边城|驿站/, 4],
]

/** 按地点名判层级；名字没线索时只认地形，不拿 geo 猜（「靠近外墙」的医疗棚还在中层）。 */
export function tierOf(loc: Location): Tier {
  const name = loc.name || ''
  for (const [re, tier] of NAME_TIER) if (re.test(name)) return tier
  if (loc.terrain === '废墟') return 4
  if (loc.terrain === '关隘') return 3
  return 2
}

/** 层级名优先用设定自己的词（内舱 / 中区 / 外墙），没有就用通用名。 */
export function tierName(tier: Tier, corpus: string): string {
  for (const word of TIER_WORDS[tier]) if (corpus.includes(word)) return word
  return TIER_FALLBACK[tier]
}

/** 被至少两处地点写进 geo/structure 的地点就是「范围」（整座庇护所），不当地图上的点。 */
export function frameOf(locations: Location[]): Location | null {
  let best: Location | null = null
  let bestHits = 0
  for (const candidate of locations) {
    const name = (candidate.name || '').trim()
    if (name.length < 2) continue
    const hits = locations.filter(
      (other) => other !== candidate && `${other.geo || ''} ${other.structure || ''}`.includes(name),
    ).length
    if (hits > bestHits) {
      bestHits = hits
      best = candidate
    }
  }
  return bestHits >= 2 ? best : null
}

/** 从 geo / structure 读一个明确方位（0=东，90=南）；读不出或两个方向打平就返回 null。 */
export function bearingOf(loc: Location): number | null {
  const raw = `${loc.name || ''} ${loc.geo || ''} ${loc.structure || ''}`
  const count = (ch: string) => (raw.match(new RegExp(ch, 'g')) || []).length
  const dirs: [number, number][] = [
    [90, count('南')],
    [-90, count('北')],
    [0, count('东')],
    [180, count('西')],
  ]
  const top = Math.max(...dirs.map(([, n]) => n))
  if (!top) return null
  const hits = dirs.filter(([, n]) => n === top)
  return hits.length === 1 ? hits[0][0] : null
}

import type { Location } from '@/mocks'

/** 地图怎么排：地点有坐标就按坐标，没坐标就按设定层级套圈。 */
export type MapMode = 'coords' | 'layers'

/** 一层：key 用来分组，name 给人看，order 由内到外。 */
export type MapLayer = { key: string; name: string; order: number }

/** 层级词：0 最里，4 最外。只认空间词，不认题材。 */
const RANK_WORDS: RegExp[] = [
  /核心|中心|中央|正中|主城|正殿|主殿|总坛/,
  /内城|内门|内院|内层|内舱|里坊|宫内|地下/,
  /中城|中区|中层|中庭|城中/,
  /外城|外墙|外围|外门|城墙|城门|关口|近郊|城郊|郊区/,
  /城外|墙外|荒野|野外|境外|海外|边关|废墟|远地|荒原|绝地/,
]
const RANK_NAMES = ['核心', '内层', '中层', '外围', '野外']
/** 设定里真用了哪个词，就拿它当层名。 */
const RANK_ALIASES: string[][] = [
  ['核心', '中心', '中央', '主殿', '正殿'],
  ['内城', '内门', '内院', '内层', '内舱'],
  ['中城', '中区', '中庭', '中层'],
  ['外墙', '城墙', '外城', '外围', '外门', '城门', '关口'],
  ['城外', '墙外', '荒野', '境外', '海外', '废墟'],
]

/** 方位角度按屏幕坐标：0=东、90=南。两字方位先认，免得「东北」拆成东和北。 */
const BEARINGS: [string, number][] = [
  ['东北', -45], ['东南', 45], ['西北', -135], ['西南', 135],
  ['东', 0], ['南', 90], ['西', 180], ['北', -90],
]

/** 「1 内城」「0：核心」这种序号前缀不进层名。 */
export function layerNameOf(raw: string): string {
  return String(raw || '').replace(/^\s*\d+\s*[.、:：\-—]?\s*/, '').trim()
}

function rankOfName(raw: string): number | null {
  const name = layerNameOf(raw)
  for (let i = 0; i < RANK_WORDS.length; i += 1) if (RANK_WORDS[i].test(name)) return i
  return null
}

/** 名字 / geo / structure 里的层级词；读不出返回 null。 */
export function autoLayerRank(loc: Location): number | null {
  const rank = rankOfText(`${loc.name || ''} ${loc.geo || ''} ${loc.structure || ''}`)
  if (rank != null) return rank
  if (loc.terrain === '废墟') return 4
  if (loc.terrain === '关隘') return 3
  return null
}

function rankOfText(raw: string): number | null {
  for (let i = 0; i < RANK_WORDS.length; i += 1) if (RANK_WORDS[i].test(raw)) return i
  return null
}

/** 范围正文按顺序写「中区（配给站…）」时，用地名前面最近的那个层词定层。 */
export function layerRankInFrame(loc: Location, frame?: Location | null): number | null {
  const name = (loc.name || '').trim()
  if (!frame || name.length < 2) return null
  let rank: number | null = null
  for (const clause of `${frame.structure || ''}\n${frame.geo || ''}`.split(
    /[，,。；;、\n（）()【】「」]/,
  )) {
    const hit = rankOfText(clause)
    if (hit != null) rank = hit
    if (rank != null && clause.includes(name)) return rank
  }
  return null
}

function layerRankOf(loc: Location, frame?: Location | null): number | null {
  return autoLayerRank(loc) ?? layerRankInFrame(loc, frame)
}

/** 这本书出现过哪些层，由内到外。没有层级信息就返回空数组。 */
export function layersOf(locations: Location[], frame?: Location | null): MapLayer[] {
  const seen = new Map<string, MapLayer>()
  for (const loc of locations) {
    const raw = (loc.mapLayer || '').trim()
    if (!raw) continue
    const name = layerNameOf(raw) || raw
    if (seen.has(name)) continue
    const digit = Number(raw.match(/^\s*(\d+)/)?.[1])
    seen.set(name, {
      key: name,
      name,
      order: Number.isFinite(digit) ? digit : rankOfName(name) ?? seen.size,
    })
  }
  if (seen.size) return [...seen.values()].sort((a, b) => a.order - b.order)

  const corpus = [...locations, ...(frame ? [frame] : [])]
    .map((l) => `${l.name || ''} ${l.geo || ''} ${l.structure || ''}`)
    .join(' ')
  const ranks = new Set<number>()
  for (const loc of locations) {
    const rank = layerRankOf(loc, frame)
    if (rank != null) ranks.add(rank)
  }
  return [...ranks].sort((a, b) => a - b).map((rank) => ({
    key: `rank:${rank}`,
    name: RANK_ALIASES[rank].find((w) => corpus.includes(w)) ?? RANK_NAMES[rank],
    order: rank,
  }))
}

/** 地点落在哪一层；写了 mapLayer 的只认 mapLayer，没写的按名字猜。 */
export function layerOf(loc: Location, layers: MapLayer[], frame?: Location | null): MapLayer | null {
  const raw = (loc.mapLayer || '').trim()
  if (raw) return layers.find((l) => l.key === (layerNameOf(raw) || raw)) ?? null
  const rank = layerRankOf(loc, frame)
  if (rank == null) return null
  return layers.find((l) => l.key === `rank:${rank}`) ?? null
}

/** 地点属于哪个范围：显式 mapScope 优先，否则看 geo/structure 提到了哪个地点名。 */
export function scopeOf(loc: Location, names: string[]): string {
  const explicit = (loc.mapScope || '').trim()
  if (explicit) return explicit
  const raw = `${loc.geo || ''} ${loc.structure || ''}`
  let best = ''
  for (const name of names) {
    if (name.length < 2 || name === loc.name || name.length <= best.length) continue
    if (raw.includes(name)) best = name
  }
  return best
}

/** 被至少两处地点写进 geo/structure 的地点就是「范围」（整座城/庇护所），不当地图上的点。 */
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

function bearingText(raw: string): number | null {
  let rest = raw
  const hits: [number, number][] = []
  for (const [word, deg] of BEARINGS) {
    if (word.length < 2) continue
    const n = rest.split(word).length - 1
    if (!n) continue
    hits.push([deg, n])
    rest = rest.split(word).join(' ')
  }
  for (const [word, deg] of BEARINGS) {
    if (word.length > 1) continue
    const n = rest.split(word).length - 1
    if (n) hits.push([deg, n])
  }
  if (!hits.length) return null
  const totals = new Map<number, number>()
  for (const [deg, n] of hits) totals.set(deg, (totals.get(deg) ?? 0) + n)
  const top = Math.max(...totals.values())
  const best = [...totals].filter(([, n]) => n === top)
  return best.length === 1 ? best[0][0] : null
}

/** 从 mapBearing / geo / structure 读一个明确方位；读不出或两个方向打平就返回 null。 */
export function bearingOf(loc: Location): number | null {
  const explicit = bearingText((loc.mapBearing || '').trim())
  if (explicit != null) return explicit
  return bearingText(`${loc.name || ''} ${loc.geo || ''} ${loc.structure || ''}`)
}

/** 有层就套圈；没有层但至少两处给了坐标，就按平面地理摆。 */
export function mapMode(locations: Location[], frame?: Location | null): MapMode {
  if (layersOf(locations, frame).length >= 2) return 'layers'
  return locations.filter((l) => l.mapX || l.mapY).length >= 2 ? 'coords' : 'layers'
}

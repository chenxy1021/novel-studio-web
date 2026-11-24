<script setup lang="ts">
/**
 * 世界观地图：把地点按「大致方位 + 地形」摊到一张区域图上。
 *
 * 没有真实经纬度，所以坐标来源分两种：
 * 1. 设定里写了 mapX/mapY（0–100，西→东 / 北→南）就直接用；
 * 2. 没写就按 geo / 结构 / 正文里的方位词（东、西、南、北、河、山…）推断，
 *    再用一次确定性的松弛把重叠的点推开。同一本书每次打开的布局一致。
 *
 * 图上画海岸、河流、山脊、林地、势力范围与道路；点地点看注释。所有动效都尊重
 * prefers-reduced-motion。
 */
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { Faction, Location } from '@/mocks'

const props = defineProps<{
  locations: Location[]
  factions: Faction[]
}>()

const router = useRouter()

const W = 1000
const H = 640
const MX = 72
const MY = 62

type Pt = { x: number; y: number }
type Terrain = 'city' | 'town' | 'village' | 'mountain' | 'water' | 'ruin' | 'pass' | 'camp'
type Anchor = 'middle' | 'start' | 'end'
type Node = Pt & {
  loc: Location
  terrain: Terrain
  glyph: string
  label: string
  major: boolean
  color: string
  note: string
  owner: string
  labelX: number
  labelY: number
  anchor: Anchor
}

const TERRAIN_GLYPH: Record<Terrain, string> = {
  city: '城', town: '镇', village: '村', mountain: '山',
  water: '水', ruin: '墟', pass: '关', camp: '营',
}
const TERRAIN_LABEL: Record<Terrain, string> = {
  city: '城', town: '镇', village: '村', mountain: '山林',
  water: '水岸', ruin: '废墟', pass: '关隘', camp: '营地',
}

function hashStr(raw: string): number {
  let h = 2166136261
  for (let i = 0; i < raw.length; i += 1) h = Math.imul(h ^ raw.charCodeAt(i), 16777619)
  return Math.abs(h)
}
/** 由字符串派生的稳定随机数（0–1）。 */
function rand(seed: number, salt: number): number {
  let x = (seed ^ Math.imul(salt + 1, 0x9e3779b1)) >>> 0
  x ^= x << 13
  x ^= x >>> 17
  x ^= x << 5
  return ((x >>> 0) % 10000) / 10000
}

function terrainOf(loc: Location): Terrain {
  const raw = `${loc.terrain} ${loc.name} ${loc.geo} ${loc.text} ${loc.structure}`
  if (/水岸|港|渡|码头|河|湖|海|湾|岛/.test(raw)) return 'water'
  if (/山林|山|岭|峰|崖|塔|坡|矿/.test(raw)) return 'mountain'
  if (/废墟|遗址|墓|祠|遗迹|焦土/.test(raw)) return 'ruin'
  if (/关隘|关口|关卡|城门|边关/.test(raw)) return 'pass'
  if (/营地|驻地|寨|军营/.test(raw)) return 'camp'
  if (/城|都城|王城/.test(raw)) return 'city'
  if (/镇|集|市/.test(raw)) return 'town'
  if (/村|庄|屯|巷|街|铺/.test(raw)) return 'village'
  return 'village'
}

const COLORS = ['#b4543f', '#3f6d7a', '#8a6a2f', '#4b6b45', '#7a4d6d', '#5a5f8a', '#8a5a3f', '#3f7a6a']

function factionColor(name: string): string {
  return COLORS[hashStr(name) % COLORS.length]
}

function directionSeed(loc: Location): { x: number; y: number } {
  const raw = `${loc.name}${loc.geo}${loc.structure}${loc.text}${loc.owner}${loc.events}`
  const count = (re: RegExp) => (raw.match(re) || []).length
  const e = count(/东/g)
  const w = count(/西/g)
  const n = count(/北/g)
  const s = count(/南/g)
  const middle = count(/中|央|城心|中心/g)
  const h = hashStr(loc.name)
  const jx = (rand(h, 1) - 0.5) * 18
  const jy = (rand(h, 2) - 0.5) * 18
  let x = 50 + jx
  let y = 50 + jy
  if (e > w) x = 74 + jx * 0.5
  else if (w > e) x = 26 + jx * 0.5
  if (n > s) y = 27 + jy * 0.5
  else if (s > n) y = 73 + jy * 0.5
  if (middle) {
    x = 50 + jx * 0.4
    y = 50 + jy * 0.4
  }
  return {
    x: Math.min(94, Math.max(6, x)),
    y: Math.min(92, Math.max(8, y)),
  }
}

function toPt(xPct: number, yPct: number): Pt {
  return {
    x: MX + (Math.min(100, Math.max(0, xPct)) / 100) * (W - MX * 2),
    y: MY + (Math.min(100, Math.max(0, yPct)) / 100) * (H - MY * 2),
  }
}

const nodes = computed<Node[]>(() => {
  const factionNames = props.factions.map((f) => f.name).filter(Boolean)
  const ownerOf = (loc: Location) => {
    for (const name of factionNames) if (loc.owner.includes(name)) return name
    return loc.owner.split(/[、,，/;；|]/)[0]?.trim() || ''
  }

  const raw = props.locations.map((loc, i) => {
    const hasCoords = loc.mapX > 0 && loc.mapY > 0
    const seed = hasCoords ? null : directionSeed(loc)
    const pt = hasCoords ? toPt(loc.mapX, loc.mapY) : toPt(seed!.x, seed!.y)
    const owner = ownerOf(loc)
    const terrain = terrainOf(loc)
    const major = i < 6 || Boolean(owner && factionNames.includes(owner))
    return {
      loc,
      x: pt.x,
      y: pt.y,
      ax: pt.x,
      ay: pt.y,
      terrain,
      glyph: TERRAIN_GLYPH[terrain],
      label: loc.name,
      major,
      color: owner ? factionColor(owner) : '#6a6257',
      note: loc.state || loc.owner || '',
      owner,
      labelX: pt.x,
      labelY: pt.y - 16,
      anchor: 'middle' as Anchor,
      fixed: hasCoords,
      /** 设定里写过坐标；即使挤成一团被迫散开，也不要离开原锚点太远。 */
      anchored: hasCoords,
    }
  })

  // AI 常把一批地点写成几乎同一个坐标。这种「有坐标但挤成一团」的点按无坐标处理，
  // 交给下面的松弛排开，否则六个地点会叠在一个像素上。
  for (const a of raw) {
    if (!a.fixed) continue
    for (const b of raw) {
      if (b === a) continue
      if (Math.hypot(b.x - a.x, b.y - a.y) < 26) {
        a.fixed = false
        break
      }
    }
  }

  // 松弛：把叠在一起的点推开。仍固定在锚点上的点只做小幅漂移（离锚点 ≤ 34），
  // 其余按迭代散开。
  const MIN_D = 74
  const DRIFT = 34
  const SOFT_DRIFT = 140
  for (let round = 0; round < 60; round += 1) {
    let moved = false
    for (let i = 0; i < raw.length; i += 1) {
      for (let j = i + 1; j < raw.length; j += 1) {
        const a = raw[i]
        const b = raw[j]
        let dx = b.x - a.x
        let dy = b.y - a.y
        let d = Math.hypot(dx, dy)
        if (d >= MIN_D) continue
        if (d < 0.01) {
          dx = 1
          dy = 0.6
          d = 1
        }
        const push = (MIN_D - d) / 2 + 0.5
        const ux = dx / d
        const uy = dy / d
        if (!a.fixed) {
          a.x -= ux * push
          a.y -= uy * push
        } else if (Math.hypot(a.x - a.ax, a.y - a.ay) < DRIFT) {
          a.x -= ux * push * 0.45
          a.y -= uy * push * 0.45
        }
        if (!b.fixed) {
          b.x += ux * push
          b.y += uy * push
        } else if (Math.hypot(b.x - b.ax, b.y - b.ay) < DRIFT) {
          b.x += ux * push * 0.45
          b.y += uy * push * 0.45
        }
        moved = true
      }
    }
    for (const p of raw) {
      p.x = Math.min(W - MX * 0.5, Math.max(MX * 0.5, p.x))
      p.y = Math.min(H - MY * 0.5, Math.max(MY * 0.5, p.y))
      const limit = p.fixed ? DRIFT : p.anchored ? SOFT_DRIFT : Infinity
      if (limit < Infinity) {
        const dx = p.x - p.ax
        const dy = p.y - p.ay
        const dist = Math.hypot(dx, dy)
        if (dist > limit) {
          p.x = p.ax + (dx / dist) * limit
          p.y = p.ay + (dy / dist) * limit
        }
      }
    }
    if (!moved) break
  }

  // 标注避让：先给主要地点挑位置，依次试「上 / 下 / 右 / 左」，和已放标注的
  // 估计外框不重叠才用。宁可少避一点，也不让名字压住别的点。
  type Box = { x0: number; x1: number; y0: number; y1: number }
  const placed: Box[] = []
  const ordered = [...raw].sort((a, b) => Number(b.major) - Number(a.major) || a.y - b.y)
  for (const n of ordered) {
    // 地名只做小字标注，点开才看完整资料；字号跟 .wa-pin__label 的 CSS 对齐。
    const fs = n.major ? 10.5 : 9.5
    const w = Math.max(22, n.label.length * fs * 0.95)
    const h = fs + 3
    const candidates: { dx: number; dy: number; anchor: Anchor }[] = [
      { dx: 0, dy: -11, anchor: 'middle' },
      { dx: 0, dy: 18, anchor: 'middle' },
      { dx: 12, dy: 3.5, anchor: 'start' },
      { dx: -12, dy: 3.5, anchor: 'end' },
    ]
    const boxOf = (c: { dx: number; dy: number; anchor: Anchor }): Box => {
      const x = n.x + c.dx
      const x0 = c.anchor === 'middle' ? x - w / 2 : c.anchor === 'start' ? x : x - w
      return { x0, x1: x0 + w, y0: n.y + c.dy - h, y1: n.y + c.dy + 2 }
    }
    const pick = candidates.find((c) => {
      const b = boxOf(c)
      return !placed.some((p) => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0)
    }) ?? candidates[0]
    const box = boxOf(pick)
    placed.push(box)
    n.labelX = n.x + pick.dx
    n.labelY = n.y + pick.dy
    n.anchor = pick.anchor
  }
  return raw
})

/* ------------------------------ 地形 ------------------------------ */

function smoothThrough(pts: Pt[]): string {
  if (!pts.length) return ''
  if (pts.length === 1) return `M ${pts[0].x} ${pts[0].y}`
  let d = `M ${pts[0].x.toFixed(1)} ${pts[0].y.toFixed(1)}`
  for (let i = 1; i < pts.length - 1; i += 1) {
    const mx = (pts[i].x + pts[i + 1].x) / 2
    const my = (pts[i].y + pts[i + 1].y) / 2
    d += ` Q ${pts[i].x.toFixed(1)} ${pts[i].y.toFixed(1)} ${mx.toFixed(1)} ${my.toFixed(1)}`
  }
  const last = pts[pts.length - 1]
  d += ` T ${last.x.toFixed(1)} ${last.y.toFixed(1)}`
  return d
}

/** 大陆轮廓：一圈带正弦扰动的闭合路径，看起来像手绘海岸线。 */
const landPath = computed(() => {
  const seed = hashStr(props.locations.map((l) => l.name).join('|') || 'empty')
  const pts: Pt[] = []
  const step = 46
  const edge = (x0: number, y0: number, x1: number, y1: number, phase: number) => {
    const len = Math.hypot(x1 - x0, y1 - y0)
    const n = Math.max(2, Math.round(len / step))
    for (let i = 0; i < n; i += 1) {
      const t = i / n
      const wobble = Math.sin((t + phase) * Math.PI * 3.2) * 15 + (rand(seed, i + Math.round(phase * 100)) - 0.5) * 10
      const nx = -(y1 - y0) / len
      const ny = (x1 - x0) / len
      pts.push({ x: x0 + (x1 - x0) * t + nx * wobble, y: y0 + (y1 - y0) * t + ny * wobble })
    }
  }
  edge(26, 18, W - 20, 24, 0.1)
  edge(W - 20, 24, W - 12, H - 24, 0.45)
  edge(W - 12, H - 24, 28, H - 14, 0.8)
  edge(28, H - 14, 26, 18, 1.15)
  return `${smoothThrough(pts)} Z`
})

const waterNodes = computed(() => nodes.value.filter((n) => n.terrain === 'water'))
const mountainNodes = computed(() => nodes.value.filter((n) => n.terrain === 'mountain'))
const forestNodes = computed(() => nodes.value.filter((n) => n.terrain === 'village' || n.terrain === 'camp'))

const riverPath = computed(() => {
  const pts = [...waterNodes.value].sort((a, b) => a.x - b.x)
  if (!pts.length) return ''
  if (pts.length === 1) {
    const p = pts[0]
    return smoothThrough([
      { x: p.x - 210, y: p.y - 150 },
      { x: p.x - 60, y: p.y - 40 },
      { x: p.x, y: p.y },
      { x: p.x + 90, y: p.y + 60 },
      { x: p.x + 230, y: p.y + 170 },
    ])
  }
  const first = pts[0]
  const last = pts[pts.length - 1]
  return smoothThrough([
    { x: first.x - 180, y: Math.max(20, first.y - 120) },
    ...pts,
    { x: last.x + 190, y: Math.min(H - 20, last.y + 130) },
  ])
})

/** 海岸线附近画几道波纹，暗示水域。 */
const waves = computed(() => {
  const seed = hashStr('waves' + props.locations.length)
  return Array.from({ length: 9 }, (_, i) => ({
    x: 30 + rand(seed, i) * (W - 100),
    y: 30 + rand(seed, i + 40) * (H - 70),
    w: 40 + rand(seed, i + 80) * 70,
    o: 0.06 + rand(seed, i + 120) * 0.08,
  }))
})

const ridgePath = computed(() => {
  const ms = [...mountainNodes.value].sort((a, b) => a.x - b.x)
  if (ms.length < 2) return ''
  return smoothThrough(ms.map((m, i) => ({ x: m.x, y: m.y + (i % 2 ? 26 : -14) })))
})

function mountainPeaks(n: Node): { x: number; y: number; s: number }[] {
  const seed = hashStr(n.loc.name)
  return Array.from({ length: 3 }, (_, i) => ({
    x: n.x - 26 + i * 24 + rand(seed, i) * 8,
    y: n.y - 6 + rand(seed, i + 9) * 10,
    s: 12 + rand(seed, i + 20) * 9,
  }))
}

function trees(n: Node): { x: number; y: number; s: number }[] {
  const seed = hashStr(n.loc.name + 'tree')
  return Array.from({ length: 5 }, (_, i) => ({
    x: n.x - 34 + rand(seed, i) * 68,
    y: n.y + 8 + rand(seed, i + 11) * 26,
    s: 5 + rand(seed, i + 22) * 4,
  }))
}

/* ------------------------------ 势力范围 / 道路 ------------------------------ */

function friendlyOwner(loc: Location): string {
  const names = props.factions.map((f) => f.name).filter(Boolean)
  for (const name of names) if (loc.owner.includes(name)) return name
  return loc.owner.split(/[、,，/;；|]/)[0]?.trim() || ''
}

function convexHull(points: Pt[]): Pt[] {
  const pts = [...points].sort((a, b) => a.x - b.x || a.y - b.y)
  if (pts.length < 3) return pts
  const cross = (o: Pt, a: Pt, b: Pt) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)
  const lower: Pt[] = []
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop()
    lower.push(p)
  }
  const upper: Pt[] = []
  for (let i = pts.length - 1; i >= 0; i -= 1) {
    const p = pts[i]
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop()
    upper.push(p)
  }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)]
}

const regions = computed(() => {
  const map = new Map<string, Node[]>()
  for (const n of nodes.value) {
    const owner = friendlyOwner(n.loc)
    if (!owner) continue
    map.set(owner, [...(map.get(owner) ?? []), n])
  }
  return [...map.entries()]
    .filter(([, list]) => list.length >= 2)
    .map(([name, list]) => {
      const cx = list.reduce((s, p) => s + p.x, 0) / list.length
      const cy = list.reduce((s, p) => s + p.y, 0) / list.length
      const padded = list.map((p) => {
        const dx = p.x - cx
        const dy = p.y - cy
        const d = Math.hypot(dx, dy) || 1
        return { x: p.x + (dx / d) * 46, y: p.y + (dy / d) * 46 }
      })
      const hull = convexHull(padded)
      const path = hull.length >= 3 ? `${smoothThrough(hull)} Z` : ''
      return { name, path, cx, cy, color: factionColor(name), count: list.length }
    })
    .filter((r) => r.path)
})

type Road = { d: string; kind: 'road' | 'trail'; from: string; to: string }
const roads = computed<Road[]>(() => {
  const ns = nodes.value
  if (ns.length < 2) return []
  const edges: { i: number; j: number; d: number }[] = []
  for (let i = 0; i < ns.length; i += 1) {
    for (let j = i + 1; j < ns.length; j += 1) {
      edges.push({ i, j, d: Math.hypot(ns[i].x - ns[j].x, ns[i].y - ns[j].y) })
    }
  }
  edges.sort((a, b) => a.d - b.d)
  const parent = ns.map((_, i) => i)
  const find = (x: number): number => (parent[x] === x ? x : (parent[x] = find(parent[x])))
  const out: Road[] = []
  for (const e of edges) {
    const a = find(e.i)
    const b = find(e.j)
    if (a === b) continue
    parent[a] = b
    const p = ns[e.i]
    const q = ns[e.j]
    const mx = (p.x + q.x) / 2
    const my = (p.y + q.y) / 2
    const dx = q.x - p.x
    const dy = q.y - p.y
    const len = Math.hypot(dx, dy) || 1
    const bend = (rand(hashStr(p.loc.name + q.loc.name), 3) - 0.5) * 90
    const cx = mx - (dy / len) * bend
    const cy = my + (dx / len) * bend
    out.push({
      d: `M ${p.x.toFixed(1)} ${p.y.toFixed(1)} Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${q.x.toFixed(1)} ${q.y.toFixed(1)}`,
      kind: p.terrain === 'mountain' || q.terrain === 'mountain' ? 'trail' : 'road',
      from: p.label,
      to: q.label,
    })
    if (out.length >= ns.length - 1) break
  }
  return out
})

const mainRoad = computed(() => [...roads.value].sort((a, b) => b.d.length - a.d.length)[0]?.d ?? '')

/* ------------------------------ 交互 ------------------------------ */

const selected = ref<Location | null>(null)
const hover = ref<string>('')
const sideQ = ref('')
const vb = reactive({ x: 0, y: 0, w: W, h: H })
const dragging = ref(false)
let dragStart: { x: number; y: number; vb: { x: number; y: number } } | null = null

function clampVb() {
  vb.w = Math.min(W * 1.4, Math.max(W * 0.32, vb.w))
  vb.h = vb.w * (H / W)
  // 至少留 18% 画布和大陆重叠，既能略微越界看海，又不会把边缘地点移出视野。
  const mx = vb.w * 0.18
  const my = vb.h * 0.18
  vb.x = Math.min(W - vb.w + mx, Math.max(-mx, vb.x))
  vb.y = Math.min(H - vb.h + my, Math.max(-my, vb.y))
}

function zoom(factor: number) {
  const cx = vb.x + vb.w / 2
  const cy = vb.y + vb.h / 2
  const w = vb.w * factor
  vb.w = w
  vb.h = w * (H / W)
  vb.x = cx - vb.w / 2
  vb.y = cy - vb.h / 2
  clampVb()
}

function resetView() {
  vb.x = 0
  vb.y = 0
  vb.w = W
  vb.h = H
}

/** 把地图移到一个地点上，用于左侧索引点击。 */
function focusOn(n: Node) {
  const w = W * 0.5
  vb.w = w
  vb.h = w * (H / W)
  vb.x = n.x - vb.w / 2
  vb.y = n.y - vb.h / 2
  clampVb()
}

function selectNode(n: Node, center = false) {
  selected.value = n.loc
  if (center) focusOn(n)
}

function onDblClick(e: MouseEvent) {
  const el = e.currentTarget as SVGSVGElement
  const box = el.getBoundingClientRect()
  const px = vb.x + ((e.clientX - box.left) / box.width) * vb.w
  const py = vb.y + ((e.clientY - box.top) / box.height) * vb.h
  vb.w = Math.max(W * 0.32, vb.w * 0.7)
  vb.h = vb.w * (H / W)
  vb.x = px - vb.w / 2
  vb.y = py - vb.h / 2
  clampVb()
}

/** 只在按住 ⌘ / Ctrl 时接管滚轮，避免抢页面滚动。 */
function onWheel(e: WheelEvent) {
  if (!e.ctrlKey && !e.metaKey) return
  e.preventDefault()
  zoom(e.deltaY > 0 ? 1.12 : 0.89)
}

function onPointerDown(e: PointerEvent) {
  const el = e.currentTarget as SVGSVGElement
  dragging.value = true
  dragStart = { x: e.clientX, y: e.clientY, vb: { x: vb.x, y: vb.y } }
  el.setPointerCapture?.(e.pointerId)
}

function onPointerMove(e: PointerEvent) {
  if (!dragging.value || !dragStart) return
  const el = e.currentTarget as SVGSVGElement
  const box = el.getBoundingClientRect()
  const scale = vb.w / box.width
  vb.x = dragStart.vb.x - (e.clientX - dragStart.x) * scale
  vb.y = dragStart.vb.y - (e.clientY - dragStart.y) * scale
  clampVb()
}

function onPointerUp() {
  dragging.value = false
  dragStart = null
}

watch(
  () => props.locations,
  () => {
    selected.value = null
    resetView()
  },
)

const nodeByName = computed(() => new Map(nodes.value.map((n) => [n.loc.name, n])))
const selectedNode = computed(() => (selected.value ? nodeByName.value.get(selected.value.name) ?? null : null))

const legend = computed(() => {
  const seen = new Map<string, { name: string; color: string; count: number }>()
  for (const n of nodes.value) {
    const owner = friendlyOwner(n.loc)
    if (!owner) continue
    const hit = seen.get(owner) ?? { name: owner, color: n.color, count: 0 }
    hit.count += 1
    seen.set(owner, hit)
  }
  return [...seen.values()].sort((a, b) => b.count - a.count)
})

const zoomLabel = computed(() => `${Math.round((W / vb.w) * 100)}%`)

/** 左栏按归属分组，方便地点多时直接找人。 */
const sideGroups = computed(() => {
  const needle = sideQ.value.trim()
  const map = new Map<string, Node[]>()
  for (const n of nodes.value) {
    if (
      needle &&
      ![n.label, n.owner, n.note, TERRAIN_LABEL[n.terrain]].join(' ').includes(needle)
    ) {
      continue
    }
    const key = n.owner || '未归属'
    map.set(key, [...(map.get(key) ?? []), n])
  }
  return [...map.entries()]
    .map(([name, list]) => ({
      name,
      color: list[0].color,
      list: [...list].sort((a, b) => a.label.localeCompare(b.label, 'zh')),
    }))
    .sort((a, b) => {
      if (a.name === '未归属') return 1
      if (b.name === '未归属') return -1
      return b.list.length - a.list.length || a.name.localeCompare(b.name, 'zh')
    })
})

function openSetup() {
  void router.push({ name: 'setup', query: { tab: 'locations' } })
}
</script>

<template>
  <div class="wa">
    <div v-if="!locations.length" class="wa__empty">
      <b>地图还是空的</b>
      <p>地点在「设定」页从大纲和世界观里拆出来；生成后地图会按方位和地形自动排布。</p>
      <button type="button" class="wa__link" @click="openSetup">去设定页 →</button>
    </div>

    <template v-else>
      <div class="wa__body">
        <aside class="wa__side" aria-label="地点索引">
          <div class="wa__sidehead">
            <span class="ns-eyebrow">地点索引</span>
            <span class="ns-num">{{ locations.length }}</span>
          </div>
          <input
            v-model="sideQ"
            class="wa__search"
            placeholder="搜地点 / 势力…"
            aria-label="搜索地点"
          />
          <div class="wa__lists">
            <section v-for="g in sideGroups" :key="g.name" class="wa__group">
              <header class="wa__grouphead">
                <i :style="{ background: g.color }" aria-hidden="true" />
                <b>{{ g.name }}</b>
                <span class="ns-num">{{ g.list.length }}</span>
              </header>
              <button
                v-for="n in g.list"
                :key="n.loc.id"
                type="button"
                class="wa__item"
                :class="{ on: selected?.id === n.loc.id, hot: hover === n.loc.id }"
                @click="selectNode(n, true)"
                @mouseenter="hover = n.loc.id"
                @mouseleave="hover = ''"
              >
                <span class="wa__itemglyph">{{ n.glyph }}</span>
                <span class="wa__itemname">{{ n.label }}</span>
                <span class="wa__itemterrain">{{ TERRAIN_LABEL[n.terrain] }}</span>
              </button>
            </section>
            <p v-if="!sideGroups.length" class="wa__nomatch">没有匹配的地点</p>
          </div>
        </aside>

        <div class="wa__frame">
          <div class="wa__bar">
            <span class="wa__title">区域舆图 · {{ locations.length }} 处</span>
            <span class="wa__hint">拖动平移 · 双击放大 · ⌘/Ctrl 滚轮缩放</span>
            <span class="wa__zoomlabel ns-num">{{ zoomLabel }}</span>
            <div class="wa__zoom">
              <button type="button" aria-label="放大" @click="zoom(0.8)">＋</button>
              <button type="button" aria-label="缩小" @click="zoom(1.25)">－</button>
              <button type="button" class="wa__reset" @click="resetView">复位</button>
            </div>
          </div>

        <div class="wa__canvas" :class="{ 'is-dragging': dragging }">
          <svg
            :viewBox="`${vb.x} ${vb.y} ${vb.w} ${vb.h}`"
            role="img"
            aria-label="世界观区域地图"
            @pointerdown="onPointerDown"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointercancel="onPointerUp"
            @pointerleave="onPointerUp"
            @dblclick="onDblClick"
            @wheel="onWheel"
          >
            <defs>
              <linearGradient id="wa-sea" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#dfe6df" />
                <stop offset="100%" stop-color="#c9d6d2" />
              </linearGradient>
              <linearGradient id="wa-land" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stop-color="#f4eddd" />
                <stop offset="55%" stop-color="#efe5d0" />
                <stop offset="100%" stop-color="#e7dac1" />
              </linearGradient>
              <radialGradient id="wa-vignette" cx="50%" cy="45%" r="72%">
                <stop offset="60%" stop-color="rgba(90,70,40,0)" />
                <stop offset="100%" stop-color="rgba(90,70,40,0.18)" />
              </radialGradient>
              <filter id="wa-grain">
                <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="7" result="n" />
                <feColorMatrix in="n" type="saturate" values="0" />
                <feComponentTransfer><feFuncA type="linear" slope="0.06" /></feComponentTransfer>
              </filter>
              <filter id="wa-glow" x="-60%" y="-60%" width="220%" height="220%">
                <feGaussianBlur stdDeviation="5" result="b" />
                <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
              </filter>
              <pattern id="wa-grid" width="50" height="50" patternUnits="userSpaceOnUse">
                <path d="M 50 0 L 0 0 0 50" fill="none" stroke="#8d7a5c" stroke-width="0.5" />
              </pattern>
              <clipPath id="wa-landclip">
                <path :d="landPath" />
              </clipPath>
            </defs>

            <rect :x="-W * 0.3" :y="-H * 0.3" :width="W * 1.6" :height="H * 1.6" fill="url(#wa-sea)" />
            <g class="wa-waves">
              <path
                v-for="(w, i) in waves"
                :key="`w-${i}`"
                :d="`M ${w.x} ${w.y} q ${w.w / 2} -6 ${w.w} 0`"
                :opacity="w.o"
              />
            </g>

            <path :d="landPath" fill="url(#wa-land)" stroke="#b9a582" stroke-width="2.4" />
            <rect
              :x="-W * 0.3"
              :y="-H * 0.3"
              :width="W * 1.6"
              :height="H * 1.6"
              fill="url(#wa-grid)"
              opacity="0.2"
              clip-path="url(#wa-landclip)"
            />

            <g class="wa-regions">
              <path
                v-for="r in regions"
                :key="`region-${r.name}`"
                :d="r.path"
                :fill="r.color"
                fill-opacity="0.09"
                :stroke="r.color"
                stroke-opacity="0.4"
                stroke-width="1.4"
                stroke-dasharray="7 6"
              />
              <text
                v-for="r in regions"
                :key="`rl-${r.name}`"
                class="wa-region-label"
                :x="r.cx"
                :y="r.cy - 4"
                :fill="r.color"
              >{{ r.name }}</text>
            </g>

            <ellipse
              v-if="waterNodes.length === 1"
              :cx="waterNodes[0].x"
              :cy="waterNodes[0].y"
              rx="34"
              ry="17"
              class="wa-lake"
            />
            <g v-if="riverPath">
              <path :d="riverPath" class="wa-river__bank" />
              <path :d="riverPath" class="wa-river" />
              <path :d="riverPath" class="wa-river__flow" />
            </g>
            <path v-if="ridgePath" :d="ridgePath" class="wa-ridge" />

            <g class="wa-mountains">
              <g v-for="n in mountainNodes" :key="`m-${n.loc.id}`">
                <ellipse :cx="n.x" :cy="n.y + 8" rx="46" ry="25" class="wa-contour" />
                <ellipse :cx="n.x" :cy="n.y + 8" rx="64" ry="35" class="wa-contour wa-contour--outer" />
                <path
                  v-for="(p, i) in mountainPeaks(n)"
                  :key="`mp-${i}`"
                  :d="`M ${p.x - p.s} ${p.y} L ${p.x} ${p.y - p.s} L ${p.x + p.s} ${p.y} Z`"
                  class="wa-peak"
                />
              </g>
            </g>

            <g class="wa-forests">
              <g v-for="n in forestNodes" :key="`f-${n.loc.id}`">
                <g v-for="(t, i) in trees(n)" :key="`t-${i}`">
                  <path :d="`M ${t.x} ${t.y - t.s * 1.8} L ${t.x - t.s} ${t.y} L ${t.x + t.s} ${t.y} Z`" class="wa-tree" />
                  <line :x1="t.x" :y1="t.y" :x2="t.x" :y2="t.y + t.s * 0.7" class="wa-trunk" />
                </g>
              </g>
            </g>

            <g class="wa-roads">
              <path
                v-for="(r, i) in roads"
                :key="`r-${i}`"
                :d="r.d"
                class="wa-road"
                :class="`wa-road--${r.kind}`"
              />
            </g>

            <g class="wa-pins">
              <g
                v-for="n in nodes"
                :key="n.loc.id"
                class="wa-pin"
                :class="{
                  'wa-pin--on': selected?.id === n.loc.id,
                  'wa-pin--major': n.major,
                  'wa-pin--hot': hover === n.loc.id,
                }"
                :transform="`translate(${n.x}, ${n.y})`"
                role="button"
                tabindex="0"
                :aria-label="`${n.label}${n.loc.owner ? `，${n.loc.owner}` : ''}`"
                @pointerdown.stop
                @click.stop="selectNode(n)"
                @keydown.enter.prevent="selectNode(n)"
                @keydown.space.prevent="selectNode(n)"
                @mouseenter="hover = n.loc.id"
                @mouseleave="hover = ''"
              >
                <title>{{ n.label }}{{ n.owner ? ` · ${n.owner}` : '' }}{{ n.note ? ` · ${n.note}` : '' }}</title>
                <circle v-if="selected?.id === n.loc.id" class="wa-pin__ring" r="17" :stroke="n.color" />
                <circle class="wa-pin__halo" r="12" :fill="n.color" />
                <circle class="wa-pin__dot" r="5" :fill="n.color" />
                <text class="wa-pin__glyph" y="4" text-anchor="middle">{{ n.glyph }}</text>
                <text
                  class="wa-pin__label"
                  :class="{ 'wa-pin__label--major': n.major }"
                  :x="n.labelX - n.x"
                  :y="n.labelY - n.y"
                  :text-anchor="n.anchor"
                >{{ n.label }}</text>
              </g>
            </g>

            <g class="wa-compass" :transform="`translate(${W - 74}, 86)`">
              <circle r="26" class="wa-compass__ring" />
              <path d="M 0 -20 L 7 4 L 0 0 L -7 4 Z" class="wa-compass__needle" />
              <text y="-30" text-anchor="middle" class="wa-compass__n">北</text>
            </g>
            <g class="wa-scale" :transform="`translate(${MX}, ${H - 34})`">
              <line x1="0" y1="0" x2="90" y2="0" />
              <line x1="0" y1="-4" x2="0" y2="4" />
              <line x1="90" y1="-4" x2="90" y2="4" />
              <text x="0" y="16">约一日脚程</text>
            </g>

            <circle v-if="mainRoad" class="wa-traveler" r="4">
              <animateMotion :path="mainRoad" dur="16s" repeatCount="indefinite" rotate="auto" />
            </circle>

            <rect :x="-W * 0.3" :y="-H * 0.3" :width="W * 1.6" :height="H * 1.6" fill="url(#wa-vignette)" pointer-events="none" />
            <rect :x="-W * 0.3" :y="-H * 0.3" :width="W * 1.6" :height="H * 1.6" filter="url(#wa-grain)" opacity="0.5" pointer-events="none" />
          </svg>

          <div class="wa-fog wa-fog--a" aria-hidden="true" />
          <div class="wa-fog wa-fog--b" aria-hidden="true" />

          <div v-if="legend.length" class="wa-legend">
            <span v-for="l in legend" :key="l.name" class="wa-legend__item">
              <i :style="{ background: l.color }" />{{ l.name }}<small class="ns-num">{{ l.count }}</small>
            </span>
          </div>

          <aside v-if="selected" class="wa-card">
            <header class="wa-card__head">
              <div>
                <span class="ns-eyebrow">{{ selectedNode?.terrain ? selectedNode.glyph : '地点' }} · {{ selected.owner || '无归属' }}</span>
                <h3>{{ selected.name }}</h3>
              </div>
              <button type="button" class="wa-card__close" aria-label="关闭" @click="selected = null">×</button>
            </header>
            <p v-if="selected.geo" class="wa-card__lead">{{ selected.geo }}</p>
            <dl class="wa-card__kv">
              <div v-if="selected.structure"><dt>结构</dt><dd>{{ selected.structure }}</dd></div>
              <div v-if="selected.senses"><dt>感官</dt><dd>{{ selected.senses }}</dd></div>
              <div v-if="selected.accessRules"><dt>进出</dt><dd>{{ selected.accessRules }}</dd></div>
              <div v-if="selected.state"><dt>状态</dt><dd>{{ selected.state }}</dd></div>
              <div v-if="selected.events"><dt>发生的事</dt><dd>{{ selected.events }}</dd></div>
              <div v-if="selected.familiar"><dt>熟客</dt><dd>{{ selected.familiar }}</dd></div>
            </dl>
            <p v-if="selected.text" class="wa-card__text">{{ selected.text }}</p>
            <footer class="wa-card__foot">
              <button type="button" class="wa__link" @click="openSetup">在设定页打开 →</button>
            </footer>
          </aside>
        </div>
        </div>
      </div>

      <p class="wa__foot">
        坐标来自设定里的 mapX/mapY；没标的按正文方位词推断，因此这是「大致方位图」，不是测绘地图。
        同一势力会聚在一起，河/山按地形铺开；点击地点可看注释。
      </p>
    </template>
  </div>
</template>

<style scoped>
.wa {
  display: grid;
  gap: 8px;
  min-width: 0;
}
.wa__body {
  display: grid;
  grid-template-columns: 224px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  min-width: 0;
}
.wa__side {
  display: flex;
  flex-direction: column;
  min-height: 0;
  max-height: 560px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  overflow: hidden;
}
.wa__sidehead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 11px 6px;
}
.wa__sidehead .ns-num {
  color: var(--ns-ink-4);
  font-size: 10.5px;
}
.wa__search {
  margin: 0 8px 6px;
  height: 28px;
  padding: 0 8px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  color: var(--ns-ink);
  font: inherit;
  font-size: 11.5px;
}
.wa__search:focus {
  outline: none;
  border-color: var(--ns-pink-line);
  box-shadow: var(--ns-focus);
}
.wa__lists {
  overflow: auto;
  padding: 0 6px 8px;
  border-top: 1px solid var(--ns-line);
}
.wa__group {
  padding-top: 7px;
}
.wa__grouphead {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 5px 4px;
  font-size: 10.5px;
  color: var(--ns-ink-3);
}
.wa__grouphead i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
}
.wa__grouphead b {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 600;
}
.wa__grouphead .ns-num {
  color: var(--ns-ink-4);
  font-size: 9.5px;
}
.wa__item {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 4px 6px;
  border: 0;
  border-radius: var(--ns-r-xs);
  background: transparent;
  color: var(--ns-ink-2);
  font: inherit;
  font-size: 11.5px;
  text-align: left;
  cursor: pointer;
}
.wa__item:hover,
.wa__item.hot {
  background: var(--ns-card-2);
}
.wa__item.on {
  background: var(--ns-pink-soft);
  color: var(--ns-ink);
}
.wa__itemglyph {
  width: 15px;
  height: 15px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--ns-card-2);
  font-family: var(--ns-serif);
  font-size: 8.5px;
  color: var(--ns-ink-3);
}
.wa__item.on .wa__itemglyph {
  background: var(--ns-card);
  color: var(--ns-pink);
}
.wa__itemname {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wa__itemterrain {
  flex: none;
  font-size: 9.5px;
  color: var(--ns-ink-4);
}
.wa__nomatch {
  margin: 10px 6px;
  font-size: 11px;
  color: var(--ns-ink-4);
}
.wa__empty {
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card-2);
  padding: 26px 24px;
}
.wa__empty b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
}
.wa__empty p {
  margin: 6px 0 10px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-3);
}
.wa__frame {
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  overflow: hidden;
}
.wa__bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--ns-line);
  background: var(--ns-card-2);
}
.wa__title {
  font-size: 12px;
  font-weight: 600;
}
.wa__hint {
  font-size: 11px;
  color: var(--ns-ink-3);
}
.wa__zoomlabel {
  margin-left: auto;
  color: var(--ns-ink-4);
  font-size: 10.5px;
}
.wa__zoom {
  display: flex;
  gap: 4px;
}
.wa__zoom button {
  width: 26px;
  height: 26px;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink-2);
  font: inherit;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
}
.wa__zoom button:hover {
  border-color: var(--ns-pink);
  color: var(--ns-ink);
}
.wa__zoom .wa__reset {
  width: auto;
  padding: 0 9px;
  font-size: 11px;
}
.wa__canvas {
  position: relative;
  aspect-ratio: 1000 / 640;
  min-height: 320px;
  overflow: hidden;
  background: #d8e0da;
  touch-action: none;
  cursor: grab;
}
.wa__canvas.is-dragging {
  cursor: grabbing;
}
.wa__canvas svg {
  display: block;
  width: 100%;
  height: 100%;
  user-select: none;
}
.wa-waves path {
  fill: none;
  stroke: #8fa8a4;
  stroke-width: 2;
  stroke-linecap: round;
}
.wa-river__bank {
  fill: none;
  stroke: #c8d3c8;
  stroke-width: 16;
  stroke-linecap: round;
  opacity: 0.5;
}
.wa-river {
  fill: none;
  stroke: #7fa8b8;
  stroke-width: 9;
  stroke-linecap: round;
  opacity: 0.72;
}
.wa-river__flow {
  fill: none;
  stroke: #e7f0ee;
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-dasharray: 12 26;
  opacity: 0.6;
  animation: wa-flow 9s linear infinite;
}
@keyframes wa-flow {
  to {
    stroke-dashoffset: -76;
  }
}
.wa-lake {
  fill: #a9c1c4;
  stroke: #8fa8a4;
  stroke-width: 1.2;
  opacity: 0.65;
}
.wa-contour {
  fill: none;
  stroke: #a6906d;
  stroke-width: 0.9;
  stroke-dasharray: 3 4;
  opacity: 0.4;
}
.wa-contour--outer {
  opacity: 0.24;
}
.wa-ridge {
  fill: none;
  stroke: #8d7a5c;
  stroke-width: 1.6;
  stroke-dasharray: 10 8;
  opacity: 0.45;
}
.wa-peak {
  fill: #b9a98b;
  stroke: #8d7a5c;
  stroke-width: 1;
  opacity: 0.9;
}
.wa-tree {
  fill: #9fb08b;
  stroke: #6f8460;
  stroke-width: 0.8;
}
.wa-trunk {
  stroke: #6f5c42;
  stroke-width: 1;
}
.wa-road {
  fill: none;
  stroke: #a98d63;
  stroke-width: 3;
  stroke-linecap: round;
  opacity: 0.75;
}
.wa-road--trail {
  stroke-dasharray: 5 6;
  stroke-width: 2;
  opacity: 0.55;
}
.wa-region-label {
  font-family: var(--ns-serif);
  font-size: 11px;
  letter-spacing: 0.08em;
  opacity: 0.28;
  pointer-events: none;
}
.wa-pin {
  cursor: pointer;
  outline: none;
}
.wa-pin__halo {
  opacity: 0.18;
  transition: opacity 0.15s ease;
}
.wa-pin__dot {
  stroke: #f4eddd;
  stroke-width: 1.6;
}
.wa-pin__glyph {
  font-family: var(--ns-serif);
  font-size: 7.5px;
  fill: #fff;
  pointer-events: none;
}
.wa-pin__label {
  font-family: var(--ns-serif);
  font-size: 9.5px;
  fill: #4a4034;
  opacity: 0.85;
  paint-order: stroke;
  stroke: #f4eddd;
  stroke-width: 2.6px;
  stroke-linejoin: round;
  pointer-events: none;
}
.wa-pin__label--major {
  font-size: 10.5px;
  font-weight: 600;
}
/* 点选 / 悬停时只把这一处地名放大，其余保持小字，地图不被字号压住。 */
.wa-pin--on .wa-pin__label,
.wa-pin--hot .wa-pin__label {
  font-size: 12.5px;
  font-weight: 700;
  opacity: 1;
}
.wa-pin:hover .wa-pin__halo,
.wa-pin--hot .wa-pin__halo,
.wa-pin:focus-visible .wa-pin__halo {
  opacity: 0.34;
}
.wa-pin:focus-visible .wa-pin__dot {
  stroke: var(--ns-pink);
  stroke-width: 2.5;
}
.wa-pin__ring {
  fill: none;
  stroke-width: 2;
  opacity: 0.8;
  transform-origin: center;
  animation: wa-pulse 1.8s ease-out infinite;
}
@keyframes wa-pulse {
  0% {
    transform: scale(0.6);
    opacity: 0.8;
  }
  70% {
    transform: scale(1.35);
    opacity: 0;
  }
  100% {
    transform: scale(1.35);
    opacity: 0;
  }
}
.wa-compass__ring {
  fill: rgba(244, 237, 221, 0.55);
  stroke: #9c8a6d;
  stroke-width: 1.2;
}
.wa-compass__needle {
  fill: #b4543f;
  opacity: 0.8;
}
.wa-compass__n {
  font-family: var(--ns-serif);
  font-size: 11px;
  fill: #6c5d49;
}
.wa-scale line {
  stroke: #7d6c55;
  stroke-width: 1.2;
}
.wa-scale text {
  font-size: 9.5px;
  fill: #7d6c55;
}
.wa-traveler {
  fill: #b4543f;
  stroke: #fff;
  stroke-width: 1.5;
  opacity: 0.85;
}
.wa-legend {
  position: absolute;
  left: 10px;
  top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  max-width: min(70%, 520px);
  padding: 7px 9px;
  border-radius: var(--ns-r-sm);
  background: color-mix(in srgb, var(--ns-card) 82%, transparent);
  backdrop-filter: blur(4px);
  border: 1px solid var(--ns-line);
  font-size: 10.5px;
  color: var(--ns-ink-2);
  pointer-events: none;
}
.wa-legend__item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.wa-legend__item i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.wa-legend__item small {
  color: var(--ns-ink-4);
}
.wa-fog {
  position: absolute;
  width: 46%;
  height: 34%;
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(255, 255, 255, 0.42), rgba(255, 255, 255, 0));
  filter: blur(8px);
  pointer-events: none;
  animation: wa-drift 26s ease-in-out infinite alternate;
}
.wa-fog--a {
  left: -8%;
  top: 12%;
}
.wa-fog--b {
  right: -10%;
  bottom: 4%;
  width: 54%;
  height: 30%;
  animation-duration: 34s;
  animation-delay: -8s;
}
@keyframes wa-drift {
  from {
    transform: translate3d(0, 0, 0) scale(1);
  }
  to {
    transform: translate3d(12%, 6%, 0) scale(1.12);
  }
}
.wa-card {
  position: absolute;
  right: 10px;
  bottom: 10px;
  width: min(320px, 46%);
  max-height: 72%;
  overflow: auto;
  padding: 12px 14px;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-md);
  background: color-mix(in srgb, var(--ns-card) 94%, transparent);
  backdrop-filter: blur(6px);
  box-shadow: var(--ns-shadow-2);
}
.wa-card__head {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.wa-card__head h3 {
  margin: 2px 0 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
}
.wa-card__close {
  margin-left: auto;
  border: 0;
  background: transparent;
  color: var(--ns-ink-3);
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
}
.wa-card__lead {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.wa-card__kv {
  margin: 8px 0 0;
  display: grid;
  gap: 1px;
  background: var(--ns-line);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  overflow: hidden;
}
.wa-card__kv > div {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr);
  gap: 8px;
  padding: 6px 8px;
  background: var(--ns-card);
}
.wa-card__kv dt {
  font-size: 10.5px;
  color: var(--ns-ink-3);
}
.wa-card__kv dd {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--ns-ink-2);
}
.wa-card__text {
  margin: 8px 0 0;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--ns-ink-3);
}
.wa-card__foot {
  margin-top: 8px;
}
.wa__link {
  border: 0;
  background: transparent;
  padding: 0;
  color: var(--ns-pink);
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}
.wa__foot {
  margin: 0;
  font-size: 11px;
  line-height: 1.7;
  color: var(--ns-ink-3);
}
@media (max-width: 1000px) {
  .wa__body {
    grid-template-columns: 1fr;
  }
  .wa__side {
    max-height: 190px;
  }
  .wa__lists {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    overflow-y: hidden;
  }
  .wa__group {
    flex: 0 0 180px;
    padding-top: 5px;
  }
}
@media (max-width: 760px) {
  .wa-card {
    position: static;
    width: auto;
    max-height: none;
    margin: 0 10px 10px;
  }
  .wa__canvas {
    aspect-ratio: auto;
    height: 380px;
  }
  .wa__hint {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .wa-fog,
  .wa-pin__ring,
  .wa-river__flow {
    animation: none;
  }
  .wa-traveler {
    display: none;
  }
}
</style>

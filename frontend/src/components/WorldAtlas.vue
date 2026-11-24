<script setup lang="ts">
/**
 * 世界观地图：按「空间层级」排，不画地形。
 *
 * 设定里的地点常常不是平铺的经纬度，而是一层套一层：册/核心在最里，往外是内舱、
 * 中区、外墙，墙外才是废墟与远地。这张图把每个地点放回它所在的层，同层按 geo 里的
 * 方位词排一圈；点开一处就画一条从核心到它的线，说明「离册几层」。
 *
 * 层级、方位、范围（整座庇护所这种容器）都从地点自己的 name/geo/structure 里读。
 * 读不到就落在中层、同层均分——不猜海岸、不补山河，图上每一块都对得上设定原文。
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import type { Faction, Location } from '@/mocks'
import { TIER_NOTE, bearingOf, frameOf, tierName, tierOf, type Tier } from '@/lib/atlas'

const props = defineProps<{ locations: Location[]; factions: Faction[] }>()
const router = useRouter()

const W = 1000
const H = 720
const C = { x: 500, y: 356 }
/** 每层的半径；核心在最中间，越往外越不安全。 */
const R: Record<Tier, number> = { 0: 0, 1: 112, 2: 186, 3: 258, 4: 318 }
const TIERS: Tier[] = [0, 1, 2, 3, 4]
const CORE_GLYPH = ['册', '内', '中', '墙', '外']
const TERRAIN_GLYPH: Record<string, string> = {
  城: '城',
  镇: '镇',
  村: '村',
  山林: '山',
  水岸: '水',
  废墟: '墟',
  关隘: '关',
  营地: '营',
}
const PALETTE = ['#b4543f', '#3f6d7a', '#8a6a2f', '#4b6b45', '#7a4d6d', '#5a5f8a', '#8a5a3f', '#3f7a6a']

type Anchor = 'start' | 'middle' | 'end'
type Node = {
  loc: Location
  tier: Tier
  bearing: number | null
  angle: number
  x: number
  y: number
  color: string
  owner: string
  faction: string
  glyph: string
  major: boolean
  labelX: number
  labelY: number
  anchor: Anchor
}
type Box = { x0: number; x1: number; y0: number; y1: number }

function hashStr(raw: string): number {
  let h = 2166136261
  for (let i = 0; i < raw.length; i += 1) h = Math.imul(h ^ raw.charCodeAt(i), 16777619)
  return Math.abs(h)
}
const rad = (deg: number) => (deg * Math.PI) / 180
const pt = (r: number, deg: number) => ({
  x: C.x + Math.cos(rad(deg)) * r,
  y: C.y + Math.sin(rad(deg)) * r,
})
function angleGap(a: number, b: number): number {
  const d = Math.abs(a - b) % 360
  return d > 180 ? 360 - d : d
}

/** 手绘感的圆：两层低频正弦扰动，比正圆更像画上去的。 */
function ringPath(r: number, seed: number): string {
  const steps = 160
  let d = ''
  for (let i = 0; i <= steps; i += 1) {
    const a = (i / steps) * Math.PI * 2
    const k = 1 + Math.sin(a * 5 + seed) * 0.012 + Math.sin(a * 11 + seed * 1.7) * 0.006
    const x = C.x + Math.cos(a) * r * k
    const y = C.y + Math.sin(a) * r * k
    d += `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`
  }
  return `${d} Z`
}
function arcPath(r: number, a0: number, a1: number): string {
  const p0 = pt(r, a0)
  const p1 = pt(r, a1)
  const large = Math.abs(a1 - a0) > 180 ? 1 : 0
  return `M ${p0.x.toFixed(1)} ${p0.y.toFixed(1)} A ${r} ${r} 0 ${large} ${a1 > a0 ? 1 : 0} ${p1.x.toFixed(1)} ${p1.y.toFixed(1)}`
}

function ownerName(loc: Location): string {
  return (loc.owner || '').split(/[、,，/;；|]/)[0]?.trim() || ''
}
function factionOf(loc: Location): string {
  const names = props.factions.map((f) => f.name).filter(Boolean)
  const raw = (loc.owner || '').trim()
  for (const name of names) {
    if (raw.includes(name) || (raw.length >= 2 && name.includes(raw))) return name
  }
  return ''
}
function factionColor(name: string): string {
  return PALETTE[hashStr(name) % PALETTE.length]
}

const corpus = computed(() =>
  props.locations.map((l) => `${l.name || ''} ${l.geo || ''} ${l.structure || ''}`).join(' '),
)
const frame = computed(() => frameOf(props.locations))
const frameSub = computed(() => {
  const raw = `${frame.value?.structure || ''} ${frame.value?.geo || ''}`
  const hit = raw.match(/同心[一二三四五两\d]+层|([一二三四五两\d]+)层/)
  return hit ? hit[0] : '空间示意'
})
const plan = computed(() => {
  const skip = frame.value?.id
  return props.locations.filter((l) => l.id !== skip)
})

/** 同层排位：有方位词的先钉住，其余找最大空档均分。 */
/** 西轴留给层级标签，地点让开这一条。 */
function offWest(angle: number): number {
  const d = ((angle % 360) + 360) % 360
  if (Math.abs(d - 180) >= 26) return angle
  return d < 180 ? 154 : 206
}

function assignAngles(group: Node[]) {
  if (!group.length) return
  const used: number[] = []
  const fixed = group.filter((n) => n.bearing != null)
  const free = group.filter((n) => n.bearing == null)

  if (!fixed.length) {
    free.forEach((n, i) => {
      n.angle = offWest(-90 + (360 / free.length) * i)
      used.push(n.angle)
    })
    return
  }
  for (const n of fixed) {
    n.angle = n.bearing as number
    used.push(n.angle)
  }
  for (const n of free) {
    const sorted = [...used].sort((a, b) => a - b)
    let best = 0
    let bestGap = -1
    for (let k = 0; k < sorted.length; k += 1) {
      const a = sorted[k]
      const b = k + 1 < sorted.length ? sorted[k + 1] : sorted[0] + 360
      const gap = b - a
      if (gap > bestGap) {
        bestGap = gap
        best = (a + gap / 2) % 360
      }
    }
    n.angle = offWest(best)
    used.push(n.angle)
  }
}

function anchorFor(cosA: number): Anchor {
  if (cosA > 0.35) return 'start'
  if (cosA < -0.35) return 'end'
  return 'middle'
}

/** 地名互不压点：先给主要地点挑位置，再依次试外 / 内 / 上 / 下。 */
function placeLabels(list: Node[], reserved: Box[]) {
  const placed = [...reserved]
  const ordered = [...list].sort((a, b) => Number(b.major) - Number(a.major) || a.angle - b.angle)
  for (const n of ordered) {
    const fs = n.major ? 15 : 14
    const w = Math.max(26, (n.loc.name || '').length * fs + 4)
    const h = fs + 4
    const ox = Math.cos(rad(n.angle))
    const oy = Math.sin(rad(n.angle))
    const candidates: { dx: number; dy: number; anchor: Anchor }[] =
      n.tier === 0
        ? [
            { dx: 0, dy: 26, anchor: 'middle' },
            { dx: 0, dy: -20, anchor: 'middle' },
          ]
        : [
            { dx: ox * 14, dy: oy * 14 + 4, anchor: anchorFor(ox) },
            { dx: -ox * 14, dy: -oy * 14 + 4, anchor: anchorFor(-ox) },
            { dx: 0, dy: -14, anchor: 'middle' },
            { dx: 0, dy: 19, anchor: 'middle' },
          ]
    const boxOf = (c: { dx: number; dy: number; anchor: Anchor }): Box => {
      const x = n.x + c.dx
      const x0 = c.anchor === 'start' ? x : c.anchor === 'end' ? x - w : x - w / 2
      return { x0, x1: x0 + w, y0: n.y + c.dy - h, y1: n.y + c.dy + 3 }
    }
    const pick =
      candidates.find((c) => {
        const b = boxOf(c)
        return !placed.some((p) => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0)
      }) ?? candidates[0]
    placed.push(boxOf(pick))
    n.labelX = n.x + pick.dx
    n.labelY = n.y + pick.dy
    n.anchor = pick.anchor
  }
}

const nodes = computed<Node[]>(() => {
  const list: Node[] = plan.value.map((loc) => {
    const tier = tierOf(loc)
    const owner = ownerName(loc)
    const faction = factionOf(loc)
    return {
      loc,
      tier,
      bearing: bearingOf(loc),
      angle: 0,
      x: C.x,
      y: C.y,
      color: faction ? factionColor(faction) : 'var(--ns-ink-3)',
      owner,
      faction,
      glyph: TERRAIN_GLYPH[loc.terrain || ''] || CORE_GLYPH[tier],
      major: tier <= 1 || Boolean(faction),
      labelX: C.x,
      labelY: C.y,
      anchor: 'middle' as Anchor,
    }
  })

  for (const tier of TIERS) {
    const group = list.filter((n) => n.tier === tier)
    if (!group.length) continue
    assignAngles(group)
    const radius = tier === 0 ? (group.length > 1 ? 40 : 0) : R[tier]
    for (const n of group) {
      n.x = C.x + Math.cos(rad(n.angle)) * radius
      n.y = C.y + Math.sin(rad(n.angle)) * radius
    }
  }

  // 层级标签固定在西轴上，先占位，免得地名压上去。
  const reserved: Box[] = []
  for (const tier of [1, 2, 3] as Tier[]) {
    if (!list.some((n) => n.tier === tier)) continue
    const text = tierName(tier, corpus.value)
    const x1 = C.x - R[tier] - 10
    reserved.push({ x0: x1 - text.length * 17 - 8, x1, y0: C.y - 16, y1: C.y + 10 })
  }
  reserved.push({ x0: W - 120, x1: W, y0: 0, y1: 120 })
  placeLabels(list, reserved)
  return list
})

/** 城墙只在有「墙内」地点时画；它不是装饰，是内外分界。 */
const wall = computed(() => (nodes.value.some((n) => n.tier <= 3) ? ringPath(R[3], 9.3) : ''))
const wallInner = computed(() => (wall.value ? ringPath(R[3] - 7, 9.3) : ''))
const rings = computed(() =>
  ([1, 2, 4] as Tier[])
    .filter((tier) => nodes.value.some((n) => n.tier === tier))
    .map((tier) => ({
      tier,
      r: R[tier],
      label: tierName(tier, corpus.value),
      d: ringPath(R[tier], tier * 3.1),
      labelX: C.x - R[tier] - 10,
      labelY: C.y + 4,
    })),
)
const wallLabel = computed(() => ({
  label: tierName(3, corpus.value),
  x: C.x - R[3] - 10,
  y: C.y + 4,
}))

const discs = computed(() => {
  const has = (tier: Tier) => nodes.value.some((n) => n.tier === tier)
  const out: { r: number; tier: Tier }[] = []
  if (has(0) || has(1) || has(2) || has(3)) out.push({ r: R[3], tier: 3 })
  if (has(0) || has(1) || has(2)) out.push({ r: R[2], tier: 2 })
  if (has(0) || has(1)) out.push({ r: R[1], tier: 1 })
  return out
})

const turrets = computed(() => {
  if (!wall.value) return []
  return Array.from({ length: 28 }, (_, i) => {
    const a = (i * 360) / 28
    const p0 = pt(R[3] - 5, a)
    const p1 = pt(R[3] + 5, a)
    return { x1: p0.x, y1: p0.y, x2: p1.x, y2: p1.y }
  })
})

/** 设定里写了「朝南的门 / 出口」才开这个口，不从书名猜。 */
const gate = computed(() => {
  const hit = props.locations.find(
    (l) => /门|出口/.test(`${l.name || ''} ${l.structure || ''}`) && /[东南西北]/.test(l.geo || ''),
  )
  const angle = hit ? bearingOf(hit) : null
  if (angle == null) return null
  return {
    angle,
    cover: arcPath(R[3], angle - 5, angle + 5),
    labelX: pt(R[3] + 18, angle).x,
    labelY: pt(R[3] + 18, angle).y + 4,
    anchor: anchorFor(Math.cos(rad(angle))),
  }
})

const exitRoad = computed(() => {
  const g = gate.value
  if (!g) return ''
  const outer = nodes.value.filter((n) => n.tier === 4)
  const target = [...outer].sort((a, b) => angleGap(a.angle, g.angle) - angleGap(b.angle, g.angle))[0]
  const from = pt(R[3] + 8, g.angle)
  if (!target) {
    const to = pt(R[3] + 56, g.angle)
    return `M ${from.x.toFixed(1)} ${from.y.toFixed(1)} L ${to.x.toFixed(1)} ${to.y.toFixed(1)}`
  }
  const mx = (from.x + target.x) / 2 + 26
  const my = (from.y + target.y) / 2
  return `M ${from.x.toFixed(1)} ${from.y.toFixed(1)} Q ${mx.toFixed(1)} ${my.toFixed(1)} ${target.x.toFixed(1)} ${target.y.toFixed(1)}`
})

const selected = ref<Location | null>(null)
const hover = ref('')
const sideQ = ref('')
watch(
  () => props.locations,
  () => {
    selected.value = null
  },
)

const nodeOf = computed(() => new Map(nodes.value.map((n) => [n.loc.id, n])))
const selectedNode = computed(() => (selected.value ? nodeOf.value.get(selected.value.id) ?? null : null))
const frameSelected = computed(() => Boolean(frame.value && selected.value?.id === frame.value.id))
const spoke = computed(() => {
  const n = selectedNode.value
  if (!n || n.tier === 0) return ''
  return `M ${C.x} ${C.y} L ${n.x.toFixed(1)} ${n.y.toFixed(1)}`
})
const selectedTierName = computed(() => {
  const n = selectedNode.value
  return n ? tierName(n.tier, corpus.value) : ''
})

const sideGroups = computed(() => {
  const needle = sideQ.value.trim().toLowerCase()
  const out: { tier: Tier; name: string; color: string; list: Node[] }[] = []
  for (const tier of TIERS) {
    const list = nodes.value
      .filter((n) => n.tier === tier)
      .filter(
        (n) =>
          !needle ||
          `${n.loc.name} ${n.owner} ${n.loc.geo} ${n.loc.terrain}`
            .toLowerCase()
            .includes(needle),
      )
      .sort((a, b) => (a.loc.name || '').localeCompare(b.loc.name || '', 'zh'))
    if (list.length) {
      out.push({ tier, name: tierName(tier, corpus.value), color: list[0].color, list })
    }
  }
  return out
})

const legend = computed(() => {
  const seen = new Map<string, { name: string; color: string; count: number }>()
  for (const n of nodes.value) {
    const key = n.faction || '其他'
    const hit = seen.get(key) ?? { name: key, color: n.color, count: 0 }
    hit.count += 1
    seen.set(key, hit)
  }
  return [...seen.values()].sort((a, b) => b.count - a.count)
})

const title = computed(() => (frame.value ? `${frame.value.name} · ${frameSub.value}` : '地点关系图'))
const ariaLabel = computed(
  () => `${frame.value?.name || '世界观'}空间层级图，由内向外为${rings.value.map((r) => r.label).join('、')}`,
)

function openSetup() {
  void router.push({ name: 'setup', query: { tab: 'locations' } })
}
</script>

<template>
  <div class="wa">
    <div v-if="!plan.length" class="wa__empty">
      <b>{{ frame ? `${frame.name}还只有范围` : '地图还是空的' }}</b>
      <p>地点在「设定」页从大纲和世界观里拆出来；生成后地图会按设定里的空间层级自动排布。</p>
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
            <section v-if="frame" class="wa__group">
              <header class="wa__grouphead">
                <b>范围</b>
                <span class="ns-num">1</span>
              </header>
              <button
                type="button"
                class="wa__item"
                :class="{ on: selected?.id === frame.id }"
                @click="selected = frame"
              >
                <span class="wa__itemglyph">界</span>
                <span class="wa__itemname">{{ frame.name }}</span>
                <span class="wa__itemterrain">{{ frameSub }}</span>
              </button>
            </section>
            <section v-for="g in sideGroups" :key="g.tier" class="wa__group">
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
                @click="selected = n.loc"
                @mouseenter="hover = n.loc.id"
                @mouseleave="hover = ''"
              >
                <span class="wa__itemglyph">{{ n.glyph }}</span>
                <span class="wa__itemname">{{ n.loc.name }}</span>
                <span class="wa__itemterrain">{{ n.owner || TIER_NOTE[n.tier] }}</span>
              </button>
            </section>
            <p v-if="!sideGroups.length" class="wa__nomatch">没有匹配的地点</p>
          </div>
        </aside>

        <div class="wa__frame">
          <div class="wa__bar">
            <span class="wa__title">{{ title }}</span>
            <span class="wa__hint">由内向外 · 越靠中心越安全</span>
            <span class="wa__count ns-num">{{ plan.length }} 处</span>
          </div>

          <div class="wa__canvas">
            <svg :viewBox="`0 0 ${W} ${H}`" role="img" :aria-label="ariaLabel">
              <defs>
                <pattern
                  id="wa-ruin"
                  width="34"
                  height="34"
                  patternUnits="userSpaceOnUse"
                  patternTransform="rotate(-18)"
                >
                  <path d="M 4 26 L 9 21" class="wa-ruin__mark" />
                  <path d="M 22 12 L 28 6" class="wa-ruin__mark" />
                </pattern>
                <radialGradient id="wa-lamp">
                  <stop offset="0%" class="wa-lamp__core" />
                  <stop offset="55%" class="wa-lamp__mid" />
                  <stop offset="100%" class="wa-lamp__out" />
                </radialGradient>
                <radialGradient id="wa-vignette" cx="50%" cy="52%" r="72%">
                  <stop offset="55%" class="wa-vig__in" />
                  <stop offset="100%" class="wa-vig__out" />
                </radialGradient>
              </defs>

              <rect :width="W" :height="H" class="wa-ground" />
              <rect :width="W" :height="H" fill="url(#wa-ruin)" />

              <circle
                v-if="nodes.some((n) => n.tier === 0)"
                :cx="C.x"
                :cy="C.y"
                r="120"
                fill="url(#wa-lamp)"
              />

              <circle
                v-for="d in discs"
                :key="`d-${d.tier}`"
                :cx="C.x"
                :cy="C.y"
                :r="d.r"
                :class="`wa-floor wa-floor--${d.tier}`"
              />

              <path
                v-for="r in rings"
                :key="`r-${r.tier}`"
                :d="r.d"
                class="wa-ring"
                :class="`wa-ring--${r.tier}`"
              />

              <template v-if="wall">
                <path :d="wall" class="wa-wall" />
                <path :d="wallInner" class="wa-wall__edge" />
                <line
                  v-for="(t, i) in turrets"
                  :key="`t-${i}`"
                  :x1="t.x1"
                  :y1="t.y1"
                  :x2="t.x2"
                  :y2="t.y2"
                  class="wa-wall__tick"
                />
                <path v-if="gate" :d="gate.cover" class="wa-gate__gap" />
                <line
                  v-if="gate"
                  :x1="pt(R[3], gate.angle).x"
                  :y1="pt(R[3], gate.angle).y"
                  :x2="pt(R[3] + 30, gate.angle).x"
                  :y2="pt(R[3] + 30, gate.angle).y"
                  class="wa-gate__stub"
                />
                <text
                  v-if="gate"
                  :x="gate.labelX"
                  :y="gate.labelY"
                  :text-anchor="gate.anchor"
                  class="wa-gate__label"
                >出口</text>
              </template>

              <path v-if="exitRoad" :d="exitRoad" class="wa-exit" />
              <path v-if="spoke" :d="spoke" class="wa-spoke" />
              <circle
                v-if="frameSelected"
                :cx="C.x"
                :cy="C.y"
                :r="R[3] + 10"
                class="wa-framehi"
              />
              <rect :width="W" :height="H" fill="url(#wa-vignette)" pointer-events="none" />

              <text
                v-for="r in rings"
                :key="`l-${r.tier}`"
                :x="r.labelX"
                :y="r.labelY"
                class="wa-ringlabel"
                text-anchor="end"
              >{{ r.label }}</text>
              <text
                v-if="wall"
                :x="wallLabel.x"
                :y="wallLabel.y"
                class="wa-ringlabel"
                text-anchor="end"
              >{{ wallLabel.label }}</text>

              <g
                v-for="n in nodes"
                :key="n.loc.id"
                class="wa-node"
                :class="{
                  'wa-node--on': selected?.id === n.loc.id,
                  'wa-node--hot': hover === n.loc.id,
                  'wa-node--major': n.major,
                }"
                :transform="`translate(${n.x.toFixed(1)}, ${n.y.toFixed(1)})`"
                role="button"
                tabindex="0"
                :aria-label="`${n.loc.name}${n.owner ? `，${n.owner}` : ''}，${tierName(n.tier, corpus)}`"
                @click="selected = n.loc"
                @keydown.enter.prevent="selected = n.loc"
                @keydown.space.prevent="selected = n.loc"
                @mouseenter="hover = n.loc.id"
                @mouseleave="hover = ''"
              >
                <title>
                  {{ n.loc.name }}{{ n.owner ? ` · ${n.owner}` : '' }}{{ n.loc.geo ? ` · ${n.loc.geo}` : '' }}
                </title>
                <circle v-if="n.tier === 0" class="wa-node__seal" r="21" />
                <circle class="wa-node__halo" :r="n.major ? 17 : 13" :fill="n.color" />
                <circle
                  class="wa-node__mark"
                  :r="n.major ? 10.5 : 8.5"
                  :stroke="n.color"
                  :fill="selected?.id === n.loc.id ? n.color : 'var(--ns-card)'"
                />
                <text
                  class="wa-node__glyph"
                  y="3.2"
                  text-anchor="middle"
                  :fill="selected?.id === n.loc.id ? 'var(--ns-card)' : n.color"
                >{{ n.glyph }}</text>
                <text
                  class="wa-node__label"
                  :x="n.labelX - n.x"
                  :y="n.labelY - n.y"
                  :text-anchor="n.anchor"
                >{{ n.loc.name }}</text>
              </g>

              <g class="wa-compass" :transform="`translate(${W - 56}, 58)`">
                <circle r="20" class="wa-compass__ring" />
                <path d="M 0 -14 L 5 3 L 0 0 L -5 3 Z" class="wa-compass__needle" />
                <text y="-25" text-anchor="middle" class="wa-compass__n">北</text>
              </g>
              <text :x="W - 16" :y="H - 16" text-anchor="end" class="wa-note">示意 · 非测距</text>
            </svg>

            <aside v-if="selected" class="wa-card">
              <header class="wa-card__head">
                <div>
                  <span class="ns-eyebrow">
                    {{ frameSelected ? '范围' : `${selectedTierName} · ${TIER_NOTE[selectedNode?.tier ?? 2]}` }}
                  </span>
                  <h3>{{ selected.name }}</h3>
                </div>
                <button type="button" class="wa-card__close" aria-label="关闭" @click="selected = null">×</button>
              </header>
              <p v-if="selectedNode" class="wa-card__depth">
                距册 {{ selectedNode.tier }} 层<template v-if="frame"> · 共 {{ plan.length }} 处</template>
              </p>
              <p v-if="selected.geo" class="wa-card__lead">{{ selected.geo }}</p>
              <dl class="wa-card__kv">
                <div v-if="selected.owner"><dt>归属</dt><dd>{{ selected.owner }}</dd></div>
                <div v-if="selected.structure"><dt>结构</dt><dd>{{ selected.structure }}</dd></div>
                <div v-if="selected.senses"><dt>感官</dt><dd>{{ selected.senses }}</dd></div>
                <div v-if="selected.accessRules"><dt>进出</dt><dd>{{ selected.accessRules }}</dd></div>
                <div v-if="selected.occupied"><dt>占用</dt><dd>{{ selected.occupied }}</dd></div>
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

          <div class="wa__foot">
            <div v-if="legend.length" class="wa-legend">
              <span v-for="l in legend" :key="l.name" class="wa-legend__item">
                <i :style="{ background: l.color }" />
                <span class="wa-legend__name">{{ l.name }}</span>
                <small class="ns-num">{{ l.count }}</small>
              </span>
            </div>
            <p>
              这张图只画设定里写过的空间关系：层名、方位、出口都取自地点自己的 geo / structure，
              没写方位的地点在同一层里均分。不画海岸与山脉，也不按坐标编地形。
            </p>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.wa {
  display: grid;
  gap: 8px;
}
.wa__body {
  display: grid;
  grid-template-columns: 232px minmax(0, 1fr);
  gap: 10px;
  align-items: stretch;
  min-width: 0;
}
.wa__side {
  display: flex;
  flex-direction: column;
  min-height: 0;
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
  flex: 1;
  min-height: 0;
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
  max-width: 74px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  overflow: hidden;
}
.wa__bar {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--ns-line);
  background: var(--ns-card-2);
}
.wa__title {
  font-family: var(--ns-serif);
  font-size: 12.5px;
  font-weight: 700;
}
.wa__hint {
  font-size: 11px;
  color: var(--ns-ink-3);
}
.wa__count {
  margin-left: auto;
  color: var(--ns-ink-4);
  font-size: 10.5px;
}
.wa__canvas {
  position: relative;
  overflow: hidden;
  background: var(--ns-paper);
}
.wa__canvas svg {
  display: block;
  width: 100%;
  height: auto;
  user-select: none;
}
.wa-ground {
  fill: var(--ns-paper);
}
.wa-ruin__mark {
  fill: none;
  stroke: var(--ns-line-2);
  stroke-width: 1;
  opacity: 0.9;
}
.wa-floor--3 {
  fill: var(--ns-paper-2);
}
.wa-floor--2 {
  fill: var(--ns-card-2);
}
.wa-floor--1 {
  fill: var(--ns-card);
}
.wa-lamp__core {
  stop-color: var(--ns-gold);
  stop-opacity: 0.34;
}
.wa-lamp__mid {
  stop-color: var(--ns-gold);
  stop-opacity: 0.1;
}
.wa-lamp__out {
  stop-color: var(--ns-gold);
  stop-opacity: 0;
}
.wa-vig__in {
  stop-color: var(--ns-ink);
  stop-opacity: 0;
}
.wa-vig__out {
  stop-color: var(--ns-ink);
  stop-opacity: 0.06;
}
.wa-ring {
  fill: none;
  stroke: var(--ns-line-2);
  stroke-width: 1.1;
  stroke-dasharray: 5 7;
  opacity: 0.95;
}
.wa-ring--4 {
  stroke-dasharray: 2 9;
  opacity: 0.55;
}
.wa-wall {
  fill: none;
  stroke: var(--ns-ink-2);
  stroke-width: 8;
  stroke-linecap: round;
  opacity: 0.5;
}
.wa-wall__edge {
  fill: none;
  stroke: var(--ns-ink-3);
  stroke-width: 1;
  stroke-dasharray: 9 6;
  opacity: 0.35;
}
.wa-wall__tick {
  stroke: var(--ns-ink-2);
  stroke-width: 1.5;
  opacity: 0.45;
}
.wa-gate__gap {
  fill: none;
  stroke: var(--ns-paper-2);
  stroke-width: 12;
}
.wa-gate__stub {
  stroke: var(--ns-ink-4);
  stroke-width: 1.2;
  stroke-dasharray: 3 4;
}
.wa-gate__label {
  font-family: var(--ns-serif);
  font-size: 12px;
  letter-spacing: 0.12em;
  fill: var(--ns-ink-3);
  paint-order: stroke;
  stroke: var(--ns-paper);
  stroke-width: 3.5px;
}
.wa-exit {
  fill: none;
  stroke: var(--ns-ink-4);
  stroke-width: 1.4;
  stroke-dasharray: 1 6;
  stroke-linecap: round;
  opacity: 0.75;
}
.wa-spoke {
  fill: none;
  stroke: var(--ns-pink);
  stroke-width: 1.4;
  stroke-dasharray: 4 5;
  opacity: 0.5;
}
.wa-framehi {
  fill: none;
  stroke: var(--ns-pink);
  stroke-width: 1.4;
  stroke-dasharray: 5 6;
  opacity: 0.55;
}
.wa-ringlabel {
  font-family: var(--ns-serif);
  font-size: 16px;
  letter-spacing: 0.14em;
  fill: var(--ns-ink-2);
  paint-order: stroke;
  stroke: var(--ns-paper);
  stroke-width: 4.5px;
  stroke-linejoin: round;
}
.wa-node {
  cursor: pointer;
  outline: none;
}
.wa-node__seal {
  fill: none;
  stroke: var(--ns-gold);
  stroke-width: 1.2;
  stroke-dasharray: 3 4;
  opacity: 0.75;
}
.wa-node__halo {
  opacity: 0.13;
  transition: opacity 0.15s ease;
}
.wa-node:hover .wa-node__halo,
.wa-node--hot .wa-node__halo,
.wa-node:focus-visible .wa-node__halo {
  opacity: 0.3;
}
.wa-node__mark {
  stroke-width: 1.6;
}
.wa-node:focus-visible .wa-node__mark {
  stroke: var(--ns-pink);
  stroke-width: 2.6;
}
.wa-node__glyph {
  font-family: var(--ns-serif);
  font-size: 9.5px;
  pointer-events: none;
}
.wa-node__label {
  font-family: var(--ns-serif);
  font-size: 14px;
  fill: var(--ns-ink-2);
  paint-order: stroke;
  stroke: var(--ns-paper);
  stroke-width: 4.2px;
  stroke-linejoin: round;
  pointer-events: none;
}
.wa-node--major .wa-node__label {
  font-size: 15px;
  font-weight: 700;
  fill: var(--ns-ink);
}
.wa-node--on .wa-node__label,
.wa-node--hot .wa-node__label {
  font-size: 16px;
  font-weight: 700;
  fill: var(--ns-ink);
}
.wa-compass__ring {
  fill: color-mix(in srgb, var(--ns-card) 70%, transparent);
  stroke: var(--ns-line-2);
  stroke-width: 1;
}
.wa-compass__needle {
  fill: var(--ns-pink);
  opacity: 0.75;
}
.wa-compass__n {
  font-family: var(--ns-serif);
  font-size: 10px;
  fill: var(--ns-ink-3);
}
.wa-note {
  font-size: 11.5px;
  letter-spacing: 0.08em;
  fill: var(--ns-ink-4);
}
.wa-card {
  position: absolute;
  right: 10px;
  bottom: 10px;
  width: min(330px, 46%);
  max-height: 74%;
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
.wa-card__close:hover {
  color: var(--ns-ink);
}
.wa-card__depth {
  margin: 4px 0 0;
  font-size: 10.5px;
  letter-spacing: 0.06em;
  color: var(--ns-pink);
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
  grid-template-columns: 54px minmax(0, 1fr);
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
  border-top: 1px solid var(--ns-line);
  padding: 8px 12px 10px;
  background: var(--ns-card);
}
.wa__foot p {
  margin: 6px 0 0;
  font-size: 11px;
  line-height: 1.7;
  color: var(--ns-ink-3);
}
.wa-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  font-size: 10.5px;
  color: var(--ns-ink-2);
}
.wa-legend__item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 150px;
  min-width: 0;
}
.wa-legend__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wa-legend__item i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.wa-legend__item small {
  color: var(--ns-ink-4);
}
@media (max-width: 1000px) {
  .wa__body {
    grid-template-columns: 1fr;
  }
  .wa__side {
    max-height: 196px;
  }
  .wa__lists {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    overflow-y: hidden;
  }
  .wa__group {
    flex: 0 0 184px;
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
  .wa__hint {
    display: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .wa-node__halo {
    transition: none;
  }
}
</style>

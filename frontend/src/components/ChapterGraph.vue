<script setup lang="ts">
import { computed } from 'vue'
import type { ChapterGraph, GraphEdge, GraphNode } from '@/api/extras'

const props = withDefaults(
  defineProps<{
    graph: ChapterGraph | null
    loading?: boolean
  }>(),
  { loading: false },
)
const emit = defineEmits<{ open: [number: number] }>()

const GAP = 34
const PAD = 56
const BASE_Y = 150
const TOP = 34
const HEIGHT = 286

const nodes = computed<GraphNode[]>(() => [...(props.graph?.nodes ?? [])].sort((a, b) => a.number - b.number))

const xOf = (n: number) => PAD + nodes.value.findIndex((x) => x.number === n) * GAP
const width = computed(() => Math.max(640, PAD * 2 + Math.max(0, nodes.value.length - 1) * GAP))

type DrawnEdge = GraphEdge & { x1: number; x2: number; path: string; mid: number; midY: number }

const drawn = computed<DrawnEdge[]>(() => {
  const byNumber = new Set(nodes.value.map((n) => n.number))
  const out: DrawnEdge[] = []
  for (const e of props.graph?.edges ?? []) {
    if (!byNumber.has(e.from) || !byNumber.has(e.to) || e.from === e.to) continue
    const x1 = xOf(e.from)
    const x2 = xOf(e.to)
    if (x1 < 0 || x2 < 0) continue
    const above = e.kind === 'foreshadow'
    const lift = Math.min(above ? 120 : 70, 24 + Math.abs(x2 - x1) * (above ? 0.32 : 0.22))
    const y1 = above ? BASE_Y - 16 : BASE_Y + 16
    const y2 = y1
    const cy = above ? y1 - lift : y1 + lift
    out.push({
      ...e,
      x1,
      x2,
      path: `M ${x1} ${y1} C ${x1} ${cy}, ${x2} ${cy}, ${x2} ${y2}`,
      mid: (x1 + x2) / 2,
      midY: above ? y1 - lift * 0.52 : y1 + lift * 0.52,
    })
  }
  return out
})

/** 边太多时只画线不写字，避免标签压成一团。 */
const showEdgeLabels = computed(() => drawn.value.length <= 14)

const bands = computed(() => {
  const vols = props.graph?.volumes ?? []
  return vols
    .map((v, i) => {
      const first = nodes.value.find((n) => n.volume === v.volume)
      const last = [...nodes.value].reverse().find((n) => n.volume === v.volume)
      if (!first || !last) return null
      const x1 = xOf(first.number) - GAP / 2
      const x2 = xOf(last.number) + GAP / 2
      return { key: `${v.volume}-${i}`, label: v.title || `第${v.volume}卷`, x1, x2: Math.max(x2, x1 + GAP), odd: i % 2 === 1 }
    })
    .filter((b): b is NonNullable<typeof b> => b !== null)
})

const stats = computed(() => props.graph?.stats ?? {
  chapters: 0, edges: 0, foreshadowEdges: 0, castEdges: 0,
  openForeshadows: 0, paidForeshadows: 0, castlessChapters: 0,
})

const nodeTone = (n: GraphNode) => {
  if (n.paid) return 'paid'
  if (n.planted) return 'planted'
  return n.approved ? 'ok' : 'pending'
}

const edgeClass = (e: GraphEdge) => [
  `edge--${e.kind}`,
  e.status === 'paid' ? 'edge--paid' : e.status === 'planned' ? 'edge--planned' : '',
]
</script>

<template>
  <div class="graphwrap">
    <div v-if="loading" class="graphload">正在按账本整理章脉…</div>
    <template v-else-if="!nodes.length">
      <slot name="empty">
        <p class="graphempty">还没有正文。写完第一章之后，这里会按伏笔和出场人物把章节连起来。</p>
      </slot>
    </template>
    <template v-else>
      <div class="graphstats">
        <span><b>{{ stats.chapters }}</b> 章</span>
        <span>伏笔线 <b>{{ stats.foreshadowEdges }}</b></span>
        <span>同场线 <b>{{ stats.castEdges }}</b></span>
        <span>未收伏笔 <b>{{ stats.openForeshadows }}</b></span>
        <span v-if="stats.castlessChapters">没记出场人物 <b>{{ stats.castlessChapters }}</b> 章</span>
      </div>

      <div class="graphscroll">
        <svg
          class="graph"
          :viewBox="`0 0 ${width} ${HEIGHT}`"
          :style="{ width: `${width}px` }"
          role="img"
          aria-label="章节关系图谱：上方弧线是伏笔埋收，下方弧线是同场人物"
        >
          <g class="bands">
            <g v-for="b in bands" :key="b.key">
              <rect :x="b.x1" :y="TOP - 12" :width="b.x2 - b.x1" :height="HEIGHT - TOP - 34" :class="{ 'band--odd': b.odd }" rx="8" />
              <text :x="b.x1 + 6" :y="TOP - 18" class="bandlabel">{{ b.label }}</text>
            </g>
          </g>

          <line :x1="PAD - 20" :x2="width - PAD + 20" :y1="BASE_Y" :y2="BASE_Y" class="spine" />

          <g class="edges">
            <g v-for="e in drawn" :key="e.id" :class="edgeClass(e)">
              <path :d="e.path" />
              <title>
                {{ e.kind === 'foreshadow' ? '伏笔' : '同场' }}：第{{ e.from }}章 → 第{{ e.to }}章
                {{ e.label ? `· ${e.label}` : '' }}
              </title>
              <text v-if="showEdgeLabels && e.label" :x="e.mid" :y="e.midY" class="edgelabel">
                {{ e.label }}
              </text>
            </g>
          </g>

          <g class="nodes">
            <g
              v-for="n in nodes"
              :key="n.id"
              class="node"
              :class="`node--${nodeTone(n)}`"
              :transform="`translate(${xOf(n.number)}, ${BASE_Y})`"
              tabindex="0"
              role="button"
              @click="emit('open', n.number)"
              @keydown.enter.prevent="emit('open', n.number)"
              @keydown.space.prevent="emit('open', n.number)"
            >
              <circle r="11" />
              <text y="3.5" class="nodenum">{{ n.number }}</text>
              <circle v-if="n.paid" class="badge badge--paid" cx="9" cy="-9" r="4" />
              <circle v-else-if="n.planted" class="badge badge--planted" cx="9" cy="-9" r="4" />
              <title>
                第{{ n.number }}章《{{ n.title }}》
                {{ n.chars }} 字{{ n.approved ? ' · 已存档' : ' · 待确认' }}
                {{ n.cast.length ? ` · 出场：${n.cast.join('、')}` : '' }}
                {{ n.planted ? ` · 埋 ${n.planted} 条伏笔` : '' }}{{ n.paid ? ` · 收 ${n.paid} 条` : '' }}
                {{ n.summary ? `\n${n.summary}` : '' }}
              </title>
            </g>
          </g>
        </svg>
      </div>

      <div class="graphlegend">
        <span><i class="dot dot--paid" /> 收过伏笔</span>
        <span><i class="dot dot--planted" /> 埋了伏笔</span>
        <span><i class="ln ln--foreshadow" /> 伏笔埋收</span>
        <span><i class="ln ln--planned" /> 计划收线</span>
        <span><i class="ln ln--cast" /> 同场人物（≤10 章）</span>
        <span class="graphlegend__hint">点章节查看；悬停看这一章牵了谁</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.graphwrap {
  display: grid;
  gap: var(--ns-s3);
}
.graphload,
.graphempty {
  margin: 0;
  padding: var(--ns-s8) var(--ns-s4);
  text-align: center;
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-3);
}
.graphstats {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
}
.graphstats b {
  color: var(--ns-ink);
  font-variant-numeric: tabular-nums;
}
.graphscroll {
  overflow-x: auto;
  overflow-y: hidden;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
}
.graph {
  display: block;
  max-width: none;
}
.bands rect {
  fill: transparent;
}
.band--odd {
  fill: color-mix(in srgb, var(--ns-card-2) 70%, transparent);
}
.bandlabel {
  font-size: 9.5px;
  fill: var(--ns-ink-3);
  letter-spacing: 0.02em;
}
.spine {
  stroke: var(--ns-line);
  stroke-width: 1;
}
.edge path {
  fill: none;
  stroke-width: 1.2;
  transition: opacity 0.15s;
}
.edge--foreshadow path {
  stroke: var(--ns-pink);
  opacity: 0.55;
}
.edge--foreshadow.edge--paid path {
  opacity: 0.85;
  stroke-width: 1.5;
}
.edge--foreshadow.edge--planned path {
  stroke-dasharray: 4 4;
  stroke: var(--ns-warn);
}
.edge--cast path {
  stroke: var(--ns-ink-3);
  opacity: 0.22;
}
.edge:hover path {
  opacity: 1;
  stroke-width: 2;
}
.edgelabel {
  font-size: 9px;
  fill: var(--ns-ink-3);
  text-anchor: middle;
}
.node {
  cursor: pointer;
  outline: none;
}
.node circle {
  fill: var(--ns-card);
  stroke: var(--ns-ink-3);
  stroke-width: 1.2;
}
.node--ok circle {
  stroke: var(--ns-ok, #2f7d5b);
}
.node--pending circle {
  stroke: var(--ns-warn);
  stroke-dasharray: 3 2;
}
.node--planted circle {
  stroke: var(--ns-pink);
}
.node--paid circle {
  stroke: var(--ns-pink);
  fill: var(--ns-pink-soft);
}
.node:hover circle,
.node:focus-visible circle {
  stroke-width: 2.4;
  filter: drop-shadow(0 1px 3px color-mix(in srgb, var(--ns-ink) 25%, transparent));
}
.nodenum {
  font-size: 9px;
  text-anchor: middle;
  fill: var(--ns-ink);
  font-variant-numeric: tabular-nums;
  pointer-events: none;
}
.badge--paid {
  fill: var(--ns-pink);
}
.badge--planted {
  fill: var(--ns-warn);
}
.graphlegend {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
}
.graphlegend__hint {
  margin-left: auto;
}
.dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 5px;
  vertical-align: 0;
}
.dot--paid {
  background: var(--ns-pink);
}
.dot--planted {
  background: var(--ns-warn);
}
.ln {
  display: inline-block;
  width: 18px;
  height: 0;
  border-top: 1.5px solid var(--ns-ink-3);
  margin-right: 6px;
  vertical-align: 3px;
}
.ln--foreshadow {
  border-color: var(--ns-pink);
}
.ln--planned {
  border-color: var(--ns-warn);
  border-top-style: dashed;
}
.ln--cast {
  opacity: 0.4;
}
</style>

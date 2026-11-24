<script setup lang="ts">
/** 势力 · 地点示意图：按归属分块排布，点节点看进出规矩和当前状态。
 *  没有经纬度数据，所以不画真实地形，只画「谁管着哪几处」。 */
import { computed, ref } from 'vue'
import type { Faction, Location } from '@/mocks'

const props = defineProps<{ locations: Location[]; factions: Faction[] }>()

const GROUP_W = 210
const NODE_W = 178
const NODE_H = 30
const GAP = 8
const TOP = 38
const PAD = 12

const selected = ref<Location | null>(null)

function ownerKeys(raw: string): string[] {
  return String(raw || '')
    .split(/[、,，/;；|]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function groupOf(loc: Location): string {
  const names = props.factions.map((f) => f.name).filter(Boolean)
  for (const key of ownerKeys(loc.owner)) {
    const hit = names.find((n) => key.includes(n) || n.includes(key))
    if (hit) return hit
  }
  return ownerKeys(loc.owner)[0] || '未归属'
}

const groups = computed(() => {
  const map = new Map<string, Location[]>()
  for (const loc of props.locations) {
    const key = groupOf(loc)
    map.set(key, [...(map.get(key) ?? []), loc])
  }
  // 势力顺序在前，未归属放最后
  const order = props.factions.map((f) => f.name).filter((n) => map.has(n))
  const rest = [...map.keys()].filter((k) => !order.includes(k)).sort()
  return [...order, ...rest].map((name) => ({ name, nodes: map.get(name) ?? [] }))
})

const layout = computed(() => {
  const gs = groups.value
  const width = Math.max(GROUP_W, gs.length * GROUP_W)
  const heights = gs.map((g) => TOP + g.nodes.length * (NODE_H + GAP))
  const height = Math.max(150, ...heights) + PAD
  return {
    width,
    height,
    groups: gs.map((g, i) => ({
      ...g,
      x: i * GROUP_W + PAD / 2,
      height: heights[i],
    })),
  }
})

function shorten(name: string, n = 11): string {
  return name.length > n ? `${name.slice(0, n)}…` : name
}
</script>

<template>
  <div class="wm">
    <div v-if="!locations.length" class="wm__empty">
      <b>地图还是空的</b>
      <p>地点在「设定」页从大纲和世界观里拆出来；生成后会自动出现在这张图上。</p>
    </div>
    <template v-else>
      <div class="wm__canvas">
        <svg
          :viewBox="`0 0 ${layout.width} ${layout.height}`"
          :style="{ width: `${layout.width}px` }"
          role="img"
          aria-label="势力与地点示意图"
        >
          <g v-for="(g, gi) in layout.groups" :key="g.name" :transform="`translate(${g.x}, 0)`">
            <rect
              class="wm__region"
              :class="`wm__region--${gi % 4}`"
              x="4"
              y="6"
              :width="NODE_W + 8"
              :height="g.height"
              rx="10"
            />
            <text class="wm__group" x="14" y="26">{{ shorten(g.name, 12) }}</text>
            <line
              class="wm__trunk"
              :x1="NODE_W / 2 + 8"
              :y1="TOP"
              :x2="NODE_W / 2 + 8"
              :y2="TOP + g.nodes.length * (NODE_H + GAP) - GAP"
            />
            <g
              v-for="(loc, ni) in g.nodes"
              :key="loc.id"
              class="wm__node"
              :class="{ 'is-on': selected?.id === loc.id }"
              role="button"
              tabindex="0"
              :aria-label="loc.name"
              @click="selected = loc"
              @keydown.enter.prevent="selected = loc"
              @keydown.space.prevent="selected = loc"
            >
              <title>{{ loc.name }}{{ loc.owner ? ` · ${loc.owner}` : '' }}</title>
              <line
                class="wm__edge"
                :x1="NODE_W / 2 + 8"
                :y1="TOP + ni * (NODE_H + GAP)"
                :x2="8"
                :y2="TOP + ni * (NODE_H + GAP) + NODE_H / 2"
              />
              <rect
                class="wm__card"
                x="8"
                :y="TOP + ni * (NODE_H + GAP)"
                :width="NODE_W"
                :height="NODE_H"
                rx="7"
              />
              <text class="wm__label" x="20" :y="TOP + ni * (NODE_H + GAP) + 19">
                {{ shorten(loc.name) }}
              </text>
            </g>
          </g>
        </svg>
      </div>

      <div v-if="selected" class="wm__detail">
        <header class="wm__detailhead">
          <b>{{ selected.name }}</b>
          <span v-if="selected.owner" class="wm__owner">{{ selected.owner }}</span>
          <button type="button" class="wm__close" aria-label="关闭地点详情" @click="selected = null">×</button>
        </header>
        <dl>
          <div v-if="selected.geo"><dt>地理</dt><dd>{{ selected.geo }}</dd></div>
          <div v-if="selected.structure"><dt>结构</dt><dd>{{ selected.structure }}</dd></div>
          <div v-if="selected.senses"><dt>感官</dt><dd>{{ selected.senses }}</dd></div>
          <div v-if="selected.accessRules"><dt>进出规矩</dt><dd>{{ selected.accessRules }}</dd></div>
          <div v-if="selected.state"><dt>当前状态</dt><dd>{{ selected.state }}</dd></div>
          <div v-if="selected.events"><dt>发生的事</dt><dd>{{ selected.events }}</dd></div>
          <div v-if="selected.text"><dt>一句话</dt><dd>{{ selected.text }}</dd></div>
        </dl>
      </div>
      <p v-else class="wm__hint">
        点任意地点节点查看详情。共 {{ locations.length }} 处，分 {{ groups.length }} 块。
      </p>
    </template>
  </div>
</template>

<style scoped>
.wm {
  background: var(--ns-card);
}
.wm__empty {
  padding: 28px 20px;
  text-align: center;
}
.wm__empty b {
  font-family: var(--ns-serif);
  font-size: 14px;
}
.wm__empty p {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--ns-ink-3);
}
.wm__canvas {
  overflow-x: auto;
  padding: 8px 10px 0;
}
.wm__canvas svg {
  display: block;
  height: auto;
}
.wm__region {
  fill: var(--ns-card-2);
  stroke: var(--ns-line);
  stroke-dasharray: 3 4;
}
.wm__region--1 {
  fill: var(--ns-paper);
}
.wm__region--2 {
  fill: var(--ns-pink-soft);
  opacity: 0.5;
}
.wm__region--3 {
  fill: var(--ns-gold-soft, var(--ns-card-2));
}
.wm__group {
  font-family: var(--ns-serif);
  font-size: 12px;
  font-weight: 700;
  fill: var(--ns-ink);
}
.wm__trunk {
  stroke: var(--ns-line-2);
  stroke-width: 1.5;
}
.wm__edge {
  stroke: var(--ns-line);
  stroke-width: 1;
}
.wm__card {
  fill: var(--ns-card);
  stroke: var(--ns-line-2);
  stroke-width: 1;
}
.wm__node {
  cursor: pointer;
  outline: none;
}
.wm__node:hover .wm__card,
.wm__node:focus-visible .wm__card {
  stroke: var(--ns-pink-line);
  fill: var(--ns-card-2);
}
.wm__node.is-on .wm__card {
  stroke: var(--ns-pink);
  stroke-width: 2;
  fill: var(--ns-pink-soft);
}
.wm__label {
  font-family: var(--ns-serif);
  font-size: 12px;
  fill: var(--ns-ink-2);
  pointer-events: none;
}
.wm__node.is-on .wm__label {
  fill: var(--ns-ink);
  font-weight: 700;
}
.wm__detail {
  border-top: 1px solid var(--ns-line);
  padding: 12px 16px 14px;
  background: var(--ns-card-2);
}
.wm__detailhead {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.wm__detailhead b {
  font-family: var(--ns-serif);
  font-size: 14px;
}
.wm__owner {
  font-size: 11px;
  color: var(--ns-ink-3);
  padding: 1px 7px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-card);
  border: 1px solid var(--ns-line);
}
.wm__close {
  margin-left: auto;
  border: 0;
  background: transparent;
  color: var(--ns-ink-3);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 4px;
}
.wm__close:hover {
  color: var(--ns-ink);
}
.wm__detail dl {
  margin: 0;
  display: grid;
  gap: 5px;
}
.wm__detail dl > div {
  display: grid;
  grid-template-columns: 66px minmax(0, 1fr);
  gap: 10px;
  font-size: 12px;
  line-height: 1.6;
}
.wm__detail dt {
  color: var(--ns-ink-3);
  font-size: 11.5px;
}
.wm__detail dd {
  margin: 0;
  color: var(--ns-ink-2);
}
.wm__hint {
  margin: 0;
  padding: 8px 16px 12px;
  font-size: 11.5px;
  color: var(--ns-ink-3);
}
</style>

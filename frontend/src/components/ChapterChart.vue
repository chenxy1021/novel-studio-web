<script setup lang="ts">
import { computed, ref } from 'vue'

/**
 * 单序列柱图：最近几章的字数 + 一条硬下限参考线。
 * 低于下限的章用「警示色 + 斜纹」双编码，不靠颜色单独表意；颜色全部走 tokens，深浅色各自成对。
 */
const props = withDefaults(
  defineProps<{
    chapters: Array<{ number: number; title: string; chars: number; approved: boolean }>
    min: number
    limit?: number
  }>(),
  { limit: 12 },
)

// 同一页可能放多张图：pattern 的 id 必须唯一
const hatchId = `ns-hatch-${Math.random().toString(36).slice(2, 8)}`

const rows = computed(() => props.chapters.slice(-props.limit))
const hover = ref<number | null>(null)

const H = 40
const BASELINE = 34
const TOP = 6

const max = computed(() => {
  const peak = Math.max(...rows.value.map((c) => c.chars), 0)
  return Math.max(peak, props.min * 1.25, 1)
})

const slot = computed(() => (rows.value.length ? 100 / rows.value.length : 0))
// viewBox 是拉伸的：按槽位比例取 36%，在 650px 宽时约 23px，不会变成厚板
const barW = computed(() => Math.min(slot.value * 0.36, 4))

function barX(i: number) {
  return slot.value * i + (slot.value - barW.value) / 2
}
function barH(c: { chars: number }) {
  return Math.max((c.chars / max.value) * (BASELINE - TOP), c.chars > 0 ? 0.6 : 0)
}
function barY(c: { chars: number }) {
  return BASELINE - barH(c)
}
function capPath(i: number, c: { chars: number }) {
  const x = barX(i)
  const w = barW.value
  const y = barY(c)
  const h = barH(c)
  const r = Math.min(1.4, w / 2, h)
  if (h <= 0.8) return `M${x},${BASELINE} h${w} v${-Math.max(h, 0.6)} h${-w} Z`
  return `M${x},${BASELINE} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${BASELINE} Z`
}

const minY = computed(() => BASELINE - (props.min / max.value) * (BASELINE - TOP))
const below = computed(() => rows.value.filter((c) => c.approved && c.chars > 0 && c.chars < props.min))

function pctLeft(i: number) {
  return ((barX(i) + barW.value / 2) / 100) * 100
}

const tip = computed(() => {
  if (hover.value === null) return null
  const c = rows.value[hover.value]
  if (!c) return null
  return {
    ...c,
    left: pctLeft(hover.value),
    low: c.approved && c.chars > 0 && c.chars < props.min,
  }
})

const summary = computed(() => {
  const n = rows.value.length
  if (!n) return '暂无章节数据'
  const total = rows.value.reduce((s, c) => s + c.chars, 0)
  return `最近 ${n} 章字数柱图：合计 ${total} 字，硬下限 ${props.min} 字，${below.value.length} 章低于下限`
})
</script>

<template>
  <div class="chart">
    <svg
      class="chart__svg"
      :viewBox="`0 0 100 ${H}`"
      preserveAspectRatio="none"
      role="img"
      :aria-label="summary"
    >
      <defs>
        <pattern :id="hatchId" width="2.4" height="2.4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="2.4" height="2.4" fill="var(--ns-chart-over)" />
          <line x1="0" y1="0" x2="0" y2="2.4" stroke="var(--ns-card)" stroke-width="1.1" />
        </pattern>
      </defs>

      <line :x1="0" :x2="100" :y1="BASELINE" :y2="BASELINE" stroke="var(--ns-line-2)" stroke-width="0.35" vector-effect="non-scaling-stroke" />

      <path
        v-for="(c, i) in rows"
        :key="c.number"
        :d="capPath(i, c)"
        :fill="c.approved && c.chars > 0 && c.chars < min ? `url(#${hatchId})` : 'var(--ns-chart-bar)'"
        :class="{ 'chart__bar--hover': hover === i, 'chart__bar--dim': c.chars === 0 }"
        @mouseenter="hover = i"
        @mouseleave="hover = null"
      />

      <!-- 参考线画在柱子上层，深色主题下也不会被柱子盖住 -->
      <line
        :x1="0"
        :x2="100"
        :y1="minY"
        :y2="minY"
        stroke="var(--ns-ink-4)"
        stroke-width="0.4"
        stroke-dasharray="1.8 1.4"
        vector-effect="non-scaling-stroke"
      />
    </svg>

    <div class="chart__axis">
      <span v-if="rows.length" class="ns-mono">第 {{ rows[0].number }} 章</span>
      <span class="chart__axis-mid">下限 {{ min }} 字</span>
      <span v-if="rows.length" class="ns-mono">第 {{ rows[rows.length - 1].number }} 章</span>
    </div>

    <div v-if="tip" class="chart__tip" :style="{ left: `${tip.left}%` }">
      <b>第 {{ tip.number }} 章 · {{ tip.title }}</b>
      <span class="ns-num">{{ tip.chars }} 字</span>
      <span v-if="tip.low" class="chart__tipwarn">低于下限</span>
      <span v-else-if="!tip.approved" class="chart__tipwarn">待确认</span>
    </div>

    <p v-if="below.length" class="chart__foot">
      <i class="chart__swatch" aria-hidden="true" />
      {{ below.length }} 章低于 {{ min }} 字硬下限：第 {{ below.map((c) => c.number).join('、') }} 章
    </p>

    <table class="ns-sr-only">
      <caption>{{ summary }}</caption>
      <thead>
        <tr><th>章</th><th>标题</th><th>字数</th></tr>
      </thead>
      <tbody>
        <tr v-for="c in rows" :key="c.number">
          <td>{{ c.number }}</td>
          <td>{{ c.title }}</td>
          <td>{{ c.chars }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.chart {
  position: relative;
  padding-top: 2px;
}
.chart__svg {
  display: block;
  width: 100%;
  height: 104px;
  overflow: visible;
}
.chart__bar {
  transition: opacity 0.12s ease;
}
.chart__bar--hover {
  opacity: 0.72;
}
.chart__bar--dim {
  opacity: 0.35;
}
.chart__axis {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
  font-size: 10.5px;
  color: var(--ns-ink-4);
}
.chart__axis-mid {
  color: var(--ns-ink-3);
}
.chart__tip {
  position: absolute;
  top: -4px;
  transform: translateX(-50%);
  display: grid;
  gap: 1px;
  padding: 6px 9px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-ink);
  color: var(--ns-paper);
  font-size: 10.5px;
  white-space: nowrap;
  pointer-events: none;
  box-shadow: var(--ns-shadow-2);
  z-index: 3;
}
.chart__tip b {
  font-weight: 600;
}
.chart__tipwarn {
  color: #f3c98a;
}
.chart__foot {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 8px 0 0;
  font-size: 11px;
  color: var(--ns-warn);
}
.chart__swatch {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  background: repeating-linear-gradient(
    45deg,
    var(--ns-chart-over) 0 1.5px,
    var(--ns-card) 1.5px 3px
  );
  border: 1px solid var(--ns-chart-over);
}
</style>

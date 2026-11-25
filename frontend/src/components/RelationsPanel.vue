<script setup lang="ts">
/** 人物关系的三种看法：矩阵 / 明细列表 / AI 关系图。挂在「人物」页，不再从设定页进。 */
import { computed, ref } from 'vue'
import { Button, Card, EmptyState, Table, type Column } from '@/design'
import { useStudio } from '@/stores/studio'
import type { CharacterRelation } from '@/mocks'

const studio = useStudio()

const relView = ref<'matrix' | 'list' | 'graph'>('matrix')
const relationQ = ref('')

const relations = computed(() => studio.relations)

const canonicalName = computed(() => {
  const map = new Map<string, string>()
  for (const c of studio.characters) {
    map.set(c.name, c.name)
    for (const a of c.aliases) map.set(a, c.name)
  }
  return map
})
const canonOf = (raw: string) => canonicalName.value.get(raw) || raw

const matrixAxis = computed(() => {
  const involved = new Set<string>()
  for (const r of relations.value) {
    involved.add(canonOf(r.a))
    involved.add(canonOf(r.b))
  }
  const names: string[] = []
  const push = (name: string) => {
    if (name && !names.includes(name)) names.push(name)
  }
  // 先按人物卡顺序（核心在前），再补只出现在关系里的名字。
  for (const c of studio.characters) if (involved.has(c.name)) push(c.name)
  for (const r of relations.value) {
    push(canonOf(r.a))
    push(canonOf(r.b))
  }
  return names.map((name, i) => ({ name, index: i + 1 }))
})

const relationIndex = computed(() => {
  const map = new Map<string, CharacterRelation>()
  for (const r of relations.value) {
    const a = canonOf(r.a)
    const b = canonOf(r.b)
    if (!a || !b || a === b) continue
    map.set(`${a}\u0000${b}`, { ...r, a, b })
  }
  return map
})

const relationGraphSrc = computed(() =>
  studio.relationMapDoc.svg
    ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(studio.relationMapDoc.svg)}`
    : '',
)

const relationRows = computed(() => {
  const needle = relationQ.value.trim()
  return [...relations.value]
    .filter((r) => !needle || [r.a, r.b, r.state, r.note].join(' ').includes(needle))
    .sort((x, y) => (y.chapter || 0) - (x.chapter || 0) || x.a.localeCompare(y.a, 'zh'))
})

const relationCols: Column<CharacterRelation>[] = [
  { key: 'a', label: '甲', width: '15%' },
  { key: 'b', label: '乙', width: '15%' },
  { key: 'state', label: '当前关系', width: '24%' },
  { key: 'note', label: '备注 / 怎么变成这样' },
  {
    key: 'chapter',
    label: '截至章',
    align: 'right',
    width: '84px',
    render: (r: CharacterRelation) => (r.chapter ? `第 ${r.chapter} 章` : '—'),
  },
]

type MatrixEdge = { state: string; note: string; chapter: number; dir: '→' | '←' | '↔' }

function cellEdges(row: string, col: string): MatrixEdge[] {
  if (row === col) return []
  const direct = relationIndex.value.get(`${row}\u0000${col}`)
  const reverse = relationIndex.value.get(`${col}\u0000${row}`)
  if (direct && reverse && direct.state === reverse.state) {
    return [{
      state: direct.state,
      note: [direct.note, reverse.note].filter(Boolean).join('；'),
      chapter: Math.max(direct.chapter, reverse.chapter),
      dir: '↔',
    }]
  }
  const out: MatrixEdge[] = []
  if (direct) out.push({ state: direct.state, note: direct.note, chapter: direct.chapter, dir: '→' })
  if (reverse) out.push({ state: reverse.state, note: reverse.note, chapter: reverse.chapter, dir: '←' })
  return out
}

function cellTitle(row: string, col: string): string {
  const edges = cellEdges(row, col)
  if (!edges.length) return `${row} ↔ ${col}：设定里还没有这组关系`
  return edges.map((e) => {
    const head = e.dir === '↔' ? `${row} ↔ ${col}` : e.dir === '→' ? `${row} → ${col}` : `${col} → ${row}`
    const note = e.note ? `（${e.note}）` : ''
    const chapter = e.chapter ? ` · 截至第 ${e.chapter} 章` : ''
    return `${head}：${e.state || '有往来'}${note}${chapter}`
  }).join('\n')
}
</script>

<template>
  <Card flush>
    <div class="relbar">
      <div class="relviews" role="group" aria-label="人物关系的三种看法">
        <button
          type="button"
          :class="{ on: relView === 'matrix' }"
          :aria-pressed="relView === 'matrix'"
          @click="relView = 'matrix'"
        >关系矩阵</button>
        <button
          type="button"
          :class="{ on: relView === 'list' }"
          :aria-pressed="relView === 'list'"
          @click="relView = 'list'"
        >明细列表</button>
        <button
          type="button"
          :class="{ on: relView === 'graph' }"
          :aria-pressed="relView === 'graph'"
          @click="relView = 'graph'"
        >关系图</button>
      </div>
      <span class="relbar__meta">{{ matrixAxis.length }} 人 · {{ relations.length }} 组关系</span>
    </div>

    <div v-if="!relations.length" class="rel-empty">
      <EmptyState
        icon="人"
        title="还没有人物关系"
        desc="生成设定时会从大纲里拆出关系矩阵；写正文时关系变化会按章汇总到这里。"
      />
    </div>

    <div v-else-if="relView === 'matrix'" class="matrixwrap">
      <table class="relmatrix">
        <caption class="ns-sr-only">人物关系矩阵：行和列都是人物，单元格是两人当前关系</caption>
        <thead>
          <tr>
            <th class="corner" scope="col">#</th>
            <th v-for="c in matrixAxis" :key="c.name" scope="col">
              <span class="rn">{{ c.index }}</span><span class="nm">{{ c.name }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in matrixAxis" :key="row.name">
            <th scope="row">
              <span class="rn">{{ row.index }}</span><span class="nm">{{ row.name }}</span>
            </th>
            <td
              v-for="col in matrixAxis"
              :key="col.name"
              :class="{
                'is-diag': row.name === col.name,
                'has-rel': row.name !== col.name && cellEdges(row.name, col.name).length,
              }"
              :title="cellTitle(row.name, col.name)"
            >
              <template v-if="row.name === col.name">—</template>
              <template v-else-if="cellEdges(row.name, col.name).length">
                <span v-for="(e, i) in cellEdges(row.name, col.name)" :key="i" class="rmrel">
                  <i>{{ e.dir }}</i>{{ e.state || e.note || '有往来' }}
                </span>
              </template>
              <span v-else class="rmempty">·</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="matrixhint">
        行 → 列。单元格是两人当前关系；→ / ← 表示设定里只记了一个方向，↔ 表示两边说法一致。
        悬停看备注与截至章；备注多的时候切「明细列表」。
      </p>
    </div>

    <div v-else-if="relView === 'graph'" class="relgraph">
      <div class="relgraph__bar">
        <span>
          AI 按当前人物和关系画一张速览图；关系变了再点重画。
          <em v-if="studio.relationMapDoc.at">上次生成：{{ studio.relationMapDoc.at }}</em>
        </span>
        <Button
          icon="✦"
          variant="ghost"
          :disabled="studio.relationMapBusy"
          @click="studio.drawRelationMap()"
        >
          {{ studio.relationMapBusy ? '正在画…' : studio.relationMapDoc.svg ? '重新生成' : 'AI 生成关系图' }}
        </Button>
      </div>
      <div v-if="relationGraphSrc" class="relgraph__canvas">
        <img :src="relationGraphSrc" alt="AI 绘制的人物关系图" />
      </div>
      <div v-else class="rel-empty">
        <EmptyState
          icon="✦"
          title="还没有关系图"
          desc="由 AI 读取人物卡与关系数据绘制，不写死在代码里；换一本书也能画。"
        >
          <Button
            variant="pink"
            icon="✦"
            :disabled="studio.relationMapBusy"
            @click="studio.drawRelationMap()"
          >
            {{ studio.relationMapBusy ? '正在画…' : 'AI 生成关系图' }}
          </Button>
        </EmptyState>
      </div>
    </div>

    <template v-else>
      <div class="tablebar">
        <input
          v-model="relationQ"
          class="tablebar__search"
          placeholder="搜人物、关系状态或备注…"
          aria-label="搜索人物关系"
        />
        <span class="tablebar__meta">{{ relationRows.length }} 条 · 按截至章从新到旧</span>
      </div>
      <Table
        v-if="relationRows.length"
        class="reltable"
        :columns="relationCols"
        :rows="relationRows"
        dense
        striped
      />
      <div v-else class="rel-empty">
        <EmptyState icon="人" title="没有匹配的关系" desc="换个名字或关键词试试。" compact />
      </div>
    </template>
  </Card>
</template>

<style scoped>
.reltable {
  border: 0;
  border-radius: 0;
}
.rel-empty {
  padding: 18px;
}
.relbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border-bottom: 1px solid var(--ns-line);
}
.relviews {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-pill);
  background: var(--ns-card-2);
}
.relviews button {
  border: 0;
  border-radius: var(--ns-r-pill);
  background: transparent;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 11.5px;
  line-height: 1.6;
  padding: 3px 10px;
  cursor: pointer;
}
.relviews button:hover {
  color: var(--ns-ink);
}
.relviews button.on {
  background: var(--ns-card);
  color: var(--ns-ink);
  box-shadow: 0 1px 2px rgb(0 0 0 / 8%);
}
.relviews button:focus-visible {
  outline: none;
  box-shadow: var(--ns-focus);
}
.relbar__meta {
  margin-left: auto;
  font-size: 11px;
  color: var(--ns-ink-4);
}
.tablebar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border-bottom: 1px solid var(--ns-line);
}
.tablebar__search {
  flex: 0 1 300px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: 12px;
}
.tablebar__search:focus {
  outline: none;
  border-color: var(--ns-pink-line);
  box-shadow: var(--ns-focus);
}
.tablebar__meta {
  margin-left: auto;
  font-size: 11px;
  color: var(--ns-ink-4);
}
.matrixwrap {
  overflow: auto;
  max-height: 66vh;
}
.relmatrix {
  border-collapse: separate;
  border-spacing: 0;
  min-width: 100%;
  font-size: 11.5px;
}
.relmatrix th,
.relmatrix td {
  padding: 7px 8px;
  border-right: 1px solid var(--ns-line);
  border-bottom: 1px solid var(--ns-line);
  text-align: left;
  vertical-align: top;
}
.relmatrix thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--ns-card);
  color: var(--ns-ink-2);
  font-weight: 600;
  white-space: nowrap;
}
.relmatrix tbody th {
  position: sticky;
  left: 0;
  z-index: 1;
  min-width: 108px;
  background: var(--ns-card);
  color: var(--ns-ink-2);
  font-weight: 600;
  white-space: nowrap;
}
.relmatrix .corner {
  left: 0;
  z-index: 3;
  min-width: 54px;
  color: var(--ns-ink-4);
}
.relmatrix .rn {
  display: inline-block;
  min-width: 16px;
  margin-right: 5px;
  font-family: var(--ns-mono);
  font-size: 9.5px;
  font-weight: 500;
  color: var(--ns-ink-4);
}
.relmatrix td {
  min-width: 124px;
  max-width: 190px;
  background: var(--ns-card);
  color: var(--ns-ink-2);
  line-height: 1.55;
}
.relmatrix td.is-diag {
  background: var(--ns-card-2);
  color: var(--ns-ink-4);
  text-align: center;
}
.relmatrix td.has-rel {
  background: color-mix(in srgb, var(--ns-pink) 7%, var(--ns-card));
}
.rmrel {
  display: block;
  word-break: break-word;
}
.rmrel + .rmrel {
  margin-top: 3px;
  padding-top: 3px;
  border-top: 1px dashed var(--ns-line);
}
.rmrel i {
  display: inline-block;
  margin-right: 3px;
  font-style: normal;
  font-size: 10px;
  color: var(--ns-pink);
}
.rmempty {
  color: var(--ns-ink-4);
}
.matrixhint {
  margin: 0;
  padding: 8px 12px;
  border-top: 1px solid var(--ns-line);
  background: var(--ns-card-2);
  color: var(--ns-ink-4);
  font-size: 10.5px;
  line-height: 1.7;
}
.relgraph {
  padding: 14px;
}
.relgraph__bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
  color: var(--ns-ink-4);
  font-size: 11px;
}
.relgraph__bar em {
  margin-left: 6px;
  font-style: normal;
  color: var(--ns-ink-3);
}
.relgraph__canvas {
  border: 1px solid var(--ns-line);
  border-radius: 8px;
  overflow: hidden;
  background: #f7f2e7;
}
.relgraph__canvas img {
  display: block;
  width: 100%;
  height: auto;
}
</style>

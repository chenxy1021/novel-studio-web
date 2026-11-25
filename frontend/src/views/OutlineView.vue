<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Card, Tag } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import GenStream from '@/components/GenStream.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import StatTile from '@/components/StatTile.vue'
import WorldAtlas from '@/components/WorldAtlas.vue'
import { useStudio } from '@/stores/studio'
import { markdownHeadings } from '@/lib/markdown'
import { rangeLabel } from '@/lib/format'
import { frameOf, layerOf, layersOf, mapMode } from '@/lib/atlas'

type OutlineTab = 'structure' | 'world' | 'map'

const studio = useStudio()
const route = useRoute()
const router = useRouter()

const tab = ref<OutlineTab>(
  route.query.tab === 'world' ? 'world' : route.query.tab === 'map' ? 'map' : 'structure',
)
const chosen = ref<number | 'book'>(1)
const draft = ref('')

const volumes = computed(() => studio.data.outline)
const current = computed(() => (chosen.value === 'book' ? null : volumes.value.find((v) => v.index === chosen.value) ?? null))
const writtenChapters = computed(() => studio.sortedChapters.filter((c) => c.approved))

const bookLayerText = computed(() => {
  const b = studio.book
  if (b.outlineText?.trim()) return b.outlineText
  const vols = volumes.value
  return [
    `## 全书层`,
    ``,
    `- 一句话故事核：${b.spine || '—'}`,
    `- 主题：${b.theme || '—'}`,
    `- 终点：${b.targetChapters} 章`,
    `- 分支：${vols.map((v) => `卷${v.index}「${v.title}」${rangeLabel(v.range[0], v.range[1])}`).join('；') || '还没有卷'}`,
    ``,
    `还没有生成大纲。点右上角「生成大纲+世界观」，让模型从故事梗概里一次长出全书层、卷层和世界观。`,
  ].join('\n')
})

/** 从生成的大纲里截出某一卷的原文；卷头可能写「第N卷」，章号区间才是准的。 */
function sliceVolume(from: number, to: number): string {
  const text = studio.book.outlineText || ''
  if (!text) return ''
  const heads = [...text.matchAll(/^#{2,4}\s*第\s*\d+\s*[卷部].*$/gm)]
  for (let i = 0; i < heads.length; i += 1) {
    const h = heads[i]
    const start = h.index ?? 0
    const end = heads[i + 1]?.index ?? text.length
    const span = /第\s*(\d+)\s*[-–—~～至到]\s*(\d+)\s*章/.exec(h[0])
    if (span && Number(span[1]) === from && Number(span[2]) === to) return text.slice(start, end).trim()
  }
  return ''
}

const volumeText = computed(() => {
  const v = current.value
  if (!v) return ''
  const real = sliceVolume(v.range[0], v.range[1])
  if (real) return real
  const done = writtenChapters.value.filter((c) => c.number >= v.range[0] && c.number <= v.range[1])
  return [
    `### 第${v.index}卷 ${v.title}（${rangeLabel(v.range[0], v.range[1])}）`,
    ``,
    `- 任务与矛盾：${v.task}`,
    `- 已写：${done.length ? `第 ${done.map((c) => c.number).join('、')} 章` : '还没开写'}`,
    ``,
    `- 卷内节拍：`,
    ...v.beats.map((b, i) => `  ${i + 1}. ${b}`),
    ``,
    `- 卷末钩子：${v.hook}`,
    ``,
    `本卷写作时只按「细纲」页的段落纲走，卷层只决定这一段往哪儿去。`,
  ].join('\n')
})

/** 世界观正文优先用生成稿（project.worldText）；旧书没有生成稿时退回 bible/时间线汇总。 */
const worldText = computed(() => {
  if (studio.book.worldText?.trim()) return studio.book.worldText
  return [
    '## 1. 世界基底',
    '',
    studio.book.synopsis || studio.book.logline || '（项目里还没写简介）',
    '',
    '## 2. 历史与时间线',
    '',
    ...(studio.data.timeline.length
      ? studio.data.timeline.map((t) => `- 第 ${t.chapter} 章（第 ${t.inWorldDay} 日）：${t.summary}`)
      : ['（时间线账本还是空的）']),
    '',
    '## 3. 日常与氛围',
    '',
    ...(studio.data.world.length
      ? studio.data.world.map((w) => `**${w.name}**：${w.detail}`)
      : ['（bible 里还没有地点/世界条目）']),
    '',
    '> 还没有生成世界观。点右上角「生成大纲+世界观」：世界观和大纲一起从故事梗概里长出来。',
  ].join('\n')
})

const habits = computed(() => studio.data.world)
const ruleCount = computed(() => studio.data.rules.length)
const locations = computed(() => studio.data.locations)
const factions = computed(() => studio.data.factions)
const mapFrame = computed(() => frameOf(locations.value))
const mapLayers = computed(() => layersOf(locations.value, mapFrame.value))
const mapHint = computed(() =>
  mapMode(locations.value, mapFrame.value) === 'coords'
    ? '按设定坐标排布'
    : mapLayers.value.length > 1
      ? `由内向外：${mapLayers.value.map((l) => l.name).join(' · ')}`
      : '按范围分块',
)
const terrainCounts = computed(() => {
  const out = new Map<string, number>()
  for (const l of locations.value) {
    const key = l.terrain?.trim() || '未标注'
    out.set(key, (out.get(key) ?? 0) + 1)
  }
  return [...out.entries()].sort((a, b) => b[1] - a[1])
})

/** 阅读 / 原文两种视图，默认阅读。 */
const reading = ref(true)

/** 世界观小节导航：从 Markdown 标题来，锚点与渲染用的是同一套 slug。 */
const worldHeadings = computed(() => markdownHeadings(worldText.value).filter((h) => h.level >= 2))
function jumpTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

/** 卷长按实际区间统计，不再用目标章节数均分。 */
const volumeSpan = computed(() => {
  const lens = volumes.value.map((v) => Math.max(0, v.range[1] - v.range[0] + 1))
  if (!lens.length) return ''
  const min = Math.min(...lens)
  const max = Math.max(...lens)
  return min === max ? `每卷 ${min} 章` : `每卷 ${min}–${max} 章`
})

/** store 已 toast 错误；吞掉 rejection，避免未处理异常。 */
function generateBlueprint() {
  void studio.generateBlueprint(Boolean(studio.book.nuewen)).catch(() => {})
}

function setTab(next: OutlineTab) {
  tab.value = next
  const query = { ...route.query }
  if (next === 'structure') delete query.tab
  else query.tab = next
  void router.replace({ query })
}

watch(
  () => route.query.tab,
  (v) => {
    const next: OutlineTab = v === 'world' || v === 'map' ? v : 'structure'
    if (next !== tab.value) tab.value = next
  },
)

watch([chosen, () => studio.key, () => studio.book.outlineText], () => {
  draft.value = chosen.value === 'book' ? bookLayerText.value : volumeText.value
}, { immediate: true })
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="结构 · 世界观"
      title="大纲与世界观"
      desc="一次生成：大纲回答「这条路通不通、这一段往哪儿去」，世界观回答「人真正活在里面的规则」。正文按卷 + 段落纲推进。"
    >
      <Button
        variant="pink"
        icon="✎"
        :disabled="studio.blueprintBusy"
        @click="generateBlueprint"
      >
        {{ studio.blueprintBusy ? '正在生成大纲+世界观…' : studio.book.outlineText ? '换一版大纲+世界观' : '生成大纲+世界观' }}
      </Button>
    </PageHeader>

    <GenStream
      v-if="studio.liveGen.active && studio.liveGen.kind === 'blueprint'"
      :active="studio.liveGen.active"
      :text="studio.liveGen.text"
      :title="studio.liveGen.title"
      :stage="studio.liveGen.stage"
      :kind="studio.liveGen.kind"
      :started-at="studio.liveGen.startedAt"
      label="大纲 + 世界观"
      class="livegen"
    />

    <div class="tabs" role="tablist" aria-label="大纲与世界观">
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'structure'"
        :class="{ on: tab === 'structure' }"
        @click="setTab('structure')"
      >
        结构大纲
        <span class="ns-num">{{ volumes.length }} 卷</span>
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'world'"
        :class="{ on: tab === 'world' }"
        @click="setTab('world')"
      >
        世界观
        <span class="ns-num">{{ worldHeadings.length }} 节</span>
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'map'"
        :class="{ on: tab === 'map' }"
        @click="setTab('map')"
      >
        地图
        <span class="ns-num">{{ locations.length }} 处</span>
      </button>
    </div>

    <template v-if="tab === 'structure'">
      <div class="stats">
        <StatTile label="卷" :value="volumes.length" unit="卷" :note="volumes.length ? '来自 ledger/volumes.json' : '卷文件里还没有卷'" />
        <StatTile
          label="目标"
          :value="studio.book.targetChapters"
          unit="章"
          :note="volumes.length ? `${volumeSpan} · 按矛盾阶段切` : '还没有卷，先分卷'"
        />
        <StatTile label="已落笔" :value="writtenChapters.length" unit="章" :note="'正文已进索引的章'" />
        <StatTile
          label="段落纲"
          :value="studio.segList.length"
          unit="段"
          :note="`${studio.book.segmentSize} 章一段`"
          tone="gold"
        />
      </div>

      <div class="grid">
        <Card flush class="nav">
          <div class="nav__head">
            <span class="ns-eyebrow">结构导航</span>
            <Tag size="sm" tone="ink">只读</Tag>
          </div>
          <button type="button" class="nav__item" :class="{ on: chosen === 'book' }" @click="chosen = 'book'">
            <span class="nav__n">0</span>
            <span>
              <b>全书层</b>
              <small>故事核 · 主题 · 终点</small>
            </span>
          </button>
          <button
            v-for="v in volumes"
            :key="v.index"
            type="button"
            class="nav__item"
            :class="{ on: chosen === v.index }"
            @click="chosen = v.index"
          >
            <span class="nav__n">{{ v.index }}</span>
            <span class="nav__text">
              <b>{{ v.title }}</b>
              <small>{{ rangeLabel(v.range[0], v.range[1]) }} · {{ v.done }}/{{ v.range[1] - v.range[0] + 1 }}</small>
            </span>
            <i class="nav__ring" :style="{ '--p': `${Math.round((v.done / (v.range[1] - v.range[0] + 1)) * 100)}%` }" />
          </button>
          <div class="nav__hint">卷目按大纲里的「矛盾阶段」解析，卷长不固定；改卷范围要回「进度」页对齐真实章节。</div>
        </Card>

        <Card flush class="editor">
          <div class="editor__bar">
            <div class="editor__title">
              <span class="ns-eyebrow">第 {{ chosen === 'book' ? 0 : chosen }} 层</span>
              <b>{{ chosen === 'book' ? '全书层大纲' : current?.title }}</b>
              <span v-if="current" class="editor__range">{{ rangeLabel(current.range[0], current.range[1]) }}</span>
            </div>
            <div class="editor__tools">
              <Tag size="sm" tone="ink">{{ studio.book.outlineText ? 'AI 生成' : '未生成' }}</Tag>
              <button type="button" class="viewtoggle" @click="reading = !reading">
                {{ reading ? '看原文' : '看阅读版' }}
              </button>
              <span class="editor__words ns-num">{{ draft.length }} 字符</span>
            </div>
          </div>
          <MarkdownView v-if="reading" class="editor__doc" :source="draft" />
          <textarea v-else v-model="draft" class="editor__area" spellcheck="false" readonly aria-label="大纲原文" />
          <div class="editor__foot">
            <span>大纲来自「开书流程」的生成结果，存在 project.json；卷索引从「### 第N卷 卷名（第a-b章）」解析。</span>
            <span v-if="current" class="editor__hook">卷末钩子：<b>{{ current.hook }}</b></span>
          </div>
        </Card>
      </div>

      <Card title="全书节拍一览" desc="一条主线四个转折。点击某一卷只跳到编辑区，不会改任何数据。" class="beats">
        <div class="beats__row">
          <div v-for="v in volumes" :key="v.index" class="beat" :class="{ on: chosen === v.index }" @click="chosen = v.index">
            <div class="beat__head">
              <span class="beat__idx">卷 {{ v.index }}</span>
              <Tag size="sm" :tone="v.done ? 'ok' : 'neutral'">{{ v.done ? `${v.done} 章` : '未开写' }}</Tag>
            </div>
            <b class="beat__title">{{ v.title }}</b>
            <p class="beat__task">{{ v.task }}</p>
            <div class="beat__hook">↳ {{ v.hook }}</div>
          </div>
        </div>
      </Card>
    </template>

    <template v-else-if="tab === 'world'">
      <div class="world">
        <div class="world__side">
          <Card flush class="wnav">
            <div class="nav__head">
              <span class="ns-eyebrow">世界观导航</span>
              <Tag size="sm" tone="ink">{{ worldHeadings.length }} 节</Tag>
            </div>
            <button
              v-for="h in worldHeadings"
              :key="h.id"
              type="button"
              class="wnav__item"
              :class="{ 'wnav__item--sub': h.level >= 3 }"
              @click="jumpTo(h.id)"
            >
              <span class="wnav__dot" aria-hidden="true" />
              <span>{{ h.text }}</span>
            </button>
            <p v-if="!worldHeadings.length" class="nav__hint">还没有世界观小节。生成后这里会按标题列出导航。</p>
            <div class="nav__hint">
              地点 {{ locations.length }} · 势力 {{ factions.length }} · 规则 {{ ruleCount }} · 物品 {{ studio.data.items.length }}
              <br />
              <RouterLink class="wnav__link" :to="{ name: 'setup', query: { tab: 'locations' } }">去设定页 →</RouterLink>
            </div>
          </Card>

          <Card v-if="habits.length" flush class="habits">
            <div class="habits__head">
              <span class="ns-eyebrow">地点 / 世界条目</span>
              <Tag size="sm" tone="gold">{{ habits.length }} 条</Tag>
            </div>
            <ul class="habits__list">
              <li v-for="h in habits.slice(0, 8)" :key="h.key">
                <b>{{ h.name }}</b>
                <p>{{ h.detail }}</p>
              </li>
            </ul>
          </Card>
        </div>

        <div class="world__main">
          <Card flush>
            <div class="editor__bar">
              <span class="ns-eyebrow">世界观正文 · Markdown</span>
              <div class="editor__tools">
                <Tag size="sm" :tone="studio.book.worldText ? 'ok' : 'neutral'">{{ studio.book.worldText ? 'AI 生成' : '未生成' }}</Tag>
                <button type="button" class="viewtoggle" @click="reading = !reading">
                  {{ reading ? '看原文' : '看阅读版' }}
                </button>
                <span class="ns-num editor__words">{{ worldText.length }} 字符</span>
              </div>
            </div>
            <MarkdownView v-if="reading" class="editor__doc" :source="worldText" />
            <textarea v-else :value="worldText" class="editor__area" spellcheck="false" readonly aria-label="世界观原文" />
            <div class="editor__foot">世界观正文存在 project.json；人物、势力、规则、地点、物品在「设定」页从同一份大纲+世界观里拆出来。</div>
          </Card>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="stats">
        <StatTile
          label="地点"
          :value="locations.length"
          unit="处"
          :note="locations.length ? '来自 bible.locations' : '先在设定页拆出地点'"
        />
        <StatTile
          label="势力"
          :value="factions.length"
          unit="个"
          :note="factions.length ? '同势力用同一个色点' : '还没有势力归属'"
        />
        <StatTile
          label="分层"
          :value="mapLayers.length"
          unit="层"
          :note="mapLayers.length ? mapLayers.map((l) => `${l.name}${locations.filter((x) => layerOf(x, mapLayers, mapFrame)?.key === l.key).length}`).join(' · ') : '地点还没写层级'"
        />
        <StatTile
          label="地形"
          :value="terrainCounts.length"
          unit="类"
          :note="terrainCounts.slice(0, 3).map(([k, n]) => `${k}${n}`).join(' · ') || '还没有地形标签'"
        />
      </div>

      <Card flush class="atlas">
        <div class="editor__bar">
          <div class="editor__title">
            <span class="ns-eyebrow">地图 · 地点关系</span>
            <b>{{ studio.mapDoc.svg ? 'AI 地图 · 按设定里的地点生成' : mapHint }}</b>
          </div>
          <div class="editor__tools">
            <Tag size="sm" :tone="studio.mapDoc.svg ? 'ok' : 'neutral'">
              {{ studio.mapDoc.svg ? 'AI 绘制' : '结构图' }}
            </Tag>
            <Button
              size="sm"
              variant="ghost"
              :disabled="studio.mapBusy || locations.length < 2"
              @click="studio.drawMap()"
            >{{ studio.mapBusy ? '正在画…' : studio.mapDoc.svg ? '重画地图' : 'AI 画地图' }}</Button>
            <Button
              size="sm"
              variant="ghost"
              @click="router.push({ name: 'setup', query: { tab: 'locations' } })"
            >去设定页编辑地点 →</Button>
          </div>
        </div>
        <WorldAtlas :locations="locations" :factions="factions" :map-svg="studio.mapDoc.svg" />
        <div class="editor__foot">
          <span>点地点看注释。有坐标按坐标摆，没坐标按层级套圈；层名、方位、范围都取自地点自己的字段和 geo，不替作者编地形。</span>
        </div>
      </Card>
    </template>
  </div>
</template>

<style scoped>
.page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.livegen {
  margin-bottom: var(--ns-s4);
}
.tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--ns-line);
  margin-bottom: 16px;
  overflow-x: auto;
}
.tabs button {
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 13px;
  padding: 9px 14px 10px;
  cursor: pointer;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: -1px;
}
.tabs button:hover {
  color: var(--ns-ink);
}
.tabs button.on {
  color: var(--ns-ink);
  border-bottom-color: var(--ns-pink);
  font-weight: 600;
}
.tabs button span {
  font-size: 10.5px;
  background: var(--ns-card-2);
  border-radius: var(--ns-r-pill);
  padding: 0 6px;
  color: var(--ns-ink-3);
}
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.atlas :deep(.wa) {
  padding: 12px;
}
.atlas :deep(.wa__frame) {
  border: 0;
  border-radius: 0;
}
.grid {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  margin-bottom: 16px;
}
.world {
  display: grid;
  grid-template-columns: 288px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.world__side,
.world__main {
  display: grid;
  gap: 14px;
  align-items: start;
}
.wnav__item {
  width: 100%;
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 7px 14px;
  border: 0;
  background: transparent;
  font: inherit;
  font-size: 12.5px;
  color: var(--ns-ink-2);
  text-align: left;
  cursor: pointer;
  line-height: 1.5;
}
.wnav__item:hover {
  background: var(--ns-card-2);
  color: var(--ns-ink);
}
.wnav__item--sub {
  padding-left: 26px;
  font-size: 12px;
  color: var(--ns-ink-3);
}
.wnav__dot {
  width: 4px;
  height: 4px;
  flex: none;
  border-radius: 50%;
  background: var(--ns-ink-4);
  transform: translateY(-3px);
}
.wnav__item--sub .wnav__dot {
  background: var(--ns-line-2);
}
.wnav__link {
  color: var(--ns-pink-2);
  text-decoration: none;
}
.wnav__link:hover {
  text-decoration: underline;
}
.viewtoggle {
  border: 1px solid var(--ns-line-2);
  background: var(--ns-card);
  color: var(--ns-ink-2);
  border-radius: var(--ns-r-pill);
  padding: 2px 10px;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}
.viewtoggle:hover {
  border-color: var(--ns-ink-4);
  color: var(--ns-ink);
}
.editor__doc {
  padding: 18px 22px;
  min-height: clamp(360px, 46vh, 640px);
  max-height: 72vh;
  overflow: auto;
  background: var(--ns-card);
}
.nav__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 13px 14px 9px;
}
.nav__item {
  position: relative;
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  border: 0;
  background: transparent;
  font: inherit;
  color: var(--ns-ink-2);
  text-align: left;
  cursor: pointer;
}
.nav__item:hover {
  background: var(--ns-card-2);
}
.nav__item.on {
  background: var(--ns-pink-soft);
  color: var(--ns-ink);
}
.nav__item.on::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 2px;
  background: var(--ns-pink);
}
.nav__n {
  width: 22px;
  height: 22px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--ns-card);
  border: 1px solid var(--ns-line);
  font-family: var(--ns-serif);
  font-size: 11px;
  font-weight: 700;
}
.nav__text {
  display: grid;
  min-width: 0;
  line-height: 1.35;
}
.nav__text b,
.nav__item > span:nth-child(2) b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-13);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nav__item small {
  font-size: 10.5px;
  color: var(--ns-ink-3);
}
.nav__ring {
  position: absolute;
  right: 12px;
  top: 50%;
  width: 14px;
  height: 14px;
  margin-top: -7px;
  border-radius: 50%;
  background: conic-gradient(var(--ns-pink) var(--p), var(--ns-line) 0);
  opacity: 0.85;
}
.nav__item:first-of-type .nav__ring {
  display: none;
}
.nav__hint {
  padding: 12px 14px 14px;
  margin-top: 6px;
  border-top: 1px dashed var(--ns-line);
  font-size: 10.5px;
  color: var(--ns-ink-3);
  line-height: 1.6;
}
.editor__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 16px;
  background: var(--ns-card-2);
  border-bottom: 1px solid var(--ns-line);
  flex-wrap: wrap;
}
.editor__title {
  display: flex;
  align-items: baseline;
  gap: 9px;
  min-width: 0;
}
.editor__title b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
}
.editor__range {
  font-size: 11px;
  color: var(--ns-ink-3);
}
.editor__tools {
  display: flex;
  align-items: center;
  gap: 10px;
}
.editor__words {
  font-size: 11px;
  color: var(--ns-ink-3);
}
.editor__area {
  display: block;
  width: 100%;
  border: 0;
  outline: 0;
  resize: vertical;
  min-height: clamp(420px, 54vh, 640px);
  padding: 18px 22px;
  background: var(--ns-card);
  color: var(--ns-ink-2);
  font-family: var(--ns-serif);
  font-size: 14.5px;
  line-height: 1.95;
}
.editor__area:focus {
  background: var(--ns-paper);
}
.editor__foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 16px;
  border-top: 1px solid var(--ns-line);
  font-size: 11px;
  color: var(--ns-ink-3);
}
.editor__hook b {
  color: var(--ns-ink-2);
  font-weight: 600;
}
.beats__row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.beat {
  min-width: 0;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  padding: 11px 12px;
  background: var(--ns-card-2);
  cursor: pointer;
  display: grid;
  gap: 4px;
  align-content: start;
  transition: border-color 0.14s ease, background 0.14s ease;
}
.beat:hover,
.beat.on {
  border-color: var(--ns-pink-line);
  background: var(--ns-card);
}
.beat__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.beat__idx {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--ns-ink-3);
}
.beat__title {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
}
.beat__task {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--ns-ink-2);
  overflow-wrap: anywhere;
}
.beat__hook {
  font-size: 11px;
  color: var(--ns-pink-2);
  line-height: 1.55;
  border-top: 1px dashed var(--ns-line);
  padding-top: 6px;
  margin-top: 2px;
  overflow-wrap: anywhere;
}
.habits__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 13px 16px 4px;
}
.habits__list {
  list-style: none;
  margin: 0;
  padding: 6px 16px 8px;
}
.habits__list li {
  padding: 10px 0;
  border-bottom: 1px dashed var(--ns-line);
}
.habits__list li:last-child {
  border-bottom: 0;
}
.habits__list b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
}
.habits__list p {
  margin: 3px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.habits__foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid var(--ns-line);
  background: var(--ns-card-2);
  font-size: 11px;
  color: var(--ns-ink-3);
  flex-wrap: wrap;
}
@media (max-width: 1040px) {
  .stats,
  .beats__row {
    grid-template-columns: repeat(2, 1fr);
  }
  .grid,
  .world {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 620px) {
  .page {
    padding: 20px 16px 64px;
  }
}
</style>

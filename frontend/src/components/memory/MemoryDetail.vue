<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch, type ComponentPublicInstance } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Card, EmptyState, Tag } from '@/design'
import { useStudio } from '@/stores/studio'
import type { MemoryChapter, MemoryOverview, MemoryRelation, MemoryVolume } from '@/api/studio'
import {
  chapterCode,
  dimsLabels,
  parseCharacterState,
  volumeOfChapter,
} from './memory-helpers'

type DetailTab = 'volume' | 'character' | 'relation' | 'recall'

const props = withDefaults(
  defineProps<{
    memory: MemoryOverview | null
    chapters: MemoryChapter[]
    selected: number | null
    filterCharacter: string
    filterVolume: number | ''
    tab: DetailTab
    loading?: boolean
  }>(),
  { filterVolume: '', loading: false },
)
const emit = defineEmits<{
  'update:tab': [tab: DetailTab]
  select: [chapter: number]
  'generate-volume': [idx: number]
  'generate-chapter': [chapter: number]
}>()

const studio = useStudio()
const router = useRouter()

const tabs: Array<{ k: DetailTab; t: string }> = [
  { k: 'volume', t: '卷摘要' },
  { k: 'character', t: '人物' },
  { k: 'relation', t: '关系' },
  { k: 'recall', t: '回查' },
]

const volumes = computed<MemoryVolume[]>(() => props.memory?.volumes ?? [])
const currentChapter = computed(() => studio.book.gate.chapter || studio.nextNumber)
const sortedChapters = computed(() => [...props.chapters].sort((a, b) => a.chapter - b.chapter))
const itemRefs = new Map<number, HTMLElement>()

/* ---------------- 卷摘要 ---------------- */

const activeVolume = computed<MemoryVolume | null>(() => {
  if (props.filterVolume !== '') {
    const picked = volumes.value.find((v) => v.volume === props.filterVolume)
    if (picked) return picked
  }
  if (props.selected != null) {
    const hit = volumeOfChapter(props.selected, volumes.value)
    if (hit) return hit
  }
  const near = volumeOfChapter(currentChapter.value, volumes.value)
  return near ?? volumes.value[0] ?? null
})

const dimsRows = computed(() =>
  dimsLabels
    .map((d) => ({ ...d, value: String(activeVolume.value?.dims?.[d.key] ?? '').trim() }))
    .filter((d) => d.value),
)

const volumeMissing = computed(() => {
  const v = activeVolume.value
  if (!v) return 0
  return (props.memory?.chapters ?? []).filter(
    (c) => c.chapter >= v.from && c.chapter <= v.to && !c.summary,
  ).length
})

function setItemRef(n: number, el: Element | ComponentPublicInstance | null) {
  if (el instanceof HTMLElement) itemRefs.set(n, el)
  else itemRefs.delete(n)
}

function scrollToSelected() {
  if (props.tab !== 'volume' || props.selected == null) return
  nextTick(() => {
    itemRefs.get(props.selected as number)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })
}

watch(
  () => [props.selected, props.tab, props.chapters.length],
  () => scrollToSelected(),
  { immediate: true },
)
onMounted(() => scrollToSelected())

/* ---------------- 人物 ---------------- */

const charQuery = ref('')
const activeName = ref('')

const allNames = computed(() => {
  const names: string[] = []
  const add = (n: string) => {
    if (n && !names.includes(n)) names.push(n)
  }
  for (const c of props.memory?.characters ?? []) add(c.name)
  for (const ch of props.memory?.chapters ?? []) for (const n of ch.characters) add(n)
  return names
})

const filteredNames = computed(() => {
  const kw = charQuery.value.trim().toLowerCase()
  if (!kw) return allNames.value
  return allNames.value.filter((n) => n.toLowerCase().includes(kw))
})

const activeCharacter = computed(
  () => (props.memory?.characters ?? []).find((c) => c.name === activeName.value) ?? null,
)
const parsedState = computed(() => parseCharacterState(activeCharacter.value?.state ?? ''))
const bibleCharacter = computed(
  () => studio.characters.find((c) => c.name === activeName.value) ?? null,
)
const statusTag = computed(() => {
  const s = bibleCharacter.value?.status
  if (s === 'dead') return { text: '已死亡', tone: 'bad' as const }
  if (s === 'missing') return { text: '失踪', tone: 'warn' as const }
  return { text: '在场', tone: 'ok' as const }
})
const recentChange = computed(() => {
  const rel = parsedState.value.relations
  return rel.length ? rel[rel.length - 1] : null
})
const hasState = computed(
  () => parsedState.value.knows.length > 0 || parsedState.value.relations.length > 0,
)

function initActiveName() {
  const wanted = props.filterCharacter || (() => {
    const chapter = (props.memory?.chapters ?? []).find((c) => c.chapter === props.selected)
    return chapter?.characters[0] || allNames.value[0] || ''
  })()
  activeName.value = wanted && allNames.value.includes(wanted) ? wanted : allNames.value[0] ?? ''
}

watch(() => props.filterCharacter, initActiveName)
watch(() => props.memory, initActiveName, { immediate: true })
watch(allNames, () => {
  if (!activeName.value || !allNames.value.includes(activeName.value)) initActiveName()
})

/* ---------------- 关系 ---------------- */

type Edge = MemoryRelation
const edges = computed<Edge[]>(() => {
  const list = props.memory?.relations ?? []
  const who = props.filterCharacter.trim()
  if (!who) return [...list].sort((a, b) => b.chapter - a.chapter)
  return list
    .filter((e) => e.a === who || e.b === who || e.a.includes(who) || e.b.includes(who))
    .sort((a, b) => b.chapter - a.chapter)
})

/* ---------------- 回查 ---------------- */

const q = ref(studio.memoryQuery)
const hasSearched = ref(false)
const recallInput = ref<HTMLInputElement | null>(null)
const canSearch = computed(() => q.value.trim().length >= 2)
const hits = computed(() => studio.recallHits.slice(0, 6))

watch(q, (v) => {
  if (v.trim().length < 2) {
    hasSearched.value = false
    studio.clearRecall()
  }
})

watch(
  () => props.tab,
  (tab) => {
    if (tab === 'recall') nextTick(() => recallInput.value?.focus())
  },
)

function runRecall() {
  if (!canSearch.value) return
  hasSearched.value = true
  void studio.recallMemory(q.value.trim())
}

function goChapter(n: number) {
  router.push({ name: 'progress', query: { chapter: String(n) } })
}
</script>

<template>
  <div class="md">
    <div class="md__tabs" role="tablist" aria-label="叙事记忆">
      <button
        v-for="t in tabs"
        :key="t.k"
        type="button"
        role="tab"
        :aria-selected="tab === t.k"
        :class="{ on: tab === t.k }"
        @click="emit('update:tab', t.k)"
      >
        {{ t.t }}
      </button>
    </div>

    <div v-if="loading" class="md__skeleton" aria-label="正在加载叙事记忆">
      <div v-for="i in 2" :key="i" class="md__bone">
        <i class="md__boneline md__boneline--head" />
        <i class="md__boneline" />
        <i class="md__boneline" />
        <i class="md__boneline md__boneline--short" />
      </div>
    </div>

    <!-- 卷摘要 -->
    <div v-else-if="tab === 'volume'" class="md__pane">
      <Card v-if="activeVolume" class="md__volume">
        <div class="md__volhead">
          <div>
            <div class="ns-eyebrow">本卷摘要</div>
            <h3>{{ activeVolume.title || `第${activeVolume.volume}卷` }}</h3>
            <p class="md__range">覆盖第 {{ activeVolume.from }}–{{ activeVolume.to }} 章</p>
          </div>
          <Button
            size="sm"
            variant="ghost"
            :disabled="studio.memoryGen.running"
            @click="emit('generate-volume', activeVolume.volume)"
          >
            重算卷摘要
          </Button>
        </div>

        <p v-if="activeVolume.summary" class="md__summary">{{ activeVolume.summary }}</p>
        <p v-else class="md__muted">这一卷还没有卷摘要。</p>

        <dl v-if="dimsRows.length" class="md__dims">
          <div v-for="d in dimsRows" :key="d.key" class="md__dim">
            <dt>{{ d.label }}</dt>
            <dd>{{ d.value }}</dd>
          </div>
        </dl>

        <p v-if="volumeMissing" class="md__warn">
          这一卷还有 {{ volumeMissing }} 章没生成记忆，卷摘要会不完整。
        </p>

        <div class="md__volfoot">
          <span>覆盖第 {{ activeVolume.from }}–{{ activeVolume.to }} 章</span>
          <span v-if="activeVolume.at">· 生成于 {{ activeVolume.at }}</span>
        </div>
      </Card>

      <Card v-else class="md__volume">
        <EmptyState
          compact
          icon="◷"
          title="这一卷还没有卷摘要"
          desc="卷摘要基于章记忆汇总：先把这一卷的章记忆补齐，再生成卷摘要。"
        />
      </Card>

      <div v-if="sortedChapters.length" class="md__chapters">
        <div
          v-for="c in sortedChapters"
          :key="c.chapter"
          :ref="(el) => setItemRef(c.chapter, el)"
          class="md__chapter"
          :class="{ 'md__chapter--on': selected === c.chapter, 'md__chapter--blank': !c.summary }"
          @click="emit('select', c.chapter)"
        >
          <div class="md__chead">
            <span class="ns-mono md__cno">{{ chapterCode(c.chapter) }}</span>
            <b>{{ c.title || `第 ${c.chapter} 章` }}</b>
            <button type="button" class="md__go" @click.stop="goChapter(c.chapter)">去这一章 →</button>
          </div>
          <p v-if="c.summary" class="md__csummary">{{ c.summary }}</p>
          <p v-else class="md__muted">记忆待补</p>
          <ul v-if="c.events.length" class="md__cevents">
            <li v-for="(e, i) in c.events.slice(0, 2)" :key="`${c.chapter}-e${i}`">{{ e }}</li>
          </ul>
          <div v-if="!c.summary" class="md__cacts">
            <button type="button" class="md__gen" @click.stop="emit('generate-chapter', c.chapter)">补写</button>
          </div>
        </div>
      </div>
      <EmptyState
        v-else
        compact
        icon="⌕"
        title="没有符合筛选的章节"
        desc="清除筛选，或去生成更多记忆。"
      />
    </div>

    <!-- 人物 -->
    <div v-else-if="tab === 'character'" class="md__pane">
      <div class="md__peoplebar">
        <input
          v-model="charQuery"
          class="md__search"
          type="search"
          placeholder="搜人物…"
          aria-label="搜索人物"
        />
        <div class="md__people">
          <button
            v-for="name in filteredNames"
            :key="name"
            type="button"
            class="md__personbtn"
            :class="{ on: activeName === name }"
            @click="activeName = name"
          >
            {{ name }}
          </button>
        </div>
      </div>

      <template v-if="activeCharacter && hasState">
        <Card class="md__person">
          <div class="md__personhead">
            <h3>{{ activeCharacter.name }}</h3>
            <Tag size="sm" :tone="statusTag.tone">{{ statusTag.text }}</Tag>
            <span class="md__asof">截至第 {{ activeCharacter.chapter }} 章</span>
          </div>

          <section v-if="parsedState.knows.length" class="md__block">
            <div class="ns-eyebrow">知道什么</div>
            <p v-for="(k, i) in parsedState.knows.slice(0, 4)" :key="`k-${i}`" class="md__line">
              第 {{ k.chapter }} 章知道：{{ k.text }}
            </p>
          </section>

          <section v-if="parsedState.relations.length" class="md__block">
            <div class="ns-eyebrow">关系</div>
            <p v-for="(r, i) in parsedState.relations.slice(0, 4)" :key="`r-${i}`" class="md__line">
              与{{ r.other }}：{{ r.text }}（第 {{ r.chapter }} 章）
            </p>
          </section>

          <section v-if="recentChange" class="md__block">
            <div class="ns-eyebrow">最近变化</div>
            <p class="md__line">第 {{ recentChange.chapter }} 章：{{ recentChange.text }}</p>
          </section>
        </Card>
      </template>

      <EmptyState
        v-else
        compact
        icon="人"
        title="这个人物还没有状态记忆"
        desc="生成记忆后，会显示他截至当前章知道什么、和谁是什么关系。"
      />
    </div>

    <!-- 关系 -->
    <div v-else-if="tab === 'relation'" class="md__pane">
      <div v-if="edges.length" class="md__edges">
        <div v-for="(e, i) in edges" :key="`${e.a}-${e.b}-${i}`" class="md__edge">
          <div class="md__edgename">{{ e.a }} ↔ {{ e.b }}</div>
          <div class="md__edgestate">{{ e.state }}</div>
          <div class="md__edgefoot">
            <span>最后变化 · 第 {{ e.chapter }} 章</span>
            <button type="button" class="md__go" @click="goChapter(e.chapter)">去这一章 →</button>
          </div>
        </div>
      </div>
      <EmptyState v-else compact icon="↔" title="还没有关系变化记录" />
    </div>

    <!-- 回查 -->
    <div v-else class="md__pane">
      <div class="md__recallbar">
        <input
          ref="recallInput"
          v-model="q"
          class="md__search md__search--wide"
          type="search"
          placeholder="输入人名、地点、物件、伏笔名（至少两个字）"
          aria-label="关键词回查"
          @keydown.enter.prevent="runRecall"
        />
        <Button size="sm" :disabled="!canSearch || studio.recallBusy" @click="runRecall">
          {{ studio.recallBusy ? '回查中…' : '回查' }}
        </Button>
      </div>

      <p v-if="hits.length" class="md__hitmeta">
        命中 {{ studio.recallHits.length }} 处，按相关度显示前 6 处
      </p>

      <div class="md__hits" :class="{ 'md__hits--dim': studio.recallBusy }">
        <div v-for="(h, i) in hits" :key="`${h.chapter}-${i}`" class="md__hit">
          <div class="md__hithead">
            <span>第 {{ h.chapter }} 章《{{ h.title }}》</span>
            <Tag size="sm" tone="neutral">记忆</Tag>
            <button type="button" class="md__go" @click="goChapter(h.chapter)">去这一章 →</button>
          </div>
          <p class="md__hittext">{{ h.text }}</p>
        </div>
      </div>

      <EmptyState
        v-if="hasSearched && !studio.recallBusy && !hits.length"
        compact
        icon="⌕"
        title="没找到相关的记忆或正文"
        :desc="`没找到「${q.trim()}」相关的记忆或正文。换个说法（人名/地点/物件/伏笔名）再查。`"
      />
      <p v-else-if="!hasSearched && !hits.length" class="md__muted">
        输入至少两个字再回查；结果会带章号出处。
      </p>
    </div>
  </div>
</template>

<style scoped>
.md {
  display: grid;
  gap: var(--ns-s3);
  min-width: 0;
}
.md__tabs {
  display: inline-flex;
  padding: 2px;
  gap: 1px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  align-self: start;
}
.md__tabs button {
  border: 0;
  background: transparent;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 11.5px;
  padding: 4px 12px;
  border-radius: 4px;
  cursor: pointer;
}
.md__tabs button.on {
  background: var(--ns-card);
  color: var(--ns-ink);
  font-weight: 600;
  box-shadow: var(--ns-shadow-1);
}
.md__pane {
  display: grid;
  gap: var(--ns-s3);
  min-width: 0;
}
.md__volhead {
  display: flex;
  align-items: flex-start;
  gap: var(--ns-s3);
}
.md__volhead > div {
  flex: 1;
  min-width: 0;
}
.md__volhead h3,
.md__personhead h3 {
  margin: 3px 0 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-18);
}
.md__range,
.md__volfoot {
  margin: 4px 0 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  font-variant-numeric: tabular-nums;
}
.md__summary {
  margin: var(--ns-s3) 0 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  line-height: 1.85;
}
.md__dims {
  display: grid;
  gap: 6px;
  margin: var(--ns-s3) 0 0;
}
.md__dim {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: var(--ns-s2);
  padding-top: 6px;
  border-top: 1px dashed var(--ns-line);
}
.md__dim dt {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.md__dim dd {
  margin: 0;
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  line-height: 1.7;
}
.md__warn {
  margin: var(--ns-s3) 0 0;
  padding: 6px 8px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-warn-soft);
  color: var(--ns-warn);
  font-size: var(--ns-fs-11);
}
.md__volfoot {
  display: flex;
  gap: var(--ns-s1);
  padding-top: var(--ns-s3);
  border-top: 1px dashed var(--ns-line);
}
.md__chapters {
  display: grid;
  gap: var(--ns-s2);
}
.md__chapter {
  padding: var(--ns-s3);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  cursor: pointer;
  transition: border-color 0.12s ease, background 0.12s ease;
}
.md__chapter:hover {
  background: var(--ns-card-2);
}
.md__chapter--on {
  border-color: var(--ns-pink-line);
  background: var(--ns-pink-soft);
}
.md__chead {
  display: flex;
  align-items: baseline;
  gap: var(--ns-s2);
  flex-wrap: wrap;
}
.md__chead b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-13);
}
.md__cno {
  color: var(--ns-ink-4);
  font-size: var(--ns-fs-11);
}
.md__go {
  margin-left: auto;
  border: 0;
  background: transparent;
  padding: 0;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: var(--ns-fs-11);
  cursor: pointer;
}
.md__go:hover {
  color: var(--ns-ink);
  text-decoration: underline;
}
.md__csummary {
  margin: 6px 0 0;
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  line-height: 1.75;
}
.md__cevents {
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 2px;
}
.md__cevents li {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.md__cevents li::before {
  content: '· ';
  color: var(--ns-ink-4);
}
.md__cacts {
  margin-top: 6px;
}
.md__gen {
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-xs);
  background: var(--ns-card);
  color: var(--ns-ink-2);
  padding: 1px 8px;
  font: inherit;
  font-size: var(--ns-fs-11);
  cursor: pointer;
}
.md__peoplebar {
  display: grid;
  gap: var(--ns-s2);
}
.md__search {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: 12.5px;
  outline: none;
}
.md__search:focus {
  border-color: var(--ns-pink);
  box-shadow: var(--ns-focus);
}
.md__people {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  max-height: 112px;
  overflow: auto;
}
.md__personbtn {
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-pill);
  background: var(--ns-card);
  color: var(--ns-ink-2);
  padding: 2px 9px;
  font: inherit;
  font-size: var(--ns-fs-11);
  cursor: pointer;
}
.md__personbtn.on {
  border-color: var(--ns-pink);
  background: var(--ns-pink-soft);
  color: var(--ns-pink);
}
.md__personhead {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  flex-wrap: wrap;
}
.md__asof {
  margin-left: auto;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  font-variant-numeric: tabular-nums;
}
.md__block {
  margin-top: var(--ns-s3);
  padding-top: var(--ns-s3);
  border-top: 1px dashed var(--ns-line);
}
.md__line {
  margin: 5px 0 0;
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  line-height: 1.7;
}
.md__edges {
  display: grid;
  gap: var(--ns-s2);
}
.md__edge {
  padding: var(--ns-s3);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
}
.md__edgename {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
}
.md__edgestate {
  margin-top: 4px;
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  line-height: 1.7;
}
.md__edgefoot {
  display: flex;
  align-items: center;
  margin-top: 6px;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.md__recallbar {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
}
.md__search--wide {
  flex: 1;
  min-width: 0;
}
.md__hitmeta {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.md__hits {
  display: grid;
  gap: var(--ns-s2);
  transition: opacity 0.15s ease;
}
.md__hits--dim {
  opacity: 0.45;
}
.md__hit {
  padding: var(--ns-s3);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
}
.md__hithead {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-2);
  flex-wrap: wrap;
}
.md__hittext {
  margin: 6px 0 0;
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  line-height: 1.75;
}
.md__muted {
  margin: var(--ns-s2) 0 0;
  color: var(--ns-ink-4);
  font-size: var(--ns-fs-11);
}
.md__skeleton {
  display: grid;
  gap: var(--ns-s3);
}
.md__bone {
  padding: var(--ns-s3);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
}
.md__boneline {
  display: block;
  height: 8px;
  margin-top: 8px;
  border-radius: 3px;
  background: var(--ns-card-2);
}
.md__boneline--head {
  width: 38%;
  margin-top: 0;
}
.md__boneline--short {
  width: 60%;
}
@media (max-width: 600px) {
  .md__dim {
    grid-template-columns: 1fr;
  }
  .md__search--wide {
    width: 100%;
  }
  .md__recallbar {
    flex-wrap: wrap;
  }
}
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, EmptyState } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import MemoryTimeline from '@/components/memory/MemoryTimeline.vue'
import MemoryDetail from '@/components/memory/MemoryDetail.vue'
import MemoryGenerateModal from '@/components/memory/MemoryGenerateModal.vue'
import { useStudio } from '@/stores/studio'
import type { MemoryChapter, MemoryTimelineEvent } from '@/api/studio'
import { splitPlaces } from '@/components/memory/memory-helpers'

type DetailTab = 'volume' | 'character' | 'relation' | 'recall'
type NarrowTab = 'timeline' | 'memory'

const studio = useStudio()
const route = useRoute()
const router = useRouter()

const filterVolume = ref<number | ''>('')
const filterCharacter = ref('')
const filterPlace = ref('')
const keywordInput = ref('')
const keyword = ref('')
const missingOpen = ref(false)
const selected = ref<number | null>(null)
const detailTab = ref<DetailTab>('volume')
const genOpen = ref(false)
const narrowTab = ref<NarrowTab>(route.query.tab === 'memory' ? 'memory' : 'timeline')
let debounce: ReturnType<typeof setTimeout> | undefined

const memory = computed(() => studio.memory)
const chapters = computed<MemoryChapter[]>(() => studio.memory?.chapters ?? [])
const timeline = computed<MemoryTimelineEvent[]>(() => studio.memory?.timeline ?? [])
const volumes = computed(() => studio.memory?.volumes ?? [])
const coverage = computed(() => studio.memory?.coverage ?? null)
const loading = computed(() => studio.memoryBusy || (!studio.memory && !studio.memoryError))
const currentChapter = computed(() => studio.nextNumber)

const tlByChapter = computed(() => {
  const map = new Map<number, MemoryTimelineEvent[]>()
  for (const row of timeline.value) {
    const list = map.get(row.chapter) ?? []
    list.push(row)
    map.set(row.chapter, list)
  }
  return map
})

function charactersOf(c: MemoryChapter): string[] {
  const set = new Set(c.characters)
  for (const e of tlByChapter.value.get(c.chapter) ?? []) for (const n of e.characters) set.add(n)
  return [...set]
}

function placesOf(c: MemoryChapter): string[] {
  const out: string[] = []
  for (const e of tlByChapter.value.get(c.chapter) ?? []) {
    for (const p of splitPlaces(e.place)) if (!out.includes(p)) out.push(p)
  }
  return out
}

const characterOptions = computed(() => {
  const set = new Set<string>()
  for (const c of chapters.value) for (const n of charactersOf(c)) set.add(n)
  for (const c of memory.value?.characters ?? []) set.add(c.name)
  return [...set].filter(Boolean).sort((a, b) => a.localeCompare(b, 'zh'))
})

const placeOptions = computed(() => {
  const set = new Set<string>()
  for (const e of timeline.value) for (const p of splitPlaces(e.place)) set.add(p)
  return [...set].sort((a, b) => a.localeCompare(b, 'zh'))
})

const volumeRange = computed(() => volumes.value.find((v) => v.volume === filterVolume.value) ?? null)

const filteredChapters = computed(() => {
  const kw = keyword.value.toLowerCase()
  return chapters.value.filter((c) => {
    if (filterVolume.value !== '') {
      const v = volumeRange.value
      if (!v || c.chapter < v.from || c.chapter > v.to) return false
    }
    if (filterCharacter.value && !charactersOf(c).includes(filterCharacter.value)) return false
    if (filterPlace.value && !placesOf(c).includes(filterPlace.value)) return false
    if (kw) {
      const hay = [
        c.title,
        c.summary,
        c.storyTime,
        c.characters.join(' '),
        c.events.join(' '),
        (tlByChapter.value.get(c.chapter) ?? []).map((e) => `${e.place} ${e.event}`).join(' '),
      ]
        .join(' ')
        .toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
})

const hasFilters = computed(
  () => filterVolume.value !== '' || !!filterCharacter.value || !!filterPlace.value || !!keyword.value,
)

const hasTextNoMemory = computed(
  () => chapters.value.length > 0 && (coverage.value?.chaptersWithMemory ?? 0) === 0,
)

const missing = computed(() => coverage.value?.missing ?? [])

function isNarrow() {
  return typeof window !== 'undefined' && window.matchMedia('(max-width: 899px)').matches
}

function setNarrowTab(tab: NarrowTab) {
  narrowTab.value = tab
  const query = { ...route.query }
  if (tab === 'memory') query.tab = 'memory'
  else delete query.tab
  void router.replace({ query })
}

function selectChapter(n: number) {
  selected.value = n
  if (isNarrow()) setNarrowTab('memory')
}

function clearFilters() {
  filterVolume.value = ''
  filterCharacter.value = ''
  filterPlace.value = ''
  keywordInput.value = ''
  keyword.value = ''
}

async function generateChapter(n: number) {
  await studio.generateChapterMemory(n, { force: false })
  selected.value = n
}

async function generateVolume(idx: number) {
  await studio.generateVolumeMemory(idx, { force: true })
}

function openRecall() {
  detailTab.value = 'recall'
  setNarrowTab('memory')
}

function goWrite() {
  void router.push({ name: 'workflow' })
}

watch(keywordInput, (v) => {
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(() => {
    keyword.value = v.trim()
  }, 300)
})

watch(
  () => route.query.tab,
  (v) => {
    const tab: NarrowTab = v === 'memory' ? 'memory' : 'timeline'
    if (tab !== narrowTab.value) narrowTab.value = tab
  },
)

watch(
  chapters,
  (list) => {
    if (selected.value != null && list.some((c) => c.chapter === selected.value)) return
    const n = currentChapter.value
    selected.value = list.some((c) => c.chapter === n) ? n : list[0]?.chapter ?? null
  },
  { immediate: true },
)

onMounted(() => {
  if (!studio.memory) void studio.loadMemory()
})
onBeforeUnmount(() => {
  if (debounce) clearTimeout(debounce)
})
</script>

<template>
  <div class="page memory">
    <PageHeader
      eyebrow="自动回写 · 时间线 · 回查"
      title="记忆"
      desc="写完一章，AI 自动把故事内时间、出场人物、关键事件和伏笔回写进来；这里只读回查，不用手写。每条都带章号出处。"
    >
      <Button
        v-if="missing.length"
        variant="pink"
        icon="◷"
        :disabled="studio.memoryBusy || !chapters.length"
        @click="genOpen = true"
      >补齐 {{ missing.length }} 章记忆</Button>
      <Button
        v-else
        variant="ghost"
        icon="◷"
        :disabled="studio.memoryBusy || !chapters.length"
        @click="genOpen = true"
      >重算记忆…</Button>
      <Button icon="⌕" :disabled="!chapters.length" @click="openRecall">关键词回查</Button>
    </PageHeader>

    <EmptyState
      v-if="studio.memoryError && !memory && !studio.memoryBusy"
      icon="!"
      title="记忆加载失败"
      :desc="studio.memoryError"
    >
      <Button variant="ghost" @click="studio.loadMemory()">重试</Button>
    </EmptyState>

    <EmptyState
      v-else-if="memory && !coverage?.chaptersWithText"
      icon="◷"
      title="还没有正文，也就还没有记忆"
      desc="记忆不用手写：写完一章，AI 会把故事内时间、地点、出场人物、关键事件自动回写到这里。"
    >
      <Button variant="pink" @click="goWrite">去开写</Button>
    </EmptyState>

    <template v-else>
      <div class="mtools" :class="{ 'mtools--off': studio.memoryBusy }">
        <label class="mtool">
          <span>卷</span>
          <select v-model="filterVolume" :disabled="studio.memoryBusy">
            <option :value="''">全部卷</option>
            <option v-for="v in volumes" :key="v.volume" :value="v.volume">
              第{{ v.volume }}卷{{ v.title ? ` · ${v.title}` : '' }}
            </option>
          </select>
        </label>
        <label class="mtool">
          <span>人物</span>
          <select v-model="filterCharacter" :disabled="studio.memoryBusy">
            <option value="">全部</option>
            <option v-for="n in characterOptions" :key="n" :value="n">{{ n }}</option>
          </select>
        </label>
        <label class="mtool">
          <span>地点</span>
          <select v-model="filterPlace" :disabled="studio.memoryBusy">
            <option value="">全部</option>
            <option v-for="p in placeOptions" :key="p" :value="p">{{ p }}</option>
          </select>
        </label>
        <input
          v-model="keywordInput"
          class="mtools__search"
          type="search"
          placeholder="⌕ 关键词"
          aria-label="按关键词过滤章节"
          :disabled="studio.memoryBusy"
        />
        <button v-if="hasFilters" type="button" class="mtools__clear" @click="clearFilters">
          清除筛选
        </button>
        <button type="button" class="mtools__cov" @click="missingOpen = !missingOpen">
          已回写 {{ coverage?.chaptersWithMemory ?? 0 }}/{{ coverage?.chaptersWithText ?? 0 }} 章
          · 缺 {{ missing.length }} 章
          · 卷摘要 {{ coverage?.volumesWithMemory ?? 0 }}/{{ coverage?.volumes ?? 0 }}
        </button>
      </div>

      <div v-if="missingOpen" class="mmissing">
        <span class="mmissing__label">缺记忆的章</span>
        <template v-if="missing.length">
          <button
            v-for="n in missing"
            :key="n"
            type="button"
            class="mmissing__chip"
            @click="selectChapter(n)"
          >
            第 {{ n }} 章
          </button>
        </template>
        <span v-else class="mmissing__empty">没有缺口</span>
      </div>

      <div v-if="hasTextNoMemory" class="mnotice">
        <div>
          <b>这 {{ chapters.length }} 章正文还没有回写记忆</b>
          <p>多半是旧稿或上次回写失败；补齐后，写新章会自动带上这些前情。</p>
        </div>
        <Button size="sm" variant="pink" :disabled="studio.memoryBusy" @click="genOpen = true">
          补齐记忆
        </Button>
      </div>

      <div class="mnarrow" role="tablist" aria-label="记忆分区">
        <button
          type="button"
          role="tab"
          :aria-selected="narrowTab === 'timeline'"
          :class="{ on: narrowTab === 'timeline' }"
          @click="setNarrowTab('timeline')"
        >
          时间线
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="narrowTab === 'memory'"
          :class="{ on: narrowTab === 'memory' }"
          @click="setNarrowTab('memory')"
        >
          叙事记忆
        </button>
      </div>

      <div class="mgrid">
        <section class="mpane mpane--timeline" :class="{ 'mpane--hidden': narrowTab !== 'timeline' }">
          <MemoryTimeline
            v-if="loading || filteredChapters.length"
            :chapters="filteredChapters"
            :timeline="timeline"
            :relations="memory?.relations ?? []"
            :volumes="volumes"
            :selected="selected"
            :loading="loading"
            @select="selectChapter"
            @generate="generateChapter"
            @generate-all="genOpen = true"
            @goto-write="goWrite"
          />
          <EmptyState
            v-else
            icon="⌕"
            title="没有符合筛选的章节"
            desc="清除筛选，或去生成更多记忆。"
          >
            <Button variant="ghost" @click="clearFilters">清除筛选</Button>
          </EmptyState>
        </section>

        <section class="mpane mpane--detail" :class="{ 'mpane--hidden': narrowTab !== 'memory' }">
          <MemoryDetail
            :memory="memory"
            :chapters="filteredChapters"
            :selected="selected"
            :filter-character="filterCharacter"
            :filter-volume="filterVolume"
            :tab="detailTab"
            :loading="loading"
            @update:tab="detailTab = $event"
            @select="selectChapter"
            @generate-volume="generateVolume"
            @generate-chapter="generateChapter"
          />
        </section>
      </div>
    </template>

    <MemoryGenerateModal
      :open="genOpen"
      :memory="memory"
      :selected="selected"
      @close="genOpen = false"
    />
  </div>
</template>

<style scoped>
.page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.memory {
  min-width: 0;
}
.mtools {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  flex-wrap: wrap;
  padding: var(--ns-s2) var(--ns-s3);
  margin-bottom: var(--ns-s3);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: color-mix(in srgb, var(--ns-paper) 92%, transparent);
  backdrop-filter: blur(6px);
}
.mtools--off {
  opacity: 0.6;
}
.mtool {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
}
.mtool select {
  padding: 4px 6px;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-xs);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: var(--ns-fs-12);
}
.mtools__search {
  flex: 1;
  min-width: 120px;
  max-width: 240px;
  padding: 5px 9px;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-xs);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: var(--ns-fs-12);
  outline: none;
}
.mtools__search:focus {
  border-color: var(--ns-pink);
  box-shadow: var(--ns-focus);
}
.mtools__clear {
  border: 0;
  background: transparent;
  color: var(--ns-pink);
  font: inherit;
  font-size: var(--ns-fs-11);
  cursor: pointer;
}
.mtools__cov {
  margin-left: auto;
  border: 0;
  background: transparent;
  color: var(--ns-ink-2);
  font: inherit;
  font-size: var(--ns-fs-11);
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  text-align: left;
}
.mtools__cov:hover {
  color: var(--ns-ink);
}
.mmissing {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  margin: -6px 0 var(--ns-s3);
  padding: 7px var(--ns-s3);
  border: 1px dashed var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.mmissing__label {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.mmissing__chip {
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-pill);
  background: var(--ns-card);
  color: var(--ns-ink-2);
  padding: 1px 8px;
  font: inherit;
  font-size: var(--ns-fs-11);
  cursor: pointer;
}
.mmissing__chip:hover {
  border-color: var(--ns-pink);
  color: var(--ns-pink);
}
.mmissing__empty {
  color: var(--ns-ink-4);
  font-size: var(--ns-fs-11);
}
.mnotice {
  display: flex;
  align-items: center;
  gap: var(--ns-s4);
  margin-bottom: var(--ns-s3);
  padding: var(--ns-s3);
  border: 1px solid var(--ns-pink-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-pink-soft);
}
.mnotice > div {
  flex: 1;
  min-width: 0;
}
.mnotice b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
}
.mnotice p {
  margin: 3px 0 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.mnarrow {
  display: none;
  gap: 2px;
  margin-bottom: var(--ns-s3);
  padding: 3px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.mnarrow button {
  flex: 1;
  border: 0;
  border-radius: var(--ns-r-xs);
  background: transparent;
  color: var(--ns-ink-3);
  padding: 6px;
  font: inherit;
  font-size: var(--ns-fs-12);
  cursor: pointer;
}
.mnarrow button.on {
  background: var(--ns-card);
  color: var(--ns-ink);
  font-weight: 600;
  box-shadow: var(--ns-shadow-1);
}
.mgrid {
  display: grid;
  grid-template-columns: 58fr 42fr;
  gap: var(--ns-s4);
  align-items: start;
}
.mpane {
  min-width: 0;
}
@media (max-width: 1179px) {
  .mgrid {
    grid-template-columns: minmax(0, 1fr);
  }
  .mtools {
    position: static;
  }
}
@media (max-width: 899px) {
  .mnarrow {
    display: flex;
  }
  .mpane--hidden {
    display: none;
  }
  .mtools__cov {
    margin-left: 0;
  }
  .mtools__search {
    max-width: none;
  }
}
@media (max-width: 620px) {
  .page {
    padding: 20px 16px 64px;
  }
}
</style>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, EmptyState, Tag } from '@/design'
import { useStudio } from '@/stores/studio'
import type { MemoryChapter, MemoryRelation, MemoryTimelineEvent, MemoryVolume } from '@/api/studio'
import { chapterCode, groupChapters, splitPlaces, type ChapterGroup } from './memory-helpers'

const props = withDefaults(
  defineProps<{
    chapters: MemoryChapter[]
    timeline: MemoryTimelineEvent[]
    relations: MemoryRelation[]
    volumes: MemoryVolume[]
    selected: number | null
    loading?: boolean
  }>(),
  { loading: false },
)
const emit = defineEmits<{
  select: [chapter: number]
  generate: [chapter: number]
  'generate-all': []
  'goto-write': []
}>()

const studio = useStudio()
const router = useRouter()

const overrides = ref<Record<string, boolean>>({})
const expandedEvents = ref<number[]>([])

const currentChapter = computed(() => studio.nextNumber)
/** 当前写作章可能还没落正文：退到最后一章，保证默认有卷展开。 */
const focusChapter = computed(() => {
  const n = currentChapter.value
  if (props.chapters.some((c) => c.chapter === n)) return n
  return props.chapters[props.chapters.length - 1]?.chapter ?? n
})
const groups = computed(() => groupChapters(props.chapters, props.volumes))

const timelineByChapter = computed(() => {
  const map = new Map<number, MemoryTimelineEvent[]>()
  for (const row of props.timeline) {
    const list = map.get(row.chapter) ?? []
    list.push(row)
    map.set(row.chapter, list)
  }
  return map
})

const relationByChapter = computed(() => {
  const map = new Map<number, MemoryRelation[]>()
  for (const row of props.relations) {
    const list = map.get(row.chapter) ?? []
    list.push(row)
    map.set(row.chapter, list)
  }
  return map
})

function eventsOf(c: MemoryChapter): string[] {
  if (c.events.length) return c.events
  const seen = new Set<string>()
  const out: string[] = []
  for (const row of timelineByChapter.value.get(c.chapter) ?? []) {
    if (!row.event || seen.has(row.event)) continue
    seen.add(row.event)
    out.push(row.event)
  }
  return out
}

/** 这一章里发生在过去的事件（回忆），用来在事件行前加小标。 */
function flashbackEventsOf(n: number): Set<string> {
  const out = new Set<string>()
  for (const row of timelineByChapter.value.get(n) ?? []) {
    if (row.flashback && row.event) out.add(row.event)
  }
  return out
}

function placesOf(c: MemoryChapter): string[] {
  const out: string[] = []
  for (const row of timelineByChapter.value.get(c.chapter) ?? []) {
    for (const p of splitPlaces(row.place)) if (!out.includes(p)) out.push(p)
  }
  return out
}

function charactersOf(c: MemoryChapter): string[] {
  if (c.characters.length) return c.characters
  const out: string[] = []
  for (const row of timelineByChapter.value.get(c.chapter) ?? []) {
    for (const name of row.characters) if (!out.includes(name)) out.push(name)
  }
  return out
}

type ForeshadowMark = { label: '埋' | '收'; name: string }
function foreshadowsOf(n: number): ForeshadowMark[] {
  const out: ForeshadowMark[] = []
  for (const f of studio.foreshadows) {
    if (f.plantedChapter === n) out.push({ label: '埋', name: f.name })
    if (f.dueChapter === n) out.push({ label: '收', name: f.name })
  }
  return out
}

function isOpen(g: ChapterGroup) {
  const forced = overrides.value[g.key]
  if (forced != null) return forced
  return g.chapters.some((c) => c.chapter === focusChapter.value || c.chapter === props.selected)
}

function toggle(g: ChapterGroup) {
  overrides.value = { ...overrides.value, [g.key]: !isOpen(g) }
}

function showMore(n: number) {
  expandedEvents.value = expandedEvents.value.includes(n)
    ? expandedEvents.value.filter((x) => x !== n)
    : [...expandedEvents.value, n]
}

function goChapter(n: number) {
  router.push({ name: 'progress', query: { chapter: String(n) } })
}

function selectChapter(n: number) {
  emit('select', n)
}
</script>

<template>
  <div class="tl">
    <div v-if="loading" class="tl__skeleton" aria-label="正在加载记忆">
      <div v-for="i in 5" :key="i" class="tl__bone">
        <i class="tl__boneline tl__boneline--head" />
        <i class="tl__boneline" />
        <i class="tl__boneline tl__boneline--short" />
      </div>
    </div>

    <EmptyState
      v-else-if="!chapters.length"
      icon="◷"
      title="还没有正文，也就还没有记忆"
      desc="记忆不用手写：每写完一章，AI 会把故事内时间、地点、出场人物、关键事件回写到这里。"
    >
      <Button variant="pink" @click="emit('goto-write')">去开写</Button>
    </EmptyState>

    <div v-else class="tl__groups">
      <section v-for="g in groups" :key="g.key" class="tl__group">
        <button
          type="button"
          class="tl__grouphead"
          :aria-expanded="isOpen(g)"
          @click="toggle(g)"
        >
          <span class="tl__caret" :class="{ 'tl__caret--open': isOpen(g) }" aria-hidden="true">▸</span>
          <b>{{ g.title }}</b>
          <span class="tl__range">{{ g.from }}–{{ g.to }}</span>
        </button>

        <div v-if="isOpen(g)" class="tl__rows">
          <article
            v-for="c in g.chapters"
            :key="c.chapter"
            class="tl__row"
            :class="{
              'tl__row--on': selected === c.chapter,
              'tl__row--blank': !c.summary,
              'tl__row--past': c.isFlashback,
            }"
            tabindex="0"
            :aria-current="selected === c.chapter ? 'true' : undefined"
            @click="selectChapter(c.chapter)"
            @keydown.enter.prevent="selectChapter(c.chapter)"
          >
            <div class="tl__head">
              <span class="tl__no ns-mono">{{ chapterCode(c.chapter) }}</span>
              <span class="tl__chapter">第 {{ c.chapter }} 章</span>
              <b class="tl__title">{{ c.title }}</b>
              <Tag v-if="c.isFlashback" size="sm" tone="gold">回忆章</Tag>
              <span v-if="c.summary" class="tl__time" :class="{ 'tl__time--none': !c.storyTime }">
                <template v-if="c.isFlashback">回忆 · </template>{{ c.storyTime || '未标注时间' }}
              </span>
            </div>

            <template v-if="!c.summary">
              <div class="tl__missing">
                <span>记忆待补</span>
                <button
                  type="button"
                  class="tl__gen"
                  @click.stop="emit('generate', c.chapter)"
                >
                  补写
                </button>
              </div>
            </template>

            <template v-else>
              <div v-if="placesOf(c).length || charactersOf(c).length" class="tl__chips">
                <span v-for="p in placesOf(c).slice(0, 3)" :key="`p-${p}`" class="tl__place">
                  <Tag size="sm" tone="neutral">{{ p }}</Tag>
                </span>
                <span class="tl__chars">
                  <span v-for="name in charactersOf(c).slice(0, 4)" :key="`c-${name}`" class="tl__chip">{{ name }}</span>
                  <span v-if="charactersOf(c).length > 4" class="tl__chip tl__chip--more">
                    +{{ charactersOf(c).length - 4 }}
                  </span>
                </span>
              </div>

              <ul v-if="eventsOf(c).length" class="tl__events">
                <li
                  v-for="(event, i) in expandedEvents.includes(c.chapter) ? eventsOf(c) : eventsOf(c).slice(0, 3)"
                  :key="`${c.chapter}-${i}`"
                >
                  <span v-if="flashbackEventsOf(c.chapter).has(event)" class="tl__fb">回忆</span>
                  <span>{{ event }}</span>
                </li>
              </ul>
              <p v-else class="tl__muted">这一章还没提炼事件</p>

              <div v-if="foreshadowsOf(c.chapter).length" class="tl__marks">
                <span v-for="(f, i) in foreshadowsOf(c.chapter)" :key="`f-${i}`" class="tl__mark">
                  {{ f.label }} · {{ f.name }}
                </span>
              </div>

              <div v-if="(relationByChapter.get(c.chapter) ?? []).length" class="tl__rels">
                <span
                  v-for="(r, i) in (relationByChapter.get(c.chapter) ?? [])"
                  :key="`r-${i}`"
                  class="tl__rel"
                >
                  状态 {{ r.a }} ↔ {{ r.b }}：{{ r.state }}
                </span>
              </div>

              <div class="tl__acts">
                <button
                  v-if="eventsOf(c).length > 3"
                  type="button"
                  class="tl__textbtn"
                  @click.stop="showMore(c.chapter)"
                >
                  {{ expandedEvents.includes(c.chapter) ? '收起' : '展开全部' }}
                </button>
                <button type="button" class="tl__golink" @click.stop="goChapter(c.chapter)">
                  去这一章 →
                </button>
              </div>
            </template>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.tl {
  min-width: 0;
}
.tl__groups {
  display: grid;
  gap: var(--ns-s4);
}
.tl__group {
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  overflow: hidden;
}
.tl__grouphead {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  width: 100%;
  padding: 9px var(--ns-s3);
  border: 0;
  background: var(--ns-card-2);
  color: var(--ns-ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.tl__grouphead b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
}
.tl__range {
  margin-left: auto;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  font-variant-numeric: tabular-nums;
}
.tl__caret {
  color: var(--ns-ink-4);
  font-size: 10px;
  transition: transform 0.15s ease;
}
.tl__caret--open {
  transform: rotate(90deg);
}
.tl__rows {
  position: relative;
  padding: 0 var(--ns-s3) var(--ns-s3);
}
.tl__rows::before {
  content: '';
  position: absolute;
  left: 18px;
  top: 4px;
  bottom: 12px;
  width: 1px;
  background: var(--ns-line);
}
.tl__row {
  position: relative;
  margin-top: var(--ns-s2);
  padding: var(--ns-s2) var(--ns-s3) var(--ns-s2) var(--ns-s4);
  border: 1px solid transparent;
  border-radius: var(--ns-r-sm);
  background: transparent;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease;
}
.tl__row::before {
  content: '';
  position: absolute;
  left: 4px;
  top: 15px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ns-card);
  border: 1px solid var(--ns-line-2);
}
.tl__row:hover {
  background: var(--ns-card-2);
}
.tl__row--on {
  background: var(--ns-pink-soft);
  border-color: var(--ns-pink-line);
}
.tl__row--on::before {
  background: var(--ns-pink);
  border-color: var(--ns-pink);
}
.tl__row--past::before {
  border-style: dashed;
  border-color: var(--ns-gold);
}
.tl__fb {
  flex: none;
  align-self: flex-start;
  margin-top: 1px;
  padding: 0 5px;
  border: 1px solid color-mix(in srgb, var(--ns-gold) 45%, var(--ns-line));
  border-radius: var(--ns-r-xs);
  color: var(--ns-gold);
  font-size: 10px;
  line-height: 16px;
}
.tl__head {
  display: flex;
  align-items: baseline;
  gap: var(--ns-s2);
  flex-wrap: wrap;
}
.tl__no {
  color: var(--ns-ink-4);
  font-size: var(--ns-fs-11);
}
.tl__chapter {
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
}
.tl__title {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-13);
}
.tl__time {
  margin-left: auto;
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-11);
}
.tl__time--none {
  color: var(--ns-ink-4);
}
.tl__chips {
  display: flex;
  align-items: center;
  gap: var(--ns-s1);
  flex-wrap: wrap;
  margin-top: 5px;
}
.tl__place {
  display: inline-flex;
}
.tl__chars {
  display: inline-flex;
  gap: 4px;
  flex-wrap: wrap;
}
.tl__chip {
  padding: 0 5px;
  border-radius: var(--ns-r-xs);
  background: var(--ns-card-2);
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-11);
  line-height: 17px;
}
.tl__chip--more {
  color: var(--ns-ink-4);
}
.tl__events {
  margin: 5px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 2px;
}
.tl__events li {
  display: flex;
  gap: 6px;
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  line-height: 1.6;
}
.tl__events li::before {
  content: '·';
  color: var(--ns-ink-4);
}
.tl__muted {
  margin: 5px 0 0;
  color: var(--ns-ink-4);
  font-size: var(--ns-fs-11);
}
.tl__marks,
.tl__rels {
  display: flex;
  flex-wrap: wrap;
  gap: 4px var(--ns-s3);
  margin-top: 4px;
}
.tl__mark {
  color: var(--ns-gold);
  font-size: var(--ns-fs-11);
}
.tl__rel {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.tl__acts {
  display: flex;
  align-items: center;
  gap: var(--ns-s3);
  margin-top: 5px;
}
.tl__textbtn,
.tl__golink {
  border: 0;
  background: transparent;
  padding: 0;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: var(--ns-fs-11);
  cursor: pointer;
}
.tl__textbtn {
  color: var(--ns-pink);
}
.tl__golink {
  margin-left: auto;
  color: var(--ns-ink-2);
}
.tl__golink:hover,
.tl__textbtn:hover {
  text-decoration: underline;
}
.tl__missing {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  margin-top: 5px;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
}
.tl__gen {
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-xs);
  background: var(--ns-card);
  color: var(--ns-ink-2);
  padding: 0 7px;
  font: inherit;
  font-size: var(--ns-fs-11);
  cursor: pointer;
}
.tl__skeleton {
  display: grid;
  gap: var(--ns-s2);
}
.tl__bone {
  padding: var(--ns-s3);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
}
.tl__boneline {
  display: block;
  height: 8px;
  margin-top: 7px;
  border-radius: 3px;
  background: var(--ns-card-2);
}
.tl__boneline--head {
  width: 40%;
  margin-top: 0;
}
.tl__boneline--short {
  width: 62%;
}
@media (max-width: 600px) {
  .tl__chips {
    display: none;
  }
  .tl__no {
    display: none;
  }
}
</style>

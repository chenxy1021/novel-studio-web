<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, Card, Tag, EmptyState } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import { useStudio } from '@/stores/studio'
import { segmentStages } from '@/mocks'
import type { BibleCharacter } from '@/mocks'

const studio = useStudio()
const q = ref('')
const status = ref<'all' | 'active' | 'missing' | 'dead'>('all')
const selected = ref<string | null>(null)

const list = computed(() =>
  studio.data.characters.filter((c) => {
    if (status.value !== 'all' && c.status !== status.value) return false
    if (!q.value.trim()) return true
    return [c.name, c.role, c.identity, c.want, c.fear].join(' ').includes(q.value.trim())
  }),
)
const current = computed<BibleCharacter | null>(() => list.value.find((c) => c.name === selected.value) ?? list.value[0] ?? null)

const statusLabel: Record<BibleCharacter['status'], string> = { active: '在场', missing: '失踪', dead: '死亡' }
const statusTone: Record<BibleCharacter['status'], 'ok' | 'warn' | 'bad'> = { active: 'ok', missing: 'warn', dead: 'bad' }

const appearances = computed(() =>
  current.value ? studio.sortedChapters.filter((c) => current.value!.appears.includes(c.number)) : [],
)
const stageOf = computed(() => {
  const c = current.value
  if (!c) return null
  for (const seg of studio.segList) {
    const stage = segmentStages(seg).find((st) => st.cast.includes(c.name))
    if (stage) return { seg, stage }
  }
  return null
})

function syncSettings() {
  studio.toast('已从正文补齐人物空白字段（不覆盖已填内容）', 'ok')
}

function callAgent() {
  studio.toast(`已把「设计 ${current.value?.name} 的人物弧线」交给 Agent（只写，不替换已有设定）`, 'info')
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="谁在推动故事"
      title="人物"
      desc="每个人物只写四件事：他想要什么、怕什么、瞒着什么、怎么说话。其余的交给正文去长。"
    >
      <Button variant="ghost" @click="syncSettings">从正文补齐</Button>
      <Button variant="pink" icon="＋">新建人物</Button>
    </PageHeader>

    <div class="filters">
      <input v-model="q" class="search" placeholder="搜名字、身份、欲望、恐惧…" aria-label="搜索人物" />
      <div class="segmented">
        <button
          v-for="s in [
            { k: 'all', t: `全部 ${studio.data.characters.length}` },
            { k: 'active', t: '在场' },
            { k: 'missing', t: '失踪' },
            { k: 'dead', t: '死亡' },
          ]"
          :key="s.k"
          type="button"
          :class="{ on: status === s.k }"
          @click="status = s.k as typeof status"
        >
          {{ s.t }}
        </button>
      </div>
      <span class="filters__meta">收录 {{ studio.data.characters.length }} 人 · 正文已出场 {{ studio.data.characters.filter((c) => c.appears.length).length }} 人</span>
    </div>

    <div v-if="current" class="grid">
      <Card flush class="roster">
        <button
          v-for="c in list"
          :key="c.name"
          type="button"
          class="person"
          :class="{ on: current.name === c.name }"
          @click="selected = c.name"
        >
          <span class="person__avatar" :style="{ background: c.color }">{{ c.name.slice(0, 1) }}</span>
          <span class="person__text">
            <b>{{ c.name }}</b>
            <small>{{ c.role }}</small>
          </span>
          <span class="person__side">
            <Tag size="sm" :tone="statusTone[c.status]">{{ statusLabel[c.status] }}</Tag>
            <small class="ns-num">出场 {{ c.appears.length }}</small>
          </span>
        </button>
      </Card>

      <div class="ns-stack">
        <Card flush>
          <div class="profile">
            <div class="profile__avatar" :style="{ background: current.color }">{{ current.name.slice(0, 1) }}</div>
            <div class="profile__head">
              <div class="profile__name">
                <h2>{{ current.name }}</h2>
                <Tag size="sm" :tone="statusTone[current.status]">{{ statusLabel[current.status] }}</Tag>
                <Tag size="sm">出场 {{ current.appears.length }} 章</Tag>
              </div>
              <p>{{ current.role }} · {{ current.identity }}</p>
            </div>
            <div class="profile__acts">
              <Button size="sm" variant="ghost" @click="callAgent">让 Agent 拆弧线</Button>
              <Button size="sm">编辑</Button>
            </div>
          </div>
          <div class="quad">
            <div class="quad__cell">
              <span class="ns-eyebrow">想要</span>
              <p>{{ current.want }}</p>
            </div>
            <div class="quad__cell">
              <span class="ns-eyebrow">害怕</span>
              <p>{{ current.fear }}</p>
            </div>
            <div class="quad__cell quad__cell--secret">
              <span class="ns-eyebrow">瞒着</span>
              <p>{{ current.secret }}</p>
            </div>
            <div class="quad__cell">
              <span class="ns-eyebrow">怎么说话</span>
              <p class="ns-serif">{{ current.voice }}</p>
            </div>
          </div>
        </Card>

        <Card title="出场时间轴" desc="按章号排。人物设定和正文对不上时，通常先坏在这里。">
          <div class="timeline">
            <div class="timeline__axis" />
            <button
              v-for="c in appearances"
              :key="c.number"
              type="button"
              class="tick"
              :style="{ left: `${((c.number - 1) / Math.max(1, studio.book.targetChapters - 1)) * 100}%` }"
              :title="`第 ${c.number} 章 · ${c.title}`"
              @click="$router.push({ name: 'progress' })"
            >
              <i />
              <span>{{ c.number }}</span>
            </button>
          </div>
          <div v-if="stageOf" class="firstbeat">
            <span class="ns-eyebrow">当前段落的角色任务</span>
            <p>
              <b>第 {{ stageOf.stage.chapters[0] }}–{{ stageOf.stage.chapters[stageOf.stage.chapters.length - 1] }} 章</b>
              ：{{ stageOf.stage.goal }}
            </p>
          </div>
        </Card>
      </div>
    </div>
    <EmptyState v-else icon="人" title="没搜到这个人" desc="换个关键词，或者点右上「新建人物」。" />
  </div>
</template>

<style scoped>
.page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.filters {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.search {
  flex: 0 1 280px;
  height: 32px;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  padding: 0 12px;
  font: inherit;
  font-size: 12.5px;
  color: var(--ns-ink);
  outline: none;
}
.search:focus {
  border-color: var(--ns-pink);
  box-shadow: var(--ns-focus);
}
.segmented {
  display: inline-flex;
  padding: 2px;
  gap: 1px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.segmented button {
  border: 0;
  background: transparent;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 11.5px;
  padding: 4px 11px;
  border-radius: 4px;
  cursor: pointer;
}
.segmented button.on {
  background: var(--ns-card);
  color: var(--ns-ink);
  font-weight: 600;
  box-shadow: var(--ns-shadow-1);
}
.filters__meta {
  margin-left: auto;
  font-size: 11px;
  color: var(--ns-ink-3);
}
.grid {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.roster {
  padding: 6px;
}
.person {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border: 0;
  background: transparent;
  border-radius: var(--ns-r-sm);
  font: inherit;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.person:hover {
  background: var(--ns-card-2);
}
.person.on {
  background: var(--ns-pink-soft);
}
.person__avatar {
  width: 30px;
  height: 30px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--ns-r-sm);
  color: #fff;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  font-weight: 700;
  opacity: 0.92;
}
.person__text {
  flex: 1;
  min-width: 0;
  display: grid;
  line-height: 1.35;
}
.person__text b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-13);
}
.person__text small {
  color: var(--ns-ink-3);
  font-size: 10.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.person__side {
  display: grid;
  justify-items: end;
  gap: 2px;
}
.person__side small {
  font-size: 10px;
  color: var(--ns-ink-3);
}
.profile {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px 16px;
  flex-wrap: wrap;
}
.profile__avatar {
  width: 56px;
  height: 56px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--ns-r-lg);
  color: #fff;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-22);
  font-weight: 700;
}
.profile__head {
  flex: 1;
  min-width: 0;
}
.profile__name {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.profile__name h2 {
  margin: 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-22);
  font-weight: 700;
}
.profile__head p {
  margin: 4px 0 0;
  color: var(--ns-ink-3);
  font-size: 12.5px;
}
.profile__acts {
  display: flex;
  gap: 6px;
}
.quad {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-top: 1px solid var(--ns-line);
}
.quad__cell {
  padding: 14px 20px;
  border-right: 1px solid var(--ns-line);
  border-bottom: 1px solid var(--ns-line);
}
.quad__cell:nth-child(2n) {
  border-right: 0;
}
.quad__cell:nth-last-child(-n + 2) {
  border-bottom: 0;
}
.quad__cell--secret {
  background: var(--ns-gold-soft);
}
.quad__cell p {
  margin: 4px 0 0;
  font-size: 13px;
  line-height: 1.75;
  color: var(--ns-ink-2);
}
.quad__cell p.ns-serif {
  font-size: var(--ns-fs-14);
}
.timeline {
  position: relative;
  height: 46px;
  margin: 4px 10px 2px;
}
.timeline__axis {
  position: absolute;
  left: 0;
  right: 0;
  top: 26px;
  height: 1px;
  background: var(--ns-line-2);
}
.tick {
  position: absolute;
  top: 14px;
  transform: translateX(-50%);
  display: grid;
  justify-items: center;
  gap: 3px;
  border: 0;
  background: transparent;
  cursor: pointer;
  padding: 0;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 9.5px;
  font-variant-numeric: tabular-nums;
}
.tick i {
  width: 3px;
  height: 13px;
  border-radius: 2px;
  background: var(--ns-pink);
  opacity: 0.85;
}
.tick:hover i {
  height: 18px;
  margin-top: -5px;
}
.firstbeat {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--ns-line);
}
.firstbeat p {
  margin: 3px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
@media (max-width: 960px) {
  .grid,
  .quad {
    grid-template-columns: 1fr;
  }
  .quad__cell {
    border-right: 0;
  }
}
@media (max-width: 620px) {
  .page {
    padding: 20px 16px 64px;
  }
}
</style>

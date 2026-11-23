<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Card, Tag } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import StatTile from '@/components/StatTile.vue'
import { useStudio } from '@/stores/studio'
import { rangeLabel } from '@/lib/format'

const studio = useStudio()
const chosen = ref<number | 'book'>(1)
const dirty = ref(false)
const draft = ref('')

const volumes = computed(() => studio.data.outline)
const current = computed(() => (chosen.value === 'book' ? null : volumes.value.find((v) => v.index === chosen.value) ?? null))
const writtenChapters = computed(() => studio.sortedChapters.filter((c) => c.approved))

const bookLayerText = computed(() => {
  const b = studio.book
  const vols = volumes.value
  return [
    `## 全书层`,
    ``,
    `- 一句话故事核：${b.spine}`,
    `- 主题：${b.theme}`,
    `- 终点：${b.targetChapters} 章，最后一章必须回答「发令权到底归谁」`,
    `- 分支：${vols.map((v) => `卷${v.index}「${v.title}」${rangeLabel(v.range[0], v.range[1])}`).join('；')}`,
    ``,
    ...vols.map((v) => [
      `### 第${v.index}卷 ${v.title}（${rangeLabel(v.range[0], v.range[1])}）`,
      `- 任务：${v.task}`,
      `- 卷内节拍：${v.beats.join(' → ')}`,
      `- 卷末钩子：${v.hook}`,
      ``,
    ].join('\n')),
  ].join('\n')
})

const volumeText = computed(() => {
  const v = current.value
  if (!v) return ''
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

watch([chosen, () => studio.key], () => {
  draft.value = chosen.value === 'book' ? bookLayerText.value : volumeText.value
  dirty.value = false
}, { immediate: true })

watch(draft, () => (dirty.value = true))

function save() {
  dirty.value = false
  studio.toast(chosen.value === 'book' ? '全书大纲已保存' : `第 ${chosen.value} 卷大纲已保存`, 'ok')
}

function reanchor() {
  draft.value = chosen.value === 'book' ? bookLayerText.value : volumeText.value
  dirty.value = false
  studio.toast('已按梗概与真实章节重新对齐（未保存）', 'info')
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="结构"
      title="大纲"
      desc="全书层只回答「这条路通不通」；卷层回答「这一段往哪儿去」。逐章排细纲已下线，正文按 10 章一段的段落纲走。"
    >
      <Button variant="ghost" @click="reanchor">按梗概重新对齐</Button>
      <Button variant="pink" :disabled="!dirty" @click="save">{{ dirty ? '保存大纲 ·' : '已保存' }}</Button>
    </PageHeader>

    <div class="stats">
      <StatTile label="卷" :value="volumes.length" unit="卷" note="全书层拆成四条主线" />
      <StatTile label="目标" :value="studio.book.targetChapters" unit="章" :note="`每卷约 ${Math.round(studio.book.targetChapters / volumes.length)} 章`" />
      <StatTile label="已落笔" :value="writtenChapters.length" unit="章" :note="'正文已进索引的章'" />
      <StatTile label="段落纲" :value="studio.segList.length" unit="段" note="10 章一段" tone="gold" />
    </div>

    <div class="grid">
      <Card flush class="nav">
        <div class="nav__head">
          <span class="ns-eyebrow">结构导航</span>
          <Tag size="sm" tone="ink">可编辑</Tag>
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
        <div class="nav__hint">卷目从项目梗概推出来；改卷范围要回「进度」页对齐真实章节。</div>
      </Card>

      <Card flush class="editor">
        <div class="editor__bar">
          <div class="editor__title">
            <span class="ns-eyebrow">第 {{ chosen === 'book' ? 0 : chosen }} 层</span>
            <b>{{ chosen === 'book' ? '全书层大纲' : current?.title }}</b>
            <span v-if="current" class="editor__range">{{ rangeLabel(current.range[0], current.range[1]) }}</span>
          </div>
          <div class="editor__tools">
            <Tag v-if="dirty" size="sm" tone="warn" dot>未保存</Tag>
            <Tag v-else size="sm" tone="ok">已同步</Tag>
            <span class="editor__words ns-num">{{ draft.length }} 字符</span>
          </div>
        </div>
        <textarea v-model="draft" class="editor__area" spellcheck="false" aria-label="大纲正文" />
        <div class="editor__foot">
          <span>保存后，Agent 写正文时会看到最新版本。</span>
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
  </div>
</template>

<style scoped>
.page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
.grid {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  margin-bottom: 16px;
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
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.beat {
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
}
.beat__hook {
  font-size: 11px;
  color: var(--ns-pink-2);
  line-height: 1.55;
  border-top: 1px dashed var(--ns-line);
  padding-top: 6px;
  margin-top: 2px;
}
@media (max-width: 1040px) {
  .stats,
  .beats__row {
    grid-template-columns: repeat(2, 1fr);
  }
  .grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 620px) {
  .page {
    padding: 20px 16px 64px;
  }
}
</style>

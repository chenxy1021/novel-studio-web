<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Card, Tag, EmptyState } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import StatTile from '@/components/StatTile.vue'
import RuleChip from '@/components/RuleChip.vue'
import { useStudio } from '@/stores/studio'
import { pct, rangeLabel, wan } from '@/lib/format'
import { segmentStages } from '@/mocks'

const studio = useStudio()
const router = useRouter()

const data = computed(() => studio.data)
const progress = computed(() => pct(studio.approved.length, studio.book.targetChapters))
const avgChars = computed(() => {
  const list = studio.approved
  return list.length ? Math.round(list.reduce((s, c) => s + c.chars, 0) / list.length) : 0
})
const thisSeg = computed(() => studio.recentSegment)
const segProgress = computed(() => {
  const s = thisSeg.value
  if (!s) return 0
  const done = studio.approved.filter((c) => c.number >= s.from && c.number <= s.to).length
  return pct(done, s.to - s.from + 1)
})
const overdue = computed(() => studio.foreshadows.filter((f) => f.status === 'open' && f.overdue))
const shortChapters = computed(() => studio.approved.filter((c) => c.chars < studio.book.minChars))
const lastChapter = computed(() => studio.approved[studio.approved.length - 1])

function startBatch() {
  if (studio.pending.length) {
    studio.toast(`第 ${studio.pending[0].number} 章还没确认，先去「进度」页处理`, 'warn')
    router.push({ name: 'progress' })
    return
  }
  studio.toast(`已把「写第 ${studio.nextNumber}–${studio.nextNumber + 9} 章」的任务交给了 Agent 会话`, 'ok')
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="这本书现在长什么样"
      :title="studio.book.title"
      :desc="studio.book.logline"
    >
      <Button variant="ghost" size="sm" icon="↗" @click="router.push({ name: 'detail' })">本段段落纲</Button>
      <Button variant="pink" icon="✎" @click="startBatch">
        {{ studio.pending.length ? `先确认第 ${studio.pending[0].number} 章` : `写第 ${studio.nextNumber}–${studio.nextNumber + 9} 章` }}
      </Button>
    </PageHeader>

    <div class="stats">
      <StatTile label="已完成" :value="studio.approved.length" :unit="`/ ${studio.book.targetChapters} 章`" :note="`${progress}% · 目标 ${wan(studio.book.targetChapters * studio.book.wordsPerChapter)} 字`" tone="pink" />
      <StatTile label="正文总量" :value="(studio.totalChars / 10000).toFixed(1)" unit="万字" :note="`平均 ${avgChars} 字 / 章`" />
      <StatTile label="本批进度" :value="thisSeg ? segProgress : 0" unit="%" :note="thisSeg ? rangeLabel(thisSeg.from, thisSeg.to) : '尚未规划段落纲'" />
      <StatTile label="未收伏笔" :value="studio.foreshadows.filter((f) => f.status === 'open').length" unit="条" :note="overdue.length ? `${overdue.length} 条已到期` : '暂无到期'" :tone="overdue.length ? 'gold' : 'plain'" />
    </div>

    <div class="cols">
      <div class="ns-stack">
        <Card eyebrow="地基" title="故事梗概">
          <div class="cover">
            <div class="cover__spine">
              <span class="ns-eyebrow">题材</span>
              <b>{{ studio.book.genre }}</b>
              <span class="ns-eyebrow">基调</span>
              <b>{{ studio.book.tone }}</b>
              <span class="ns-eyebrow">平台</span>
              <b>{{ studio.book.platform }}</b>
            </div>
            <div class="cover__body">
              <p class="synopsis ns-serif">{{ studio.book.synopsis }}</p>
              <blockquote class="theme">
                <span class="ns-eyebrow">一句话主题</span>
                <em>{{ studio.book.theme }}</em>
              </blockquote>
            </div>
          </div>
          <template #footer>
            <Button size="sm" variant="ghost" @click="router.push({ name: 'outline' })">去大纲页改结构 →</Button>
          </template>
        </Card>

        <Card
          :eyebrow="thisSeg ? rangeLabel(thisSeg.from, thisSeg.to) : '段落纲'"
          title="这一段的脊柱"
          desc="10 章一段只铺一份段落纲（3–5 个台阶）。写正文时，Agent 按本章所在台阶的目标、转折、伏笔、现场走。"
        >
          <div v-if="thisSeg" class="spine">
            <p class="spine__text ns-serif">{{ thisSeg.spine }}</p>
            <div class="spine__bar">
              <i :style="{ width: `${segProgress}%` }" />
            </div>
            <ol class="stages">
              <li v-for="(s, i) in segmentStages(thisSeg)" :key="i">
                <span class="stages__no">{{ i + 1 }}</span>
                <div class="stages__body">
                  <div class="stages__head">
                    <b>第 {{ s.chapters[0] }}–{{ s.chapters[s.chapters.length - 1] }} 章 · 台阶 {{ i + 1 }}</b>
                    <Tag size="sm" :tone="s.pace === '紧' ? 'pink' : 'neutral'">节奏 {{ s.pace }}</Tag>
                  </div>
                  <p>{{ s.goal }}</p>
                </div>
              </li>
            </ol>
          </div>
          <EmptyState
            v-else
            icon="☰"
            title="还没有段落纲"
            desc="点右上「写第 N 章」，Agent 会先用段落纲规划这一批（3–5 个台阶），你确认方向后落账。"
          />
          <template #footer>
            <Button size="sm" variant="ghost" @click="router.push({ name: 'detail' })">看完整段落纲 →</Button>
          </template>
        </Card>
      </div>

      <div class="ns-stack">
        <Card eyebrow="Gate" title="创作关卡" flush>
          <div class="gate">
            <div class="gate__step" :class="{ on: studio.book.gates.brief }"><RuleChip :ok="studio.book.gates.brief" label="梗概" /></div>
            <span class="gate__line" />
            <div class="gate__step" :class="{ on: studio.book.gates.outline }"><RuleChip :ok="studio.book.gates.outline" label="大纲" /></div>
            <span class="gate__line" />
            <div class="gate__step" :class="{ on: studio.book.gates.bible }"><RuleChip :ok="studio.book.gates.bible" label="设定" /></div>
            <span class="gate__line" />
            <div class="gate__step" :class="{ on: studio.book.gate.phase === 'writing' }"><RuleChip :ok="true" label="写作" /></div>
          </div>
          <div class="gate__now">
            <span class="gate__tag">当前</span>
            <div>
              <b>第 {{ studio.book.gate.chapter }} 章 · {{ studio.book.gate.phase === 'writing' ? '待写' : '待确认' }}</b>
              <p>{{ studio.book.gate.reason }}</p>
            </div>
          </div>
        </Card>

        <Card eyebrow="最近" title="上一章" :desc="lastChapter ? `第 ${lastChapter.number} 章 · ${lastChapter.title}` : '还没有正文'">
          <template v-if="lastChapter">
            <p class="last__summary">{{ lastChapter.summary }}</p>
            <div class="last__meta">
              <Tag size="sm" tone="ok">{{ lastChapter.chars }} 字</Tag>
              <Tag v-for="c in lastChapter.characters.slice(0, 3)" :key="c" size="sm">{{ c }}</Tag>
            </div>
          </template>
          <template #footer>
            <Button size="sm" variant="ghost" @click="router.push({ name: 'progress' })">去进度页 →</Button>
          </template>
        </Card>

        <Card eyebrow="需要你注意" title="三个待办">
          <ul class="todo">
            <li class="todo__item" @click="router.push({ name: 'foreshadow' })">
              <Tag :tone="overdue.length ? 'warn' : 'neutral'" size="sm">{{ overdue.length ? '到期' : '—' }}</Tag>
              <span v-if="overdue.length">{{ overdue[0].name }} · 第 {{ overdue[0].dueChapter }} 章该收了</span>
              <span v-else>伏笔都在期限内</span>
            </li>
            <li class="todo__item" @click="router.push({ name: 'progress' })">
              <Tag :tone="studio.pending.length ? 'pink' : 'neutral'" size="sm">{{ studio.pending.length ? '待确认' : '—' }}</Tag>
              <span v-if="studio.pending.length">第 {{ studio.pending.map((c) => c.number).join('、') }} 章等你存档</span>
              <span v-else>没有待确认章</span>
            </li>
            <li class="todo__item" @click="router.push({ name: 'progress' })">
              <Tag :tone="shortChapters.length ? 'bad' : 'neutral'" size="sm">{{ shortChapters.length ? '字数' : '—' }}</Tag>
              <span v-if="shortChapters.length">{{ shortChapters.length }} 章低于 {{ studio.book.minChars }} 字硬下限</span>
              <span v-else>全部达到 {{ studio.book.minChars }} 字下限</span>
            </li>
          </ul>
        </Card>

        <Card eyebrow="下一步" title="写作顺序">
          <ol class="next">
            <li><b>① 确认待确认章</b><span>进度页 → 存档，或者退回重写</span></li>
            <li><b>② 写下一批</b><span>第 {{ studio.nextNumber }}–{{ studio.nextNumber + 9 }} 章，按本段台阶走</span></li>
            <li><b>③ 按批体检</b><span>每章问题铺在那一章下面，跨章问题单列</span></li>
          </ol>
        </Card>
      </div>
    </div>
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
  margin-bottom: 20px;
}
.cols {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(300px, 1fr);
  gap: 16px;
  align-items: start;
}
.cover {
  display: grid;
  grid-template-columns: 148px minmax(0, 1fr);
  gap: 20px;
}
.cover__spine {
  display: grid;
  align-content: start;
  gap: 3px;
  padding: 14px 14px 16px;
  border-left: 3px solid var(--ns-pink);
  background: var(--ns-card-2);
  border-radius: 0 var(--ns-r-sm) var(--ns-r-sm) 0;
}
.cover__spine b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-13);
  line-height: 1.5;
  margin-bottom: 8px;
  font-weight: 600;
}
.synopsis {
  margin: 0;
  font-size: 14.5px;
  line-height: 1.95;
  text-indent: 0;
}
.theme {
  margin: 16px 0 0;
  padding: 10px 0 0;
  border-top: 1px dashed var(--ns-line-2);
}
.theme em {
  display: block;
  margin-top: 3px;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  color: var(--ns-ink-2);
  font-style: normal;
}
.spine__text {
  margin: 0 0 12px;
  font-size: var(--ns-fs-14);
  line-height: 1.85;
  color: var(--ns-ink-2);
}
.spine__bar {
  height: 4px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-card-2);
  overflow: hidden;
  margin-bottom: 16px;
}
.spine__bar i {
  display: block;
  height: 100%;
  background: var(--ns-pink);
}
.stages {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 12px;
}
.stages li {
  display: flex;
  gap: 12px;
}
.stages__no {
  width: 22px;
  height: 22px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--ns-card-2);
  border: 1px solid var(--ns-line);
  font-family: var(--ns-serif);
  font-size: 11px;
  font-weight: 700;
  color: var(--ns-ink-2);
}
.stages__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.stages__head b {
  font-size: 12.5px;
}
.stages__body p {
  margin: 3px 0 0;
  color: var(--ns-ink-2);
  font-size: 12.5px;
  line-height: 1.65;
}
.gate {
  display: flex;
  align-items: center;
  padding: 16px 20px 6px;
}
.gate__step {
  flex: none;
}
.gate__line {
  flex: 1;
  height: 1px;
  background: var(--ns-line);
  margin: 0 8px;
}
.gate__now {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin: 6px 16px 16px;
  padding: 11px 12px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-pink-soft);
  border: 1px solid var(--ns-pink-line);
}
.gate__tag {
  flex: none;
  font-size: 10.5px;
  font-weight: 700;
  background: var(--ns-pink);
  color: #fff;
  border-radius: var(--ns-r-xs);
  padding: 1px 6px;
  margin-top: 1px;
}
.gate__now b {
  font-size: 12.5px;
}
.gate__now p {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--ns-ink-3);
}
.last__summary {
  margin: 0 0 10px;
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--ns-ink-2);
}
.last__meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.todo {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
}
.todo__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 0;
  border-top: 1px dashed var(--ns-line);
  cursor: pointer;
  font-size: 12.5px;
  color: var(--ns-ink-2);
}
.todo__item:first-child {
  border-top: 0;
  padding-top: 0;
}
.todo__item:hover {
  color: var(--ns-ink);
}
.next {
  margin: 0;
  padding: 0 0 0 18px;
  display: grid;
  gap: 10px;
  font-size: 12.5px;
  color: var(--ns-ink-2);
}
.next li::marker {
  color: var(--ns-pink);
  font-weight: 700;
}
.next b {
  color: var(--ns-ink);
}
.next span {
  display: block;
  color: var(--ns-ink-3);
  font-size: 11.5px;
}
@media (max-width: 1040px) {
  .stats {
    grid-template-columns: repeat(2, 1fr);
  }
  .cols {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 620px) {
  .page {
    padding: 20px 16px 64px;
  }
  .cover {
    grid-template-columns: 1fr;
  }
}
</style>

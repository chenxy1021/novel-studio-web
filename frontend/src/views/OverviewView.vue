<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Card, Tag } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import StatTile from '@/components/StatTile.vue'
import RuleChip from '@/components/RuleChip.vue'
import ChapterChart from '@/components/ChapterChart.vue'
import { useStudio } from '@/stores/studio'
import { pct, rangeLabel, wan } from '@/lib/format'
import { segmentStages } from '@/lib/segment'

const studio = useStudio()
const router = useRouter()

const progress = computed(() => pct(studio.approved.length, studio.book.targetChapters))
const avgChars = computed(() => {
  const list = studio.approved
  return list.length ? Math.round(list.reduce((s, c) => s + c.chars, 0) / list.length) : 0
})
const seg = computed(() => studio.recentSegment)
const segRows = computed(() =>
  seg.value ? studio.sortedChapters.filter((c) => c.number >= seg.value!.from && c.number <= seg.value!.to) : [],
)
const segDone = computed(() => segRows.value.filter((c) => c.approved).length)
const segProgress = computed(() => (seg.value ? pct(segDone.value, seg.value.to - seg.value.from + 1) : 0))
const ribbon = computed(() =>
  seg.value
    ? Array.from({ length: seg.value.to - seg.value.from + 1 }, (_, i) => {
        const n = seg.value!.from + i
        const ch = studio.findChapter(n)
        const state = ch?.approved ? 'done' : ch && ch.chars > 0 ? 'review' : 'todo'
        return { n, state }
      })
    : [],
)
const overdue = computed(() => studio.foreshadows.filter((f) => f.status === 'open' && f.overdue))
const openThreads = computed(() => studio.foreshadows.filter((f) => f.status === 'open'))
const shortChapters = computed(() => studio.approved.filter((c) => c.chars < studio.book.minChars))
const lastChapter = computed(() => studio.approved[studio.approved.length - 1])
const pending = computed(() => studio.pending)
const recent = computed(() => studio.sortedChapters.slice(-12))
const today = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date())

type Action = { label: string; kind: 'pink' | 'secondary' | 'ghost'; run: () => void }
type Task = { id: string; tone: 'pink' | 'warn' | 'gold' | 'ok'; title: string; detail: string; actions: Action[] }

function goProgress(n?: number) {
  router.push(n ? { name: 'progress', query: { chapter: String(n) } } : { name: 'progress' })
}

const batchSize = computed(() => Math.max(3, studio.book.segmentSize || 10))
const writeFrom = computed(() => (studio.chapters.length ? studio.nextNumber : 1))
/**
 * 今日页与「细纲 / 写作」用同一批章：已经排过段落纲时，直接写到这一段末尾；
 * 段落纲还没覆盖到下一章（比如上一段已写完）才按每段章数往后推。
 */
const writeTo = computed(() => {
  const seg = studio.currentSegment
  if (seg && seg.to >= writeFrom.value) return seg.to
  return Math.min(studio.book.targetChapters || writeFrom.value + batchSize.value - 1, writeFrom.value + batchSize.value - 1)
})
const noForeshadow = computed(() => studio.foreshadows.length === 0)

/** 所有「写正文」入口统一进开写面板；只在没骨架时才回开书流程。 */
function openWrite(from?: number, to?: number) {
  const preset: { source: 'today'; from?: number; to?: number } = { source: 'today' }
  if (from) preset.from = from
  if (to) preset.to = to
  studio.openWritePanel(preset)
}

/** 「现在做什么」只留三条，按「卡住的东西优先」排序。全清空时给一条正向任务。 */
const tasks = computed<Task[]>(() => {
  const list: Task[] = []
  if (!studio.book.outlineText) {
    list.push({
      id: 'blueprint',
      tone: 'pink',
      title: '先立大纲和世界观',
      detail: '选题的故事梗概已经就位：用它生成全书大纲 + 卷层 + 世界观（虐文会带反转公式）',
      actions: [{ label: '去开书流程', kind: 'pink', run: () => router.push({ name: 'workflow' }) }],
    })
  } else if (!studio.chapters.length) {
    list.push({
      id: 'write-first',
      tone: 'pink',
      title: noForeshadow.value ? '骨架已立，先设计伏笔' : '骨架已立，轮到写第一批',
      detail: noForeshadow.value
        ? `正文要按伏笔网推进；伏笔设计好后，再写第 ${writeFrom.value}–${writeTo.value} 章`
        : `按「设定 → 伏笔 → 写第 ${writeFrom.value}–${writeTo.value} 章」的顺序推进，写完逐章确认`,
      actions: [
        noForeshadow.value
          ? { label: '去设计伏笔', kind: 'pink', run: () => router.push({ name: 'foreshadow' }) }
          : { label: `开写第 ${writeFrom.value}–${writeTo.value} 章`, kind: 'pink', run: () => openWrite(writeFrom.value, writeTo.value) },
      ],
    })
  }
  if (pending.value.length) {
    const issues = pending.value.reduce((s, c) => s + (studio.checks[c.number]?.findings.filter((f) => f.severity === 'high').length ?? c.fixReasons.length), 0)
    list.push({
      id: 'pending',
      tone: 'pink',
      title: `第 ${pending.value.map((c) => c.number).join('、')} 章等你确认`,
      detail: issues ? `${issues} 条硬伤要先看：字数、章尾钩子、连续性` : '体检已过，读过一遍就可以存档',
      actions: [
        { label: `处理第 ${pending.value[0].number} 章`, kind: 'pink', run: () => goProgress(pending.value[0].number) },
        {
          label: pending.value.length > 1 ? `存档全部 ${pending.value.length} 章` : '直接存档',
          kind: 'secondary',
          run: () => studio.autoArchivePending(),
        },
      ],
    })
  }
  if (overdue.value.length) {
    list.push({
      id: 'foreshadow',
      tone: 'warn',
      title: `${overdue.value.length} 条伏笔已经到期`,
      detail: overdue.value.map((f) => `${f.name}（第 ${f.dueChapter} 章该收）`).join('、'),
      actions: [{ label: '去收线', kind: 'secondary', run: () => router.push({ name: 'foreshadow' }) }],
    })
  }
  if (shortChapters.value.length) {
    list.push({
      id: 'short',
      tone: 'gold',
      title: `${shortChapters.value.length} 章低于 ${studio.book.minChars} 字下限`,
      detail: `第 ${shortChapters.value.map((c) => c.number).join('、')} 章 · 平台过审会卡字数`,
      actions: [{ label: '看这几章', kind: 'secondary', run: () => goProgress(shortChapters.value[0].number) }],
    })
  }
  if (!list.length) {
    list.push({
      id: 'clear',
      tone: 'ok',
      title: '手头没有卡住的事',
      detail: `下一批是第 ${writeFrom.value}–${writeTo.value} 章，先把台阶想清楚再写正文`,
      actions: [{ label: '规划下一段', kind: 'pink', run: () => router.push({ name: 'detail' }) }],
    })
  }
  return list.slice(0, 3)
})

const primary = computed<Action>(() => {
  if (!studio.book.outlineText) {
    return { label: '生成大纲和世界观', kind: 'pink', run: () => router.push({ name: 'workflow' }) }
  }
  if (pending.value.length) {
    return { label: `确认第 ${pending.value[0].number} 章`, kind: 'pink', run: () => goProgress(pending.value[0].number) }
  }
  if (noForeshadow.value) {
    return { label: '先设计伏笔', kind: 'pink', run: () => router.push({ name: 'foreshadow' }) }
  }
  return {
    label: `开写第 ${writeFrom.value}–${writeTo.value} 章`,
    kind: 'pink',
    run: () => openWrite(writeFrom.value, writeTo.value),
  }
})

function runBatch() {
  goProgress()
  studio.runBatchCheck()
}
</script>

<template>
  <div class="ns-page today">
    <PageHeader eyebrow="今日" :title="studio.book.title" :desc="studio.book.logline">
      <Button variant="ghost" icon="✍" @click="router.push({ name: 'workflow' })">开书流程</Button>
      <Button variant="ghost" icon="☰" @click="router.push({ name: 'detail' })">段落纲</Button>
    </PageHeader>

    <!-- 一屏之内：现在是什么状态、今天推哪一步 -->
    <section class="hero">
      <div class="hero__main">
        <div class="hero__meta">
          <span class="hero__date">{{ today }}</span>
          <span class="hero__dot" aria-hidden="true" />
          <span>{{ studio.book.genre.split(' · ')[0] }} · {{ studio.book.platform }}</span>
        </div>
        <h2 class="hero__headline">{{ primary.label }}</h2>
        <p class="hero__sub">{{ tasks[0].detail }}</p>
        <div class="hero__actions">
          <Button :variant="primary.kind" icon="→" @click="primary.run">{{ primary.label }}</Button>
          <Button variant="secondary" icon="⚗" :disabled="studio.batchBusy" @click="runBatch">
            {{ studio.batchBusy ? '体检中…' : '按批体检' }}
          </Button>
          <span class="hero__streak">连续写作 <b>{{ studio.streak }}</b> 天 · 今日 <b>{{ (studio.wordsToday / 1000).toFixed(1) }}k</b> 字</span>
        </div>
      </div>
      <div class="hero__meter">
        <div class="meter__top">
          <span class="ns-eyebrow">全书进度</span>
          <span class="meter__num ns-num">{{ studio.approved.length }}<small>/{{ studio.book.targetChapters }} 章</small></span>
        </div>
        <div class="meter__track"><i :style="{ width: `${progress}%` }" /></div>
        <div class="meter__foot">
          <span>{{ progress }}%</span>
          <span>{{ wan(studio.totalChars) }} 字 · 均 {{ avgChars }}/章</span>
        </div>
        <div class="meter__segment">
          <span class="ns-eyebrow">本段 {{ seg ? rangeLabel(seg.from, seg.to) : '未规划' }}</span>
          <span class="ns-num">{{ segDone }}/{{ segRows.length || 10 }}</span>
        </div>
        <div v-if="ribbon.length" class="ribbon" aria-label="本段章节状态">
          <button
            v-for="r in ribbon"
            :key="r.n"
            type="button"
            class="ribbon__cell"
            :class="`ribbon__cell--${r.state}`"
            :title="`第 ${r.n} 章`"
            @click="goProgress(r.n)"
          >
            <span>{{ r.n }}</span>
          </button>
        </div>
      </div>
    </section>

    <!-- 按优先级排的行动队列 -->
    <section class="queue" aria-label="现在做什么">
      <header class="queue__head">
        <h3>现在做什么</h3>
        <span class="queue__hint">从上往下处理，处理完自动消失</span>
      </header>
      <ol class="queue__list">
        <li v-for="(t, i) in tasks" :key="t.id" class="task" :class="`task--${t.tone}`">
          <span class="task__idx ns-mono">{{ i + 1 }}</span>
          <div class="task__body">
            <b>{{ t.title }}</b>
            <span>{{ t.detail }}</span>
          </div>
          <div class="task__acts">
            <Button
              v-for="a in t.actions"
              :key="a.label"
              size="sm"
              :variant="a.kind === 'pink' ? 'pink' : a.kind === 'secondary' ? 'secondary' : 'ghost'"
              @click="a.run"
            >
              {{ a.label }}
            </Button>
          </div>
        </li>
      </ol>
    </section>

    <div class="stats">
      <StatTile label="已完成" :value="studio.approved.length" :unit="`/ ${studio.book.targetChapters} 章`" :note="`${progress}% · 目标 ${wan(studio.book.targetChapters * studio.book.wordsPerChapter)} 字`" tone="pink" />
      <StatTile label="正文总量" :value="(studio.totalChars / 10000).toFixed(1)" unit="万字" :note="`平均 ${avgChars} 字 / 章`" />
      <StatTile label="本段进度" :value="segProgress" unit="%" :note="seg ? rangeLabel(seg.from, seg.to) : '尚未规划段落纲'" />
      <StatTile label="未收伏笔" :value="openThreads.length" unit="条" :note="overdue.length ? `${overdue.length} 条已到期` : '暂无到期'" :tone="overdue.length ? 'gold' : 'plain'" />
    </div>

    <div class="cols">
      <div class="ns-stack">
        <Card eyebrow="本批" :title="seg ? `这一段的字数分布 · ${rangeLabel(seg.from, seg.to)}` : '还没有可看的章节'" desc="虚线是每章字数硬下限。斜纹柱表示低于下限；点柱子看单章，点下方数字跳转。">
          <template v-if="recent.length">
            <ChapterChart :chapters="recent" :min="studio.book.minChars" :limit="12" />
            <div v-if="seg" class="segstrip">
              <span class="ns-eyebrow">本段台阶</span>
              <div class="segstrip__stages">
                <span v-for="(st, i) in segmentStages(seg)" :key="i" class="segstrip__stage">
                  <i class="segstrip__no">{{ i + 1 }}</i>
                  第 {{ st.chapters[0] }}–{{ st.chapters[st.chapters.length - 1] }} 章
                  <Tag size="sm" :tone="st.pace === '紧' ? 'pink' : 'neutral'">{{ st.pace }}</Tag>
                </span>
              </div>
            </div>
          </template>
          <p v-else class="muted">还没有正文。先从段落纲规划第一批，再开始写。</p>
          <template #footer>
            <Button size="sm" variant="ghost" @click="goProgress()">逐章看 →</Button>
            <Button size="sm" variant="ghost" @click="router.push({ name: 'detail' })">段落纲 →</Button>
          </template>
        </Card>

        <Card
          :eyebrow="seg ? rangeLabel(seg.from, seg.to) : '段落纲'"
          title="这一段的脊柱"
          :desc="`${batchSize} 章一段只铺一份段落纲（3–5 个台阶）。写正文时，按本章所在台阶的目标、转折、伏笔、现场走。`"
        >
          <div v-if="seg" class="spine">
            <p class="spine__text ns-serif">{{ seg.spine }}</p>
            <div class="spine__bar"><i :style="{ width: `${segProgress}%` }" /></div>
            <ol class="stages">
              <li v-for="(s, i) in segmentStages(seg)" :key="i">
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
          <p v-else class="muted">还没有段落纲。点「规划下一段」，后端会先给 3–5 个台阶的预览，你确认方向后才落账。</p>
          <template #footer>
            <Button size="sm" variant="ghost" @click="router.push({ name: 'detail' })">看完整段落纲 →</Button>
          </template>
        </Card>

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
            <Button size="sm" variant="ghost" @click="router.push({ name: 'outline', query: { tab: 'world' } })">世界观 →</Button>
          </template>
        </Card>
      </div>

      <aside class="ns-stack">
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
              <b>第 {{ studio.nextNumber }} 章 · {{ studio.book.gate.phase === 'writing' ? '待写' : '待确认' }}</b>
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
          <p v-else class="muted">写完之后，这里会显示上一章摘要和出场人物，方便接着写。</p>
          <template #footer>
            <Button size="sm" variant="ghost" @click="goProgress(lastChapter?.number)">去这一章 →</Button>
          </template>
        </Card>

        <Card eyebrow="下一步" title="写作顺序">
          <ol class="next">
            <li><b>① 确认待确认章</b><span>进度页 → 存档，或者退回重写</span></li>
            <li><b>② 写下一批</b><span>第 {{ writeFrom }}–{{ writeTo }} 章，按本段台阶走</span></li>
            <li><b>③ 按批体检</b><span>每章问题铺在那一章下面，跨章问题单列</span></li>
          </ol>
        </Card>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.today {
  padding-top: 24px;
}
.muted {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
  line-height: 1.7;
}

/* ---- hero ---- */
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr);
  gap: 20px;
  padding: 20px 22px;
  margin-bottom: 16px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-lg);
  background:
    radial-gradient(120% 160% at 100% 0%, var(--ns-pink-soft) 0%, transparent 52%),
    var(--ns-card);
  box-shadow: var(--ns-shadow-1);
}
.hero__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: var(--ns-ink-3);
}
.hero__date {
  font-weight: 600;
  color: var(--ns-ink-2);
}
.hero__dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--ns-ink-4);
}
.hero__headline {
  margin: 6px 0 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-28);
  line-height: 1.25;
  letter-spacing: 0.01em;
}
.hero__sub {
  margin: 6px 0 0;
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-13);
  max-width: 56ch;
}
.hero__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  flex-wrap: wrap;
}
.hero__streak {
  font-size: 11px;
  color: var(--ns-ink-3);
  margin-left: 4px;
}
.hero__streak b {
  color: var(--ns-ink);
  font-family: var(--ns-serif);
}
.hero__meter {
  align-self: center;
  padding: 14px 16px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: color-mix(in srgb, var(--ns-card) 82%, transparent);
}
.meter__top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}
.meter__num {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-22);
  font-weight: 700;
  line-height: 1;
}
.meter__num small {
  font-family: var(--ns-sans);
  font-size: 11px;
  color: var(--ns-ink-3);
  font-weight: 500;
  margin-left: 2px;
}
.meter__track {
  height: 6px;
  margin: 9px 0 6px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-chart-track);
  overflow: hidden;
}
.meter__track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--ns-pink) 0%, var(--ns-pink-2) 100%);
  transition: width 0.3s ease;
}
.meter__foot {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 10.5px;
  color: var(--ns-ink-3);
}
.meter__segment {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--ns-line);
  font-size: 11.5px;
}
.ribbon {
  display: flex;
  gap: 3px;
  margin-top: 8px;
}
.ribbon__cell {
  flex: 1;
  height: 22px;
  min-width: 0;
  display: grid;
  place-items: center;
  border: 1px solid var(--ns-line);
  border-radius: 3px;
  background: var(--ns-card-2);
  color: var(--ns-ink-4);
  font-family: var(--ns-mono);
  font-size: 9.5px;
  cursor: pointer;
  padding: 0;
}
.ribbon__cell:hover {
  border-color: var(--ns-line-2);
  color: var(--ns-ink);
}
.ribbon__cell--done {
  background: color-mix(in srgb, var(--ns-ok) 20%, var(--ns-card));
  border-color: color-mix(in srgb, var(--ns-ok) 42%, transparent);
  color: var(--ns-ok);
}
.ribbon__cell--review {
  background: var(--ns-pink-soft);
  border-color: var(--ns-pink-line);
  color: var(--ns-pink-2);
}

/* ---- queue ---- */
.queue {
  margin-bottom: 18px;
}
.queue__head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 0 2px 8px;
}
.queue__head h3 {
  margin: 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
}
.queue__hint {
  font-size: 11px;
  color: var(--ns-ink-4);
}
.queue__list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.task {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 16px;
  border: 1px solid var(--ns-line);
  border-left-width: 3px;
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  box-shadow: var(--ns-shadow-1);
}
.task--pink {
  border-left-color: var(--ns-pink);
}
.task--warn {
  border-left-color: var(--ns-warn);
}
.task--gold {
  border-left-color: var(--ns-gold);
}
.task--ok {
  border-left-color: var(--ns-ok);
}
.task__idx {
  width: 22px;
  height: 22px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--ns-card-2);
  color: var(--ns-ink-3);
  font-size: 11px;
  font-weight: 700;
}
.task__body {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 2px;
}
.task__body b {
  font-size: var(--ns-fs-13);
  line-height: 1.4;
}
.task__body span {
  font-size: 11.5px;
  color: var(--ns-ink-3);
  line-height: 1.5;
}
.task__acts {
  display: flex;
  gap: 6px;
  flex: none;
  flex-wrap: wrap;
  justify-content: flex-end;
}

/* ---- stats & columns ---- */
.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.cols {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(300px, 1fr);
  gap: 16px;
  align-items: start;
}

/* ---- cards ---- */
.chart-note {
  display: flex;
  justify-content: space-between;
  gap: 8px;
}
.segstrip {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--ns-line);
}
.segstrip__stages {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 6px;
}
.segstrip__stage {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px 3px 4px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-pill);
  font-size: 10.5px;
  color: var(--ns-ink-2);
  background: var(--ns-card-2);
}
.segstrip__no {
  width: 15px;
  height: 15px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--ns-ink);
  color: var(--ns-card);
  font-size: 9px;
  font-style: normal;
  font-weight: 700;
}
.spine__text {
  margin: 0 0 10px;
  font-size: var(--ns-fs-14);
  line-height: 1.85;
  color: var(--ns-ink-2);
}
.spine__bar {
  height: 4px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-chart-track);
  overflow: hidden;
  margin-bottom: 14px;
}
.spine__bar i {
  display: block;
  height: 100%;
  background: var(--ns-pink);
}
.stages {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.stages li {
  display: flex;
  gap: 10px;
}
.stages__no {
  width: 20px;
  height: 20px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid var(--ns-line-2);
  color: var(--ns-ink-3);
  font-size: 10px;
  font-weight: 700;
}
.stages__body {
  min-width: 0;
}
.stages__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.stages__head b {
  font-size: var(--ns-fs-12);
}
.stages__body p {
  margin: 3px 0 0;
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-2);
  line-height: 1.65;
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
  font-size: var(--ns-fs-12);
  margin-bottom: 6px;
}
.synopsis {
  margin: 0;
  font-size: var(--ns-fs-14);
  line-height: 1.9;
  color: var(--ns-ink-2);
}
.theme {
  margin: 12px 0 0;
  padding: 10px 12px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-pink-soft);
}
.theme em {
  display: block;
  margin-top: 2px;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-13);
  font-style: normal;
  color: var(--ns-pink-2);
  line-height: 1.7;
}

/* ---- gate / last / next ---- */
.gate {
  display: flex;
  align-items: center;
  padding: 16px 18px 4px;
}
.gate__step {
  flex: none;
  opacity: 0.55;
}
.gate__step.on {
  opacity: 1;
}
.gate__line {
  flex: 1;
  height: 1px;
  background: var(--ns-line);
  margin: 0 6px;
}
.gate__now {
  display: flex;
  gap: 10px;
  margin: 12px 18px 18px;
  padding: 10px 12px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.gate__tag {
  flex: none;
  align-self: flex-start;
  padding: 1px 6px;
  border-radius: var(--ns-r-xs);
  background: var(--ns-pink);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
}
.gate__now b {
  font-size: var(--ns-fs-12);
}
.gate__now p {
  margin: 2px 0 0;
  font-size: 11px;
  color: var(--ns-ink-3);
  line-height: 1.6;
}
.last__summary {
  margin: 0;
  font-size: var(--ns-fs-13);
  line-height: 1.75;
  color: var(--ns-ink-2);
}
.last__meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.next {
  display: grid;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: step;
}
.next li {
  display: grid;
  gap: 1px;
  padding-left: 12px;
  border-left: 2px solid var(--ns-line);
}
.next b {
  font-size: var(--ns-fs-12);
}
.next span {
  font-size: 11px;
  color: var(--ns-ink-3);
}

@media (max-width: 1080px) {
  .hero {
    grid-template-columns: 1fr;
  }
  .stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .cols {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 620px) {
  .task {
    align-items: flex-start;
    flex-wrap: wrap;
  }
  .task__acts {
    width: 100%;
    justify-content: flex-start;
    padding-left: 36px;
  }
  .cover {
    grid-template-columns: 1fr;
  }
  .hero__headline {
    font-size: var(--ns-fs-22);
  }
}
</style>

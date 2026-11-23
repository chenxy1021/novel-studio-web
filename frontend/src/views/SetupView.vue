<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, Card, Tag, Table, type Column } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import { useStudio } from '@/stores/studio'
import type { Rule, TimelineRow } from '@/mocks'

const studio = useStudio()
const tab = ref<'rules' | 'factions' | 'timeline' | 'threads'>('rules')
const opened = ref<Set<string>>(new Set())

const rules = computed(() => studio.data.rules)
const factions = computed(() => studio.data.factions)
const timeline = computed(() => studio.data.timeline)

type ThreadRow = { id: string; name: string; due: number | string; known: string; change: string }
const threadRows = computed<ThreadRow[]>(() =>
  studio.foreshadows
    .filter((f) => f.status === 'open')
    .map((f) => ({
      id: f.id,
      name: f.name,
      due: f.dueChapter ?? '—',
      known: f.revealWho || '季恒',
      change: f.revealChange || f.hint || '揭开会改变读者对这段广播的判断',
    })),
)
const threadCols: Column<ThreadRow>[] = [
  { key: 'name', label: '悬而未决的事', width: '32%' },
  { key: 'due', label: '计划交代章', numeric: true, width: '110px' },
  { key: 'known', label: '谁先知道', width: '120px' },
  { key: 'change', label: '交代后改变什么' },
]

function toggle(id: string) {
  const next = new Set(opened.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  opened.value = next
}

function saveRule(r: Rule) {
  studio.toast(`硬规则「${r.text.slice(0, 12)}…」已保存`, 'ok')
}

const counts = computed(() => ({
  rules: rules.value.length,
  factions: factions.value.length,
  timeline: timeline.value.length,
  threads: threadRows.value.length,
}))
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="硬约束"
      title="设定"
      desc="设定只写「不能违背的东西」。硬规则写清代价和漏洞；势力写清明规则与潜规则；悬而未决的事写清第几章交代。"
    >
      <Button variant="ghost">从正文补齐</Button>
      <Button variant="pink" icon="＋">新建</Button>
    </PageHeader>

    <div class="tabs" role="tablist">
      <button
        v-for="t in [
          { k: 'rules', t: '硬规则', n: counts.rules },
          { k: 'factions', t: '势力与恩怨', n: counts.factions },
          { k: 'timeline', t: '时间线', n: counts.timeline },
          { k: 'threads', t: '悬而未决的事', n: counts.threads },
        ]"
        :key="t.k"
        role="tab"
        type="button"
        :aria-selected="tab === t.k"
        :class="{ on: tab === t.k }"
        @click="tab = t.k as typeof tab"
      >
        {{ t.t }} <span class="ns-num">{{ t.n }}</span>
      </button>
    </div>

    <div v-if="tab === 'rules'" class="rules">
      <Card v-for="r in rules" :key="r.id" flush class="rule">
        <div class="rule__head" @click="toggle(r.id)">
          <Tag size="sm" tone="ink">硬规则</Tag>
          <b>{{ r.text }}</b>
          <span class="rule__state">{{ r.tested.includes('未') ? '未实测' : '已实测' }}</span>
          <span class="rule__caret">{{ opened.has(r.id) ? '⌃' : '⌄' }}</span>
        </div>
        <div class="rule__grid">
          <div>
            <span class="ns-eyebrow">代价</span>
            <p>{{ r.cost }}</p>
          </div>
          <div>
            <span class="ns-eyebrow">漏洞</span>
            <p>{{ r.loophole }}</p>
          </div>
          <div>
            <span class="ns-eyebrow">实测</span>
            <p>{{ r.tested }}</p>
          </div>
          <div v-if="r.forbidden.length">
            <span class="ns-eyebrow">禁止出现</span>
            <p class="rule__ban">
              <Tag v-for="b in r.forbidden" :key="b" size="sm" tone="bad">{{ b }}</Tag>
            </p>
          </div>
        </div>
        <Transition name="rule">
          <div v-if="opened.has(r.id)" class="rule__more">
            <div class="rule__editor">
              <span class="ns-eyebrow">想让这条规则怎么裂</span>
              <p class="ns-serif">{{ r.loophole }}——第 {{ r.id === 'r1' ? 7 : 12 }} 章起，有人开始利用这一点；季恒要决定是堵上还是留着。</p>
            </div>
            <Button size="sm" @click="saveRule(r)">保存改动</Button>
          </div>
        </Transition>
      </Card>
    </div>

    <div v-else-if="tab === 'factions'" class="factions">
      <Card v-for="f in factions" :key="f.name" :title="f.name" :desc="f.nature">
        <div class="faction">
          <div>
            <span class="ns-eyebrow">明规则</span>
            <p>{{ f.openRule }}</p>
          </div>
          <div class="faction__hidden">
            <span class="ns-eyebrow">潜规则</span>
            <p>{{ f.hiddenRule }}</p>
          </div>
          <div>
            <span class="ns-eyebrow">欠下的账</span>
            <p>{{ f.debt }}</p>
          </div>
        </div>
      </Card>
    </div>

    <Card v-else-if="tab === 'timeline'" flush>
      <Table
        :columns="[
          { key: 'chapter', label: '章', numeric: true, width: '64px' },
          { key: 'inWorldDay', label: '故事内第几天', numeric: true, width: '120px' },
          { key: 'summary', label: '这一章发生了什么' },
        ] as Column<TimelineRow>[]"
        :rows="timeline as unknown as TimelineRow[]"
        dense
        striped
      />
    </Card>

    <Card v-else flush>
      <Table :columns="threadCols" :rows="threadRows" dense striped row-key="id" />
    </Card>
  </div>
</template>

<style scoped>
.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 32px 72px;
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
.rules {
  display: grid;
  gap: 10px;
}
.rule__head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 18px;
  cursor: pointer;
}
.rule__head b {
  flex: 1;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  line-height: 1.5;
  font-weight: 600;
}
.rule__state {
  font-size: 11px;
  color: var(--ns-ink-3);
  white-space: nowrap;
}
.rule__caret {
  color: var(--ns-ink-4);
  font-size: 12px;
}
.rule__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  border-top: 1px dashed var(--ns-line);
}
.rule__grid > div {
  padding: 12px 18px;
  border-bottom: 1px dashed var(--ns-line);
}
.rule__grid > div:nth-child(2n) {
  border-left: 1px dashed var(--ns-line);
}
.rule__grid p {
  margin: 3px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.rule__ban {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.rule__more {
  display: flex;
  gap: 14px;
  align-items: flex-end;
  justify-content: space-between;
  padding: 12px 18px;
  background: var(--ns-card-2);
}
.rule__editor p {
  margin: 3px 0 0;
  font-size: 13px;
  line-height: 1.8;
  color: var(--ns-ink-2);
  max-width: 70ch;
}
.factions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.faction {
  display: grid;
  gap: 12px;
}
.faction > div {
  padding: 9px 11px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.faction__hidden {
  background: var(--ns-warn-soft) !important;
}
.faction p {
  margin: 3px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.rule-enter-active,
.rule-leave-active {
  transition: opacity 0.15s ease;
}
.rule-enter-from,
.rule-leave-to {
  opacity: 0;
}
@media (max-width: 900px) {
  .factions,
  .rule__grid {
    grid-template-columns: 1fr;
  }
  .rule__grid > div:nth-child(2n) {
    border-left: 0;
  }
}
@media (max-width: 620px) {
  .page {
    padding: 20px 16px 64px;
  }
}
</style>

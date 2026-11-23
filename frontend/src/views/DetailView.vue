<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, Card, Tag, EmptyState, Modal, Input } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import { useStudio } from '@/stores/studio'
import { segmentStages } from '@/mocks'
import type { SegmentStage } from '@/mocks'
import { rangeLabel } from '@/lib/format'

const studio = useStudio()
const openSegs = ref<number[]>([])
const segs = computed(() => [...studio.segList].sort((a, b) => a.from - b.from))
const openSeg = ref<number | null>(studio.recentSegment?.from ?? null)
const showPlan = ref(false)
const planFrom = ref('')
const planTo = ref('')
const chosenStage = ref<number | null>(null)

function chaptersIn(stage: SegmentStage) {
  return studio.approved.filter((c) => stage.chapters.includes(c.number)).length
}

function stateOf(s: { status: string }) {
  if (s.status === 'done') return { label: '已写完', tone: 'ok' as const }
  if (s.status === 'writing') return { label: '正在写', tone: 'pink' as const }
  return { label: '只规划未落笔', tone: 'neutral' as const }
}

function planNext() {
  planFrom.value = String(studio.nextNumber)
  planTo.value = String(studio.nextNumber + 9)
  showPlan.value = true
}

function confirmPlan() {
  showPlan.value = false
  studio.toast(`已把第 ${planFrom.value}–${planTo.value} 章交给 Agent 规划（3–5 个台阶，先预览再落账）`, 'info')
}

function deleteSeg(s: { from: number; to: number }) {
  studio.segList = studio.segList.filter((x) => !(x.from === s.from && x.to === s.to))
  studio.toast(`已删掉第 ${s.from}–${s.to} 章段落纲（已写正文不受影响）`, 'warn')
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="批量写作"
      title="细纲 · 段落纲"
      desc="按 10 章一段规划：一段一份段落纲，3–5 个台阶。写正文时 Agent 按本章所在台阶走——台阶目标、转折、本台阶埋/收的伏笔、预计现场。不再逐章排细纲。"
    >
      <Button icon="＋" @click="planNext">规划第 {{ studio.nextNumber }}–{{ studio.nextNumber + 9 }} 章</Button>
    </PageHeader>

    <div class="legend">
      <span class="legend__item"><i class="legend__dot legend__dot--goal" />目标</span>
      <span class="legend__item"><i class="legend__dot legend__dot--turn" />转折</span>
      <span class="legend__item"><i class="legend__dot legend__dot--plant" />埋</span>
      <span class="legend__item"><i class="legend__dot legend__dot--pay" />收</span>
      <span class="legend__item"><i class="legend__dot legend__dot--scene" />现场</span>
      <span class="legend__spacer" />
      <span class="legend__meta">共 {{ segs.length }} 段 · 覆盖 {{ segs.length ? `${segs[0].from}–${segs[segs.length - 1].to}` : '—' }} 章</span>
    </div>

    <div v-if="segs.length" class="segs">
      <Card v-for="s in segs" :key="`${s.from}-${s.to}`" flush class="seg">
        <div class="seg__head" @click="(openSeg = openSeg === s.from ? null : s.from)">
          <div class="seg__range">
            <span class="ns-mono">{{ String(s.from).padStart(3, '0') }}</span>
            <span class="seg__seed">—</span>
            <span class="ns-mono">{{ String(s.to).padStart(3, '0') }}</span>
          </div>
          <div class="seg__title">
            <div class="seg__name">
              <b>{{ rangeLabel(s.from, s.to) }}</b>
              <Tag size="sm" :tone="stateOf(s).tone" dot>{{ stateOf(s).label }}</Tag>
              <Tag size="sm">{{ s.stages }} 个台阶</Tag>
            </div>
            <p>{{ s.spine }}</p>
          </div>
          <div class="seg__meta">
            <span>{{ studio.approved.filter((c) => c.number >= s.from && c.number <= s.to).length }}/{{ s.to - s.from + 1 }} 章</span>
            <span class="seg__caret">{{ openSeg === s.from ? '⌃' : '⌄' }}</span>
          </div>
        </div>

        <Transition name="seg">
          <div v-if="openSeg === s.from" class="seg__body">
            <div class="rail" role="list">
              <div
                v-for="(st, i) in segmentStages(s)"
                :key="i"
                class="stage"
                :class="{ 'stage--focus': chosenStage === i, 'stage--done': chaptersIn(st) === st.chapters.length }"
                role="listitem"
                @mouseenter="chosenStage = i"
                @mouseleave="chosenStage = null"
              >
                <div class="stage__marker">
                  <span class="stage__no">{{ i + 1 }}</span>
                  <i v-if="i < segmentStages(s).length - 1" class="stage__stem" />
                </div>
                <div class="stage__content">
                  <div class="stage__top">
                    <b>台阶 {{ i + 1 }}</b>
                    <span class="stage__chs">第 {{ st.chapters.join('、') }} 章</span>
                    <Tag size="sm" :tone="st.pace === '紧' ? 'pink' : st.pace === '缓' ? 'info' : 'neutral'">节奏 {{ st.pace }}</Tag>
                    <span class="stage__done">{{ chaptersIn(st) }}/{{ st.chapters.length }} 已写</span>
                  </div>
                  <dl class="kv">
                    <div class="kv__row">
                      <dt>目标</dt>
                      <dd>{{ st.goal }}</dd>
                    </div>
                    <div class="kv__row">
                      <dt>转折</dt>
                      <dd>{{ st.turn }}</dd>
                    </div>
                    <div v-if="st.foreshadow.plant.length" class="kv__row">
                      <dt>本台阶埋</dt>
                      <dd><Tag v-for="f in st.foreshadow.plant" :key="f" size="sm" tone="warn">{{ f }}</Tag></dd>
                    </div>
                    <div v-if="st.foreshadow.payoff.length" class="kv__row">
                      <dt>本台阶收</dt>
                      <dd><Tag v-for="f in st.foreshadow.payoff" :key="f" size="sm" tone="ok">{{ f }}</Tag></dd>
                    </div>
                    <div class="kv__row">
                      <dt>现场</dt>
                      <dd class="kv__places">
                        <span v-for="p in st.places" :key="p">{{ p }}</span>
                        <span class="kv__cast">出场：{{ st.cast.join('、') }}</span>
                      </dd>
                    </div>
                  </dl>
                </div>
              </div>
            </div>
            <div class="seg__foot">
              <span>这一段的台阶决定「写哪几章、每章往哪儿走」；每章的字数和问题在「进度」页逐章看。</span>
              <div class="seg__acts">
                <Button size="sm" variant="ghost" @click="$router.push({ name: 'progress' })">去写这一段 →</Button>
                <Button size="sm" variant="ghost" class="seg__danger" @click="deleteSeg(s)">删除本段</Button>
              </div>
            </div>
          </div>
        </Transition>
      </Card>
    </div>
    <EmptyState
      v-else
      icon="☰"
      title="还没有段落纲"
      desc="回「概览」点「写第 N 章」，Agent 会先用 novel_segment op=plan 规划这一段（3–5 个台阶），你确认方向后落账。"
    >
      <Button size="sm" @click="planNext">规划下一段</Button>
    </EmptyState>

    <Modal :open="showPlan" title="规划下一段段落纲" desc="10 章一段。Agent 只给预览：3–5 个台阶，每个台阶给目标 / 转折 / 伏笔 / 现场。你确认后才落账。" width="560px" @close="showPlan = false">
      <div class="planform">
        <Input v-model="planFrom" label="从第几章开始" type="number" />
        <Input v-model="planTo" label="写到第几章" type="number" hint="建议连续 10 章；短篇最后一章可以不足" />
      </div>
      <ul class="planrules">
        <li>一段只回答一个问题，台阶按「紧 → 缓 → 紧」排。</li>
        <li>本段该埋的伏笔在台阶里点名，后期收的时候不用回头找。</li>
        <li>预计现场写具体地名，Agent 写正文时不会临时编一个新街区。</li>
      </ul>
      <template #footer>
        <Button variant="ghost" @click="showPlan = false">取消</Button>
        <Button variant="primary" @click="confirmPlan">交给 Agent 规划</Button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.legend {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  font-size: 11px;
  color: var(--ns-ink-3);
  margin-bottom: 12px;
}
.legend__item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.legend__dot {
  width: 7px;
  height: 7px;
  border-radius: 2px;
}
.legend__dot--goal {
  background: var(--ns-ink);
}
.legend__dot--turn {
  background: var(--ns-info);
}
.legend__dot--plant {
  background: var(--ns-warn);
}
.legend__dot--pay {
  background: var(--ns-ok);
}
.legend__dot--scene {
  background: var(--ns-gold);
}
.legend__spacer {
  flex: 1;
}
.legend__meta {
  font-variant-numeric: tabular-nums;
}
.segs {
  display: grid;
  gap: 12px;
}
.seg__head {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 14px 18px;
  cursor: pointer;
}
.seg__range {
  flex: none;
  display: flex;
  align-items: center;
  gap: 5px;
  font-family: var(--ns-mono);
  font-size: var(--ns-fs-16);
  font-weight: 600;
  color: var(--ns-ink-3);
  padding-top: 1px;
}
.seg__seed {
  color: var(--ns-pink);
}
.seg__title {
  flex: 1;
  min-width: 0;
}
.seg__name {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.seg__name b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
}
.seg__title p {
  margin: 5px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
  max-width: 72ch;
}
.seg__meta {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11.5px;
  color: var(--ns-ink-3);
  font-variant-numeric: tabular-nums;
  padding-top: 3px;
}
.seg__caret {
  font-size: 12px;
  color: var(--ns-ink-4);
}
.seg__body {
  border-top: 1px solid var(--ns-line);
  padding: 18px 20px 12px;
  background: color-mix(in srgb, var(--ns-paper) 45%, var(--ns-card));
}
.rail {
  display: grid;
}
.stage {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: 14px;
  transition: background 0.14s ease;
  border-radius: var(--ns-r-sm);
}
.stage--focus {
  background: var(--ns-card-2);
}
.stage__marker {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
  padding-top: 2px;
}
.stage__no {
  width: 24px;
  height: 24px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--ns-card);
  border: 1px solid var(--ns-line-2);
  font-family: var(--ns-serif);
  font-size: 11.5px;
  font-weight: 700;
  color: var(--ns-ink-2);
}
.stage--focus .stage__no {
  background: var(--ns-ink);
  border-color: var(--ns-ink);
  color: var(--ns-card);
}
.stage__stem {
  flex: 1;
  width: 1px;
  min-height: 22px;
  background: var(--ns-line-2);
  margin: 4px 0 0;
}
.stage__content {
  padding: 0 0 18px;
  min-width: 0;
}
.stage__top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 3px 0 6px;
}
.stage__top b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
}
.stage__chs {
  font-size: 11.5px;
  color: var(--ns-ink-3);
}
.stage__done {
  margin-left: auto;
  font-size: 10.5px;
  color: var(--ns-ink-3);
  font-variant-numeric: tabular-nums;
}
.kv {
  margin: 0;
  display: grid;
  gap: 5px;
}
.kv__row {
  display: grid;
  grid-template-columns: 68px minmax(0, 1fr);
  gap: 10px;
  align-items: baseline;
}
.kv dt {
  font-size: 11px;
  font-weight: 600;
  color: var(--ns-ink-3);
  letter-spacing: 0.03em;
}
.kv dd {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.kv__places {
  gap: 6px;
}
.kv__places > span:not(.kv__cast) {
  padding: 0 7px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-xs);
  background: var(--ns-card);
  font-size: 11.5px;
}
.kv__cast {
  color: var(--ns-ink-3);
  font-size: 11.5px;
  margin-left: 4px;
}
.seg__foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
  padding-top: 10px;
  border-top: 1px dashed var(--ns-line);
  font-size: 11px;
  color: var(--ns-ink-3);
}
.seg__acts {
  display: flex;
  gap: 6px;
}
.seg__danger {
  color: var(--ns-bad);
}
.planform {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.planrules {
  margin: 14px 0 0;
  padding-left: 18px;
  font-size: 12px;
  color: var(--ns-ink-2);
  line-height: 1.8;
}
.planrules li::marker {
  color: var(--ns-pink);
}
.seg-enter-active,
.seg-leave-active {
  transition: opacity 0.15s ease;
}
.seg-enter-from,
.seg-leave-to {
  opacity: 0;
}
@media (max-width: 700px) {
  .page {
    padding: 20px 16px 64px;
  }
  .seg__meta,
  .seg__range {
    display: none;
  }
}
</style>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Card, Tag, EmptyState, Modal, Input } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import ReferencePanel from '@/components/ReferencePanel.vue'
import ChapterCheckPanel from '@/components/ChapterCheckPanel.vue'
import SkillRewriteModal from '@/components/SkillRewriteModal.vue'
import { fetchReferences, previewReferences, type FocusRef, type ReferencePack } from '@/api/references'
import type { Finding } from '@/api/client'
import { useStudio } from '@/stores/studio'
import { segmentStages } from '@/lib/segment'
import type { ChapterOutline, Segment, SegmentStage } from '@/mocks'
import { rangeLabel } from '@/lib/format'

const studio = useStudio()
const router = useRouter()
const openSegs = ref<number[]>([])
const segs = computed(() => [...studio.segList].sort((a, b) => a.from - b.from))
const openSeg = ref<number | null>(studio.recentSegment?.from ?? null)

// ---------------------------------------------------------------- 批次细纲
/** 段落纲可能没有（还没规划），但批次细纲通常已经生成；一份批次细纲按章落成多条 ledger 行，这里按批归组展示。 */
type OutlineGroup = { key: string; label: string; spine: string; rows: ChapterOutline[] }
const outlineRows = computed(() => studio.outlineRows)
const outlineGroups = computed<OutlineGroup[]>(() => {
  const groups: OutlineGroup[] = []
  const byKey = new Map<string, OutlineGroup>()
  for (const row of outlineRows.value) {
    const batched = row.batchFrom > 0 && row.batchTo >= row.batchFrom
    const key = batched ? `b-${row.batchFrom}-${row.batchTo}` : `c-${row.chapter}`
    let group = byKey.get(key)
    if (!group) {
      group = {
        key,
        label: batched
          ? `第 ${row.batchFrom}–${row.batchTo} 章 · 一批细纲`
          : `单章细纲 · 第 ${row.chapter} 章`,
        spine: row.batchSpine,
        rows: [],
      }
      byKey.set(key, group)
      groups.push(group)
    }
    group.rows.push(row)
  }
  return groups.sort((a, b) => a.rows[0].chapter - b.rows[0].chapter)
})
/** 这一组是不是一次批量生成出来的细纲。 */
function isBatch(group: OutlineGroup): boolean {
  return group.key.startsWith('b-')
}

const outlineCover = computed(() => {
  const rows = outlineRows.value
  if (!rows.length) return '—'
  const first = rows[0].chapter
  const last = rows[rows.length - 1].chapter
  return first === last ? String(first) : `${first}–${last}`
})

const openOutline = ref<number | null>(null)

function toggleOutline(n: number) {
  openOutline.value = openOutline.value === n ? null : n
}

function chapterChars(n: number): number {
  return studio.findChapter(n)?.chars ?? 0
}

onMounted(() => {
  void studio.refreshOutlines()
})
const showPlan = ref(false)
const planFrom = ref('')
const planTo = ref('')
const planPreview = ref<Segment | null>(null)
const planBusy = ref(false)
const chosenStage = ref<number | null>(null)
const showNuewen = ref(false)
const nuewenNote = ref('')

function openNuewen() {
  showNuewen.value = true
}

async function runNuewen() {
  try {
    await studio.generateNuewen(nuewenNote.value)
  } catch {
    /* store 已经 toast，弹窗保持打开让作者重试 */
  }
}

async function toggleNuewenMode() {
  try {
    await studio.setNuewenMode(!studio.nuewenEnabled)
  } catch (e) {
    studio.toast(`切换失败：${e instanceof Error ? e.message : String(e)}`, 'warn')
  }
}

async function copyNuewen() {
  try {
    await navigator.clipboard.writeText(studio.nuewen.text)
    studio.toast('虐文骨架已复制', 'ok')
  } catch {
    studio.toast('复制失败：浏览器不允许写剪贴板', 'warn')
  }
}

function nuewenTime(): string {
  if (!studio.nuewen.at) return ''
  const d = new Date(studio.nuewen.at)
  if (Number.isNaN(d.getTime())) return studio.nuewen.at
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 下一段从哪开始：当前段落纲还没写完时先写这一段，规划新段要接在它后面。 */
const planStart = computed(() => {
  const seg = studio.currentSegment
  return seg && seg.to >= studio.nextNumber ? seg.to + 1 : studio.nextNumber
})
const batchEnd = computed(() => planStart.value + Math.max(1, studio.book.segmentSize || 10) - 1)

function chaptersIn(stage: SegmentStage) {
  return studio.approved.filter((c) => stage.chapters.includes(c.number)).length
}

function stateOf(s: { status: string }) {
  if (s.status === 'done') return { label: '已写完', tone: 'ok' as const }
  if (s.status === 'writing') return { label: '正在写', tone: 'pink' as const }
  return { label: '只规划未落笔', tone: 'neutral' as const }
}

function planNext() {
  planFrom.value = String(planStart.value)
  planTo.value = String(batchEnd.value)
  planPreview.value = null
  showPlan.value = true
}

async function previewPlan() {
  planBusy.value = true
  try {
    planPreview.value = await studio.planSegment(Number(planFrom.value), Number(planTo.value))
  } catch (e) {
    studio.toast(`规划失败：${e instanceof Error ? e.message : e}`, 'warn')
  } finally {
    planBusy.value = false
  }
}

async function commitPlan() {
  planBusy.value = true
  try {
    await studio.saveSegmentPlan(Number(planFrom.value), Number(planTo.value))
    showPlan.value = false
    planPreview.value = null
  } catch (e) {
    studio.toast(`落账失败：${e instanceof Error ? e.message : e}`, 'warn')
  } finally {
    planBusy.value = false
  }
}

async function deleteSeg(s: { from: number; to: number }) {
  await studio.deleteSegment(s.from, s.to)
}

/** 写本段：统一走开写面板，由面板负责文风确认与逐章状态。 */
function openSegmentWrite() {
  const seg = studio.currentSegment
  studio.openWritePanel({
    source: 'detail',
    // 与今日页 / 开书面板同源：段内已经写过的章不再重复带进本批。
    from: seg ? Math.max(seg.from, studio.nextNumber) : studio.nextNumber,
    to: seg?.to ?? batchEnd.value,
  })
}

// ---------------------------------------------------------------- 本章资料
const refOpen = ref(false)
const refChapter = ref(1)
const refPack = ref<ReferencePack | null>(null)
const refLoading = ref(false)
const refError = ref('')
const refFocus = ref<FocusRef[]>([])

const refExisting = computed(() => (studio.findChapter(refChapter.value)?.chars ?? 0) > 0)

function defaultRefChapter(): number {
  const seg = studio.currentSegment
  if (!seg) return studio.nextNumber
  for (let n = seg.from; n <= seg.to; n++) {
    if ((studio.findChapter(n)?.chars ?? 0) === 0) return n
  }
  return seg.from
}

const focusOptions = computed<FocusRef[]>(() => [
  ...studio.rules
    .filter((r) => r.text)
    .map((r) => ({ type: 'rule', key: r.text, label: `规则·${r.text.slice(0, 18)}` })),
  ...studio.world.map((w) => ({ type: 'place', key: w.name, label: `地点·${w.name}` })),
  ...studio.characters.map((c) => ({ type: 'character', key: c.name, label: `人物·${c.name}` })),
  ...studio.factions.map((f) => ({ type: 'faction', key: f.name, label: `势力·${f.name}` })),
  ...studio.foreshadows.map((f) => ({ type: 'foreshadow', key: f.name, label: `伏笔·${f.name}` })),
  ...(studio.memory?.chapters ?? []).map((c) => ({
    type: 'memory',
    key: String(c.chapter),
    label: `第 ${c.chapter} 章记忆`,
  })),
])

async function loadRef() {
  if (!studio.key) return
  refLoading.value = true
  refError.value = ''
  try {
    refPack.value = await fetchReferences(studio.key, refChapter.value, 'prose')
  } catch (e) {
    refError.value = e instanceof Error ? e.message : String(e)
  } finally {
    refLoading.value = false
  }
}

function openRefAt(n?: number) {
  refChapter.value = n ?? defaultRefChapter()
  refFocus.value = []
  refPack.value = null
  refOpen.value = true
  void loadRef()
}

async function setRefFocus(next: FocusRef[]) {
  refFocus.value = next
  if (!studio.key) return
  refLoading.value = true
  try {
    refPack.value = await previewReferences(studio.key, refChapter.value, next, 'prose')
  } catch (e) {
    refError.value = e instanceof Error ? e.message : String(e)
  } finally {
    refLoading.value = false
  }
}

function refWrite() {
  const n = refChapter.value
  refOpen.value = false
  studio.openWritePanel({
    source: 'detail',
    numbers: [n],
    focus: refFocus.value.map((f) => ({ type: f.type, key: f.key, label: f.label || f.key })),
  })
}

// ---------------------------------------------------------------- 体检
const checkOpen = ref(false)
const checkChapter = ref(1)
const rewriteOpen = ref(false)
const rewriteBusy = ref(false)
const rewriteError = ref('')

function openCheck(n: number) {
  checkChapter.value = n
  checkOpen.value = true
  if (!studio.checkResults[n]) void studio.check(n)
  if (studio.texts[n] == null) void studio.loadText(n)
}

/** 复检点名的段落就地重写；改完原句消失就自动从面板摘掉。 */
function rewritePara(n: number, finding: Finding) {
  if (!finding.paragraph) return
  void studio.rewriteParagraph(n, finding.paragraph, finding).catch(() => {})
}

function startRewrite(n: number) {
  checkChapter.value = n
  rewriteError.value = ''
  rewriteOpen.value = true
  if (!studio.checkResults[n]) void studio.check(n)
}

async function submitRewrite(payload: { skills: string[]; instruction: string; findings: Finding[] }) {
  rewriteBusy.value = true
  rewriteError.value = ''
  try {
    await studio.rewrite(checkChapter.value, '', payload.skills, payload.instruction, payload.findings)
    rewriteOpen.value = false
  } catch (e) {
    rewriteError.value = e instanceof Error ? e.message : String(e)
  } finally {
    rewriteBusy.value = false
  }
}

function goFromRef(route: string) {
  refOpen.value = false
  void router.push(route)
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="批量写作"
      title="细纲 · 段落纲"
      :desc="`按 ${studio.book.segmentSize} 章一段规划：一段一份段落纲，3–5 个台阶。点「写本段」会先给这一段出一份细纲，再照细纲逐章写正文；段落纲决定这一段往哪儿去。`"
    >
      <Button icon="▤" @click="openRefAt()">本章资料</Button>
      <Button
        variant="pink"
        icon="✒"
        :disabled="!studio.currentSegment"
        @click="openSegmentWrite"
      >
        写本段（细纲+正文）
      </Button>
      <Button variant="ghost" icon="✎" @click="openNuewen">
        {{ studio.nuewenEnabled || studio.nuewen.text ? '虐文骨架' : '开启虐文模式' }}
      </Button>
      <Button icon="＋" @click="planNext">规划第 {{ planStart }}–{{ batchEnd }} 章</Button>
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

    <Card v-if="studio.nuewen.text" class="nuewen" flush>
      <div class="nuewen__head" @click="openNuewen">
        <div>
          <span class="ns-eyebrow">虐文骨架 · {{ nuewenTime() }}</span>
          <b>人物反转表与分章骨架</b>
          <Tag v-if="studio.nuewenEnabled" size="sm" tone="pink">改写已套用</Tag>
        </div>
        <span class="nuewen__more">查看 / 重新生成 →</span>
      </div>
    </Card>

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
                    <span class="stage__chs">
                      第
                      <button
                        v-for="n in st.chapters"
                        :key="n"
                        type="button"
                        class="stage__chbtn"
                        :title="`查看第 ${n} 章资料`"
                        @click="openRefAt(n)"
                      >{{ n }}</button>
                      章
                    </span>
                    <Button
                      v-if="st.chapters.length"
                      size="sm"
                      variant="ghost"
                      @click="openCheck(st.chapters[0])"
                    >体检</Button>
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
    <section v-if="outlineGroups.length" class="outl">
      <div class="legend">
        <span class="legend__item"><i class="legend__dot legend__dot--goal" />批次细纲</span>
        <span class="legend__spacer" />
        <span class="legend__meta">{{ outlineGroups.length }} 批 · 覆盖第 {{ outlineCover }} 章 · 点开看这一批的分章落点</span>
      </div>
      <Card v-for="g in outlineGroups" :key="g.key" flush class="outl__group">
        <div class="outl__head">
          <div class="outl__headtext">
            <span class="ns-eyebrow">{{ g.label }}</span>
            <p v-if="g.spine" class="outl__spine">{{ g.spine }}</p>
            <p v-if="isBatch(g)" class="outl__sub">
              下面 {{ g.rows.length }} 章是这批细纲的分章落点，正文只照自己那一章写，不另起细纲。
            </p>
          </div>
          <Tag size="sm">{{ isBatch(g) ? '一批细纲' : '单章细纲' }}</Tag>
        </div>
        <div class="outl__rows">
          <div
            v-for="row in g.rows"
            :key="row.chapter"
            class="outl__row"
            :class="{ 'outl__row--open': openOutline === row.chapter }"
          >
            <button type="button" class="outl__sum" @click="toggleOutline(row.chapter)">
              <span class="ns-mono outl__no">{{ String(row.chapter).padStart(3, '0') }}</span>
              <b>{{ row.title || `第 ${row.chapter} 章` }}</b>
              <span class="outl__meta">
                {{ isBatch(g) ? '分章落点' : '节拍' }} {{ row.beats.length }} 个<template v-if="chapterChars(row.chapter)"> · {{ chapterChars(row.chapter) }} 字</template>
              </span>
              <span class="outl__caret">{{ openOutline === row.chapter ? '⌃' : '⌄' }}</span>
            </button>
            <div v-if="openOutline === row.chapter" class="outl__body">
              <div v-if="row.openingState" class="outl__line">
                <s>开场</s><span>{{ row.openingState }}</span>
              </div>
              <div v-if="row.endingState" class="outl__line">
                <s>结束</s><span>{{ row.endingState }}</span>
              </div>
              <ol v-if="row.beats.length" class="outl__beats">
                <li v-for="(beat, i) in row.beats" :key="i">{{ beat }}</li>
              </ol>
              <div v-if="row.mustInclude.length" class="outl__line">
                <s>必须出现</s><span>{{ row.mustInclude.join('；') }}</span>
              </div>
              <div v-if="row.mustAvoid.length" class="outl__line">
                <s>必须回避</s><span>{{ row.mustAvoid.join('；') }}</span>
              </div>
              <div v-if="row.pressure.deadline || row.pressure.stake || row.pressure.opponent" class="outl__pressure">
                <Tag v-if="row.pressure.deadline" size="sm" tone="warn">期限：{{ row.pressure.deadline }}</Tag>
                <Tag v-if="row.pressure.stake" size="sm" tone="pink">代价：{{ row.pressure.stake }}</Tag>
                <Tag v-if="row.pressure.opponent" size="sm">对手：{{ row.pressure.opponent }}</Tag>
              </div>
              <div v-if="row.detail" class="outl__full">{{ row.detail }}</div>
              <div class="outl__acts">
                <Button size="sm" variant="ghost" @click="openRefAt(row.chapter)">本章资料</Button>
                <Button size="sm" variant="ghost" @click="openCheck(row.chapter)">体检</Button>
              </div>
            </div>
          </div>
        </div>
      </Card>
    </section>

    <EmptyState
      v-if="!segs.length && !outlineGroups.length"
      icon="☰"
      title="还没有段落纲，也没有批次细纲"
      desc="回「今日」点「规划下一段」，后端按人物、伏笔和大纲拼出这一段（3–5 个台阶），你确认方向后落账；开写时会先给这一批章出一份细纲，再照它逐章写正文。"
    >
      <Button size="sm" @click="planNext">规划下一段</Button>
    </EmptyState>

    <Modal :open="showPlan" title="规划下一段段落纲" :desc="`${studio.book.segmentSize} 章一段。后端按人物、伏笔和大纲确定性拼装 3–5 个台阶；先预览，确认后才写进 ledger/segments.jsonl。`" width="720px" @close="showPlan = false">
      <div class="planform">
        <Input v-model="planFrom" label="从第几章开始" type="number" :disabled="!!planPreview" />
        <Input v-model="planTo" label="写到第几章" type="number" :hint="`建议连续 ${studio.book.segmentSize} 章；短篇最后一章可以不足`" :disabled="!!planPreview" />
      </div>
      <div v-if="planPreview" class="planpreview">
        <div class="planpreview__head ns-eyebrow">
          第 {{ planPreview.from }}–{{ planPreview.to }} 章 · {{ planPreview.plan.stages.length }} 个台阶
        </div>
        <ol class="planpreview__list">
          <li v-for="(st, i) in planPreview.plan.stages" :key="i">
            <b>台阶 {{ i + 1 }} · 第 {{ st.chapters[0] }}–{{ st.chapters[st.chapters.length - 1] }} 章</b>
            <span>目标：{{ st.goal }}</span>
            <span>转折：{{ st.turn }}</span>
            <span>节奏：{{ st.pace }} · 现场：{{ st.places.join('、') || '—' }}</span>
            <span>埋：{{ st.foreshadow.plant.join('、') || '—' }} · 收：{{ st.foreshadow.payoff.join('、') || '—' }}</span>
          </li>
        </ol>
      </div>
      <ul v-else class="planrules">
        <li>一段只回答一个问题，台阶按「紧 → 缓 → 紧」排。</li>
        <li>本段该埋的伏笔在台阶里点名，后期收的时候不用回头找。</li>
        <li>预计现场写具体地名，写正文时不会临时编一个新街区。</li>
      </ul>
      <template #footer>
        <Button variant="ghost" @click="showPlan = false">取消</Button>
        <Button v-if="planPreview" variant="ghost" :disabled="planBusy" @click="planPreview = null">返回修改</Button>
        <Button v-if="!planPreview" variant="primary" :disabled="planBusy" @click="previewPlan">
          {{ planBusy ? '生成中…' : '生成预览' }}
        </Button>
        <Button v-else variant="primary" :disabled="planBusy" @click="commitPlan">
          {{ planBusy ? '落账中…' : '确认落账' }}
        </Button>
      </template>
    </Modal>

    <Modal
      :open="showNuewen"
      title="虐文骨架"
      desc="按「最 X → 最非 X」文案，生成人物反转表 + 接下来 10 章的分章骨架。只出骨架，不写正文。"
      width="860px"
      @close="showNuewen = false"
    >
      <pre v-if="studio.nuewen.text" class="nuewen__text">{{ studio.nuewen.text }}</pre>
      <div v-else class="nuewen__empty">
        <p>模型会先给每个角色立一个具体的「最」，再设计反转、代价和连锁影响，最后排出接下来 10 章。</p>
        <p class="ns-muted">生成一次可能 1–3 分钟；结果会写进 <code>ledger/nuewen.jsonl</code>。</p>
      </div>
      <div class="nuewen__mode">
        <div>
          <b>正文改写套用虐文原则</b>
          <p>开启后，每次「按问题重写」和 AI 复检都会带上「最 X → 最非 X」的约束。</p>
        </div>
        <Button
          size="sm"
          :variant="studio.nuewenEnabled ? 'secondary' : 'ghost'"
          @click="toggleNuewenMode"
        >
          {{ studio.nuewenEnabled ? '已开启 · 点此关闭' : '开启' }}
        </Button>
      </div>
      <Input
        v-model="nuewenNote"
        label="补充要求（可选）"
        placeholder="例：前三章必须见血；主角是女主；不要重生。"
      />
      <template #footer>
        <Button variant="ghost" @click="showNuewen = false">关闭</Button>
        <Button v-if="studio.nuewen.text" variant="secondary" :disabled="studio.nuewenBusy" @click="copyNuewen">
          复制
        </Button>
        <Button variant="pink" :disabled="studio.nuewenBusy" @click="runNuewen">
          {{ studio.nuewenBusy ? '生成中…' : studio.nuewen.text ? '重新生成' : '生成虐文骨架' }}
        </Button>
      </template>
    </Modal>

    <ReferencePanel
      :open="refOpen"
      :chapter="refChapter"
      :pack="refPack"
      :loading="refLoading"
      :existing="refExisting"
      :focus="refFocus"
      :focus-options="focusOptions"
      :error="refError"
      @close="refOpen = false"
      @refresh="loadRef"
      @update:focus="setRefFocus"
      @write="refWrite"
      @go="goFromRef"
    />

    <Modal :open="checkOpen" title="" width="760px" @close="checkOpen = false">
      <ChapterCheckPanel
        :chapter="checkChapter"
        :result="studio.checkResults[checkChapter] ?? null"
        :ai-result="studio.aiChecks[checkChapter] ?? null"
        :stale="!!studio.checkStale[checkChapter]"
        :loading="!!studio.checkLoading[checkChapter]"
        :ai-loading="!!studio.aiCheckLoading[checkChapter]"
        :ai-stream="studio.liveGen.active && studio.liveGen.kind === 'ai-check' ? studio.liveGen : null"
        :paragraph-busy="!!studio.paragraphBusy[checkChapter]"
        :paragraph-stream="studio.liveGen.active && studio.liveGen.kind === 'paragraph' ? studio.liveGen : null"
        :can-rewrite="(studio.findChapter(checkChapter)?.chars ?? 0) > 0"
        @refresh="studio.check(checkChapter)"
        @ai-check="studio.aiCheck(checkChapter)"
        @rewrite-paragraph="(finding) => rewritePara(checkChapter, finding)"
        @rewrite="startRewrite(checkChapter)"
        @close="checkOpen = false"
        @locate="(payload) => { checkOpen = false; router.push({ path: '/progress', query: { chapter: String(checkChapter), q: payload.text } }) }"
      />
    </Modal>

    <SkillRewriteModal
      :open="rewriteOpen"
      :chapter="checkChapter"
      :suggested="studio.checkResults[checkChapter]?.suggestedSkills ?? []"
      :findings="(studio.aiChecks[checkChapter] ?? studio.checkResults[checkChapter])?.findings ?? []"
      :ai-tells="studio.checkResults[checkChapter]?.aiTells ?? null"
      :busy="rewriteBusy"
      :error="rewriteError"
      :stream="studio.liveGen.active && studio.liveGen.kind === 'rewrite' ? studio.liveGen : null"
      @close="rewriteOpen = false"
      @submit="submitRewrite"
    />
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
.planpreview {
  margin-top: 16px;
  max-height: 46vh;
  overflow: auto;
  border-top: 1px dashed var(--ns-line);
  padding-top: 12px;
}
.planpreview__head {
  color: var(--ns-ink-3);
  margin-bottom: 8px;
}
.planpreview__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}
.planpreview__list li {
  display: grid;
  gap: 3px;
  padding: 10px 12px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  font-size: 12px;
  color: var(--ns-ink-2);
  line-height: 1.6;
}
.planpreview__list b {
  color: var(--ns-ink);
  font-family: var(--ns-serif);
  font-size: 13px;
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
/* ---- 批次细纲 ---- */
.outl {
  margin-top: 20px;
  display: grid;
  gap: 12px;
}
.outl__group {
  overflow: hidden;
}
.outl__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 18px;
  border-bottom: 1px solid var(--ns-line);
}
.outl__headtext {
  min-width: 0;
}
.outl__spine {
  margin: 5px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ns-ink-2);
  max-width: 78ch;
}
.outl__sub {
  margin: 5px 0 0;
  font-size: 11px;
  line-height: 1.6;
  color: var(--ns-ink-3);
}
.outl__rows {
  display: grid;
}
.outl__row {
  border-top: 1px solid var(--ns-line);
}
.outl__row:first-child {
  border-top: 0;
}
.outl__row--open {
  background: color-mix(in srgb, var(--ns-paper) 40%, var(--ns-card));
}
.outl__sum {
  width: 100%;
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 10px 18px;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.outl__sum:hover {
  background: var(--ns-hover);
}
.outl__no {
  flex: none;
  font-size: 12px;
  color: var(--ns-ink-3);
}
.outl__sum b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
}
.outl__meta {
  margin-left: auto;
  font-size: 11px;
  color: var(--ns-ink-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.outl__caret {
  flex: none;
  font-size: 12px;
  color: var(--ns-ink-4);
}
.outl__body {
  padding: 2px 18px 14px 46px;
  display: grid;
  gap: 7px;
}
.outl__line {
  display: grid;
  grid-template-columns: 62px minmax(0, 1fr);
  gap: 10px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.outl__line s {
  text-decoration: none;
  font-size: 11px;
  font-weight: 600;
  color: var(--ns-ink-3);
  letter-spacing: 0.03em;
  padding-top: 1px;
}
.outl__beats {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 4px;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.outl__beats li::marker {
  color: var(--ns-pink);
}
.outl__pressure {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.outl__full {
  margin-top: 2px;
  padding: 10px 12px;
  max-height: 260px;
  overflow: auto;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-hover);
  font-family: var(--ns-mono);
  font-size: 11.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  color: var(--ns-ink-2);
}
.outl__acts {
  display: flex;
  gap: 6px;
  padding-top: 2px;
}
@media (max-width: 700px) {
  .page {
    padding: 20px 16px 64px;
  }
  .seg__meta,
  .seg__range {
    display: none;
  }
  .outl__body {
    padding-left: 18px;
  }
}
.nuewen {
  margin: 0 0 16px;
}
.nuewen__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 13px 16px;
  cursor: pointer;
}
.nuewen__head b {
  display: block;
  margin-top: 2px;
  font-size: 14px;
}
.nuewen__more {
  color: var(--ns-pink-2);
  font-size: 12px;
  flex: none;
}
.nuewen__text {
  margin: 0 0 16px;
  padding: 14px 16px;
  max-height: 52vh;
  overflow: auto;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-hover);
  font-family: var(--ns-mono);
  font-size: 12px;
  line-height: 1.75;
  white-space: pre-wrap;
}
.nuewen__mode {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin: 0 0 14px;
  padding: 11px 13px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-hover);
}
.nuewen__mode b {
  display: block;
  font-size: 12.5px;
}
.nuewen__mode p {
  margin: 3px 0 0;
  color: var(--ns-ink-3);
  font-size: 11.5px;
  line-height: 1.6;
}
.nuewen__empty {
  margin-bottom: 14px;
  font-size: 13px;
  color: var(--ns-ink-2);
}
.nuewen__empty p {
  margin: 0 0 8px;
  line-height: 1.8;
}
</style>

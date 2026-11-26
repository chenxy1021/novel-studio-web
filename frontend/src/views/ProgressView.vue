<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Card, Tag, Modal, EmptyState, Input } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import RuleChip from '@/components/RuleChip.vue'
import ChapterCheckPanel from '@/components/ChapterCheckPanel.vue'
import SkillRewriteModal from '@/components/SkillRewriteModal.vue'
import { useStudio } from '@/stores/studio'
import { usePrefs } from '@/stores/prefs'
import { pct } from '@/lib/format'
import { highlightSegments } from '@/lib/highlight'
import type { Finding } from '@/api/client'
import type { SyncScan } from '@/api/extras'

const studio = useStudio()
const prefs = usePrefs()
const route = useRoute()
const router = useRouter()

const filter = ref<'all' | 'pending' | 'approved' | 'issues'>('all')
const expanded = ref<number | null>(null)
const activeRow = ref<number | null>(null)
/** 从命令面板/今日页跳进来的那章：不在本批时也要能看到 */
const focusChapter = ref<number | null>(null)
const search = reactive<Record<number, string>>({})

const showCopy = ref(false)
const copyTarget = ref(0)
const rewriteOpen = ref(false)
const rewriteChapter = ref(0)
const rewriteBusy = ref(false)
const rewriteError = ref('')
/** 批量存档/退回的选择；跨筛选保留。 */
const selected = ref<Set<number>>(new Set())
/** 从开写面板「逐章审阅」带进来的范围。 */
const rangeFrom = ref<number | null>(null)
const rangeTo = ref<number | null>(null)
const rejectConfirmOpen = ref(false)
const rejectTargets = ref<number[]>([])

/* 手改回灌：扫出应用外改过的正文，勾选后重跑索引 / 章记忆 / 人物状态。 */
const syncOpen = ref(false)
const syncScanData = ref<SyncScan | null>(null)
const syncPicked = ref<Set<number>>(new Set())
const syncMemory = ref(true)
const SYNC_LABEL: Record<string, string> = {
  edited: '应用外改过',
  untracked: '未进索引',
  baseline: '旧书补基线',
  missing: '正文缺失',
  'memory-stale': '记忆过期',
}

async function openSync() {
  syncOpen.value = true
  syncScanData.value = await studio.scanSync()
  syncPicked.value = new Set(
    (syncScanData.value?.items ?? []).filter((x) => x.kind !== 'missing').map((x) => x.number),
  )
}

function toggleSync(n: number) {
  const next = new Set(syncPicked.value)
  if (next.has(n)) next.delete(n)
  else next.add(n)
  syncPicked.value = next
}

async function applySyncPicked() {
  const res = await studio.applySync([...syncPicked.value], syncMemory.value)
  if (res) {
    syncScanData.value = studio.syncScan
    syncOpen.value = false
  }
}

function scrollToChapter(n: number) {
  nextTick(() => {
    document.querySelector<HTMLElement>(`[data-chapter="${n}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  })
}

function isTyping(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)
}

function moveRow(delta: number) {
  if (!rows.value.length) return
  const idx = rows.value.findIndex((r) => r.number === activeRow.value)
  const next = idx < 0 ? 0 : Math.min(rows.value.length - 1, Math.max(0, idx + delta))
  activeRow.value = rows.value[next].number
  scrollToChapter(activeRow.value)
}

/** 进度页键盘：J/K 走章，Space 勾选，A 存档，R 退回，Shift+R 退回并重写，B 体检。 */
function onKey(e: KeyboardEvent) {
  if (prefs.paletteOpen || prefs.helpOpen || rewriteOpen.value || showCopy.value || rejectConfirmOpen.value || fsAction.value || syncOpen.value) return
  if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return
  const active = rows.value.find((r) => r.number === activeRow.value)

  if (e.key === 'j' || e.key === 'J') {
    e.preventDefault()
    moveRow(1)
  } else if (e.key === 'k' || e.key === 'K') {
    e.preventDefault()
    moveRow(-1)
  } else if (e.key === ' ' || e.code === 'Space') {
    if (!active) return
    e.preventDefault()
    toggleSelected(active.number)
  } else if (e.key === 'a' || e.key === 'A') {
    e.preventDefault()
    void archiveCurrentOrSelected()
  } else if (e.key === 'Enter') {
    if (!active) return
    const tag = (e.target as HTMLElement | null)?.tagName
    if (tag === 'BUTTON' || tag === 'A') return
    e.preventDefault()
    if (!active.approved) studio.archive(active.number)
    else toggle(active.number)
  } else if ((e.key === 'r' || e.key === 'R') && e.shiftKey) {
    if (!active) return
    e.preventDefault()
    startRewrite(active.number)
  } else if (e.key === 'r' || e.key === 'R') {
    e.preventDefault()
    requestReject()
  } else if (e.key === 'b' || e.key === 'B') {
    e.preventDefault()
    if (!studio.batchBusy) studio.runBatchCheck()
  }
}

/** 从 URL 同步「范围 / 筛选」：挂载时和执行中的同页跳转（写作面板 → 去审阅）都走这里。 */
function syncRangeFromQuery() {
  const qFrom = Number(route.query.from)
  const qTo = Number(route.query.to)
  const hasRange = Number.isFinite(qFrom) && qFrom > 0 && Number.isFinite(qTo) && qTo >= qFrom
  rangeFrom.value = hasRange ? qFrom : null
  rangeTo.value = hasRange ? qTo : null
  if (route.query.filter === 'pending') filter.value = 'pending'
  else if (!route.query.chapter) filter.value = 'all'
}

// 已经在进度页时再点「去审阅」不会重新挂载组件，必须跟着 query 变。
watch(
  () => [route.query.from, route.query.to, route.query.filter],
  () => syncRangeFromQuery(),
)

onMounted(() => {
  const q = Number(route.query.chapter)
  const qFrom = Number(route.query.from)
  const qTo = Number(route.query.to)
  const hasRange = Number.isFinite(qFrom) && qFrom > 0 && Number.isFinite(qTo) && qTo >= qFrom
  syncRangeFromQuery()
  // 明确点进来审某一章 / 带范围来审一批时不要自动存档，否则「处理待确认章」就没得看了
  if (prefs.autoArchive && !q && !hasRange) studio.autoArchivePending()
  if (q) {
    filter.value = 'all'
    focusChapter.value = q
    expanded.value = q
    activeRow.value = q
    studio.loadText(q)
    if (typeof route.query.q === 'string' && route.query.q.trim()) {
      search[q] = route.query.q
      void studio.loadText(q).then(() => {
        nextTick(() => {
          document
            .querySelector<HTMLElement>(`[data-chapter="${q}"] .row__prose`)
            ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
        })
      })
    }
    scrollToChapter(q)
  } else {
    activeRow.value = rows.value[0]?.number ?? null
  }
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

const seg = computed(() => studio.recentSegment)
/** 从「去审阅」带进来的显式范围（不是当前段落纲）。 */
const batchRange = computed<[number, number] | null>(() =>
  rangeFrom.value != null && rangeTo.value != null ? [rangeFrom.value, rangeTo.value] : null,
)
/**
 * 本页作用范围：显式范围 > 当前段落纲 > 全书。
 * 没有段落纲的书（直接从开写面板逐章写）不能因为圈不出「本批」就一片空白。
 */
const scopeRange = computed<[number, number] | null>(() => {
  if (batchRange.value) return batchRange.value
  const s = seg.value
  return s ? [s.from, s.to] : null
})
const batchLabel = computed(() =>
  scopeRange.value ? `${scopeRange.value[0]}–${scopeRange.value[1]}` : '全书',
)
const batchCheckLabel = computed(() =>
  scopeRange.value ? `按批体检 第 ${batchLabel.value} 章` : '按批体检',
)
const scopeDesc = computed(() => {
  if (batchRange.value) return `本批 ${batchLabel.value} 章。`
  if (seg.value) return `本段 ${batchLabel.value} 章。`
  return '还没有段落纲，先按全书显示。'
})
const inBatch = computed(() => {
  const range = scopeRange.value
  const base = range
    ? studio.sortedChapters.filter((c) => c.number >= range[0] && c.number <= range[1])
    : [...studio.sortedChapters]
  // 跳转目标不在本段（比如从命令面板搜到上一批的章）时，把那章临时带进来
  if (focusChapter.value && !base.some((c) => c.number === focusChapter.value)) {
    const extra = studio.findChapter(focusChapter.value)
    if (extra) return [...base, extra].sort((a, b) => a.number - b.number)
  }
  return base
})
const rows = computed(() =>
  inBatch.value.filter((c) => {
    if (filter.value === 'pending') return !c.approved
    if (filter.value === 'approved') return c.approved
    if (filter.value === 'issues') return Boolean(studio.checks[c.number]?.findings.length)
    return true
  }),
)
const batchDone = computed(() => {
  const range = scopeRange.value
  return studio.approved.filter(
    (c) => !range || (c.number >= range[0] && c.number <= range[1]),
  ).length
})
const batchSpan = computed(() => {
  if (scopeRange.value) return scopeRange.value[1] - scopeRange.value[0] + 1
  return Math.max(inBatch.value.length, 1)
})
const batchProgress = computed(() => pct(batchDone.value, batchSpan.value))
/** 按批体检是快照；体检/AI 复检改过的章以当前结果为准，修好的自动从「要重写」里消失。 */
const todoRewrite = computed(() =>
  (studio.batch?.chapters ?? [])
    .filter((c) => !(studio.checks[c.number]?.pass ?? c.pass))
    .map((c) => c.number),
)
/** 按批体检核对正文后自动记收的伏笔：说清楚是哪几条、收在第几章。 */
const autoPaidText = computed(() => {
  const lines = studio.batch?.autoPaid ?? []
  if (!lines.length) return ''
  const detail = lines.map((it) => `${it.name}（第 ${it.chapter} 章）`).join('、')
  return `${lines.length} 条到期伏笔正文里已经写了：${detail}`
})

/* ---------- 批量选择 ---------- */

const selectedCount = computed(() => selected.value.size)

function toggleSelected(n: number) {
  const c = studio.findChapter(n)
  if (!c || c.chars <= 0) return
  const next = new Set(selected.value)
  if (next.has(n)) next.delete(n)
  else next.add(n)
  selected.value = next
}

function selectPendingInBatch() {
  const next = new Set(selected.value)
  for (const c of inBatch.value) if (!c.approved && c.chars > 0) next.add(c.number)
  selected.value = next
}

function clearSelected() {
  selected.value = new Set()
}

async function archiveSelectedNow() {
  const list = [...selected.value].sort((a, b) => a - b)
  if (!list.length) return
  try {
    const res = await studio.archiveSelected(list)
    if (!res) return
    const ok = new Set(res.results.filter((r) => r.ok).map((r) => r.number))
    selected.value = new Set([...selected.value].filter((n) => !ok.has(n)))
  } catch {
    /* store 已 toast，失败章保留选择 */
  }
}

async function archiveCurrentOrSelected() {
  if (selected.value.size) {
    await archiveSelectedNow()
    return
  }
  const active = rows.value.find((r) => r.number === activeRow.value)
  if (!active) return
  if (!active.approved) await studio.archive(active.number)
  else studio.toast(`第 ${active.number} 章已存档`, 'info')
}

function requestReject() {
  const list = selected.value.size
    ? [...selected.value]
    : activeRow.value != null
      ? [activeRow.value]
      : []
  if (!list.length) {
    studio.toast('先勾选要退回的章', 'warn')
    return
  }
  rejectTargets.value = list.sort((a, b) => a - b)
  rejectConfirmOpen.value = true
}

async function confirmBatchReject() {
  const list = [...rejectTargets.value]
  rejectConfirmOpen.value = false
  if (!list.length) return
  const failed: number[] = []
  for (const n of list) {
    await studio.reject(n, '批量退回')
    if (studio.findChapter(n)) failed.push(n)
  }
  if (failed.length) {
    selected.value = new Set(failed)
    studio.toast(`已退回 ${list.length - failed.length} 章；第 ${failed.join('、')} 章没退成功`, 'warn')
  } else {
    selected.value = new Set()
    studio.toast(`已退回 ${list.length} 章，旧稿在「废章」`, 'warn')
  }
}

function clearRange() {
  rangeFrom.value = null
  rangeTo.value = null
  // 只清本地状态会让 URL 和页面对不上：之后再点「去审阅」是同一个地址，不会再触发同步。
  if (route.query.from || route.query.to) {
    const query = { ...route.query }
    delete query.from
    delete query.to
    void router.replace({ path: route.path, query })
  }
}

const sevTone = (s: Finding['severity']) => (s === 'high' ? 'bad' : s === 'mid' ? 'warn' : 'neutral')
const sevLabel = (s: Finding['severity']) => (s === 'high' ? '硬伤' : s === 'mid' ? '建议' : '提醒')

/* ---------- 跨章问题里逐条处理到期伏笔 ---------- */

type OverdueLine = NonNullable<Finding['items']>[number]
const fsAction = ref<{ mode: 'payoff' | 'abandon'; line: OverdueLine } | null>(null)
const fsPayoffChapter = ref('')
const fsBusy = ref(false)

function askPayoff(line: OverdueLine) {
  fsAction.value = { mode: 'payoff', line }
  fsPayoffChapter.value = String(line.dueChapter || studio.batch?.to || 1)
}

function askAbandon(line: OverdueLine) {
  fsAction.value = { mode: 'abandon', line }
}

/** 处理完立刻重跑按批体检，让跨章问题自己消失，不用作者再点一次「体检」。 */
async function confirmFsAction() {
  const act = fsAction.value
  if (!act || fsBusy.value) return
  fsBusy.value = true
  try {
    if (act.mode === 'payoff') {
      const chapter = Math.max(1, Math.floor(Number(fsPayoffChapter.value) || 0))
      if (!chapter) {
        studio.toast('填一下收在第几章', 'warn')
        return
      }
      // 面板上的同一行可能合并了几条重复录入：一起处理，避免点完又冒出来。
      for (const id of act.line.ids?.length ? act.line.ids : [act.line.id]) {
        await studio.payoffForeshadow(id, chapter)
      }
    } else {
      for (const id of act.line.ids?.length ? act.line.ids : [act.line.id]) {
        await studio.abandonForeshadow(id)
      }
    }
    fsAction.value = null
    await studio.runBatchCheck(studio.batch?.from, studio.batch?.to)
  } catch (e) {
    studio.toast(`处理失败：${e instanceof Error ? e.message : String(e)}`, 'warn')
  } finally {
    fsBusy.value = false
  }
}

function tally(n: number) {
  const list = studio.checks[n]?.findings ?? []
  return {
    high: list.filter((f) => f.severity === 'high').length,
    mid: list.filter((f) => f.severity === 'mid').length,
    total: list.length,
  }
}

function openCopy(n: number) {
  copyTarget.value = n
  showCopy.value = true
  studio.loadText(n)
}

async function doCopy() {
  const c = studio.findChapter(copyTarget.value)
  const text = `${c?.title ?? ''}\n\n${await copyText(copyTarget.value)}`
  try {
    await navigator.clipboard.writeText(text)
    studio.toast(`已复制第 ${copyTarget.value} 章正文`, 'ok')
  } catch {
    studio.toast('复制失败：浏览器不允许写剪贴板，请手动选中', 'warn')
  }
  showCopy.value = false
}

function startRewrite(n: number) {
  rewriteChapter.value = n
  rewriteError.value = ''
  rewriteOpen.value = true
  // 复检结果是内存里的，刷新过就没了：先捞一轮回来，弹窗里才看得到复检没过的问题。
  void studio.loadAiRound(n)
  if (!studio.checkResults[n]) void studio.check(n)
  if (studio.texts[n] == null) studio.loadText(n)
}

async function submitRewrite(payload: { skills: string[]; instruction: string; findings: Finding[] }) {
  const n = rewriteChapter.value
  rewriteBusy.value = true
  rewriteError.value = ''
  try {
    await studio.rewrite(n, '', payload.skills, payload.instruction, payload.findings)
    rewriteOpen.value = false
  } catch (e) {
    rewriteError.value = e instanceof Error ? e.message : String(e)
  } finally {
    rewriteBusy.value = false
  }
}

function aiReview(n: number) {
  void studio.aiCheck(n)
}

/** 复检点名的段落就地重写；改完原句消失就自动从面板摘掉。 */
function rewritePara(n: number, finding: Finding) {
  if (!finding.paragraph) return
  void studio.rewriteParagraph(n, finding.paragraph, finding).catch(() => {})
}

/** 作者确认这条已经处理：从本轮复检里摘掉，不再重新扫。 */
function resolveFinding(n: number, finding: Finding) {
  void studio.markAiResolved(n, finding)
}

/** 明确要求重新出题：旧轮次剩余条目作废。 */
function rescanAi(n: number) {
  void studio.newAiRound(n).catch(() => {})
}

function openCheck(n: number) {
  expanded.value = n
  activeRow.value = n
  if (!studio.checkResults[n]) void studio.check(n)
}

/** 体检面板的「定位」：展开本章，把引文设为搜索高亮，滚到对应段。 */
function locateSample(n: number, payload: { text: string; paragraph: number; offset: number }) {
  expanded.value = n
  activeRow.value = n
  void studio.loadText(n)
  search[n] = payload.text
  nextTick(() => {
    const body = document.querySelector<HTMLElement>(`[data-chapter="${n}"] .row__prose`)
    const target = body?.querySelectorAll<HTMLElement>('p')[Math.max(0, payload.paragraph - 1)]
    ;(target ?? body)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  })
}

function toggle(n: number) {
  activeRow.value = n
  expanded.value = expanded.value === n ? null : n
  if (expanded.value === n) studio.loadText(n)
}

function paragraphs(n: number): string[] {
  const text = studio.texts[n] ?? ''
  const blocks = text.split(/\n{2,}/).map((s) => s.trim()).filter(Boolean)
  return blocks.length ? blocks : [text]
}

async function copyText(n: number): Promise<string> {
  return studio.texts[n] ?? (await studio.loadText(n)) ?? studio.findChapter(n)?.summary ?? ''
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="写 · 审 · 存"
      title="进度"
      :desc="`${scopeDesc}${prefs.autoArchive ? '自动存档已开：进页面会存档待确认章；你勾选章节时本次自动存档暂停。' : '手动模式：勾选章节后批量存档或退回；勾选不会等你保存。'}`"
    >
      <Button :disabled="studio.batchBusy" icon="⚗" @click="studio.runBatchCheck()">
        {{ studio.batchBusy ? '按批体检中…' : batchCheckLabel }}
      </Button>
      <Button variant="ghost" icon="☰" @click="$router.push({ name: 'detail' })">段落纲</Button>
      <Button
        variant="ghost"
        icon="⤓"
        :disabled="studio.exportBusy"
        @click="studio.exportBook()"
      >
        {{ studio.exportBusy ? '导出中…' : '导出 TXT' }}
      </Button>
      <Button variant="ghost" icon="↺" :disabled="studio.syncBusy" @click="openSync">回灌手改</Button>
    </PageHeader>

    <div class="batchbar">
      <div class="batchbar__left">
        <span class="batchbar__range ns-mono">{{ batchLabel }}</span>
        <div class="batchbar__meta">
          <b>{{ batchDone }}/{{ inBatch.length }} 章已存档</b>
          <span>{{ studio.book.targetChapters }} 章全书 · 第 {{ studio.nextNumber }} 章下一章 · 每章硬下限 {{ studio.book.minChars }} 字</span>
        </div>
        <Button v-if="batchRange" size="sm" variant="ghost" @click="clearRange">清除范围</Button>
      </div>
      <div class="batchbar__track"><i :style="{ width: `${batchProgress}%` }" /></div>
      <div class="batchbar__filters">
        <button v-for="f in [
          { k: 'all', t: '全部' },
          { k: 'pending', t: `待确认 ${studio.pending.length}` },
          { k: 'approved', t: '已存档' },
          { k: 'issues', t: '有体检问题' },
        ]" :key="f.k" type="button" class="batchbar__filter" :class="{ on: filter === f.k }" @click="filter = f.k as typeof filter">
          {{ f.t }}
        </button>
      </div>
      <div class="batchbar__keys" aria-label="键盘快捷键">
        <kbd class="ns-kbd">J</kbd><kbd class="ns-kbd">K</kbd><span>走章</span>
        <kbd class="ns-kbd">空格</kbd><span>勾选</span>
        <kbd class="ns-kbd">A</kbd><span>存档</span>
        <kbd class="ns-kbd">R</kbd><span>退回</span>
        <kbd class="ns-kbd">⇧R</kbd><span>退回并重写</span>
        <kbd class="ns-kbd">B</kbd><span>体检</span>
      </div>
    </div>

    <div class="selectbar" :class="{ 'selectbar--on': selectedCount > 0 }">
      <span class="selectbar__count">已选 <b>{{ selectedCount }}</b> 章</span>
      <Button size="sm" variant="ghost" @click="selectPendingInBatch">全选待确认</Button>
      <Button size="sm" variant="ghost" :disabled="!selectedCount" @click="clearSelected">清空</Button>
      <span class="selectbar__spacer" />
      <Button size="sm" variant="primary" :disabled="!selectedCount" @click="archiveSelectedNow">
        存档选中 {{ selectedCount }} 章
      </Button>
      <Button
        size="sm"
        variant="ghost"
        class="selectbar__danger"
        :disabled="!selectedCount && activeRow == null"
        @click="requestReject"
      >退回选中</Button>
    </div>

    <Card v-if="studio.batch" class="batchcard" eyebrow="整批视角" :title="`按批体检 第 ${studio.batch.from}–${studio.batch.to} 章`">
      <template #actions>
        <Button size="sm" variant="ghost" @click="studio.batch = null">关闭</Button>
      </template>
      <div class="batchcard__summary">
        <template v-if="todoRewrite.length">
          要重写：第 {{ todoRewrite.join('、') }} 章。
        </template>
        <template v-else>没有要重写的章。</template>
        {{ studio.batch.blocking.length ? `整批问题 ${studio.batch.blocking.length} 条。` : '' }}
        单章问题已铺在下面每一章，要改就点那一章的「重写本章」。
      </div>
      <p v-if="studio.batch.autoPaid?.length" class="batchcard__autopaid">
        核对正文：{{ autoPaidText }}。账本已记收，判错了可在
        <RouterLink :to="{ name: 'foreshadow' }">伏笔页</RouterLink>「重新打开」。
      </p>
      <div v-if="studio.batch.blocking.length" class="blocking">
        <div class="blocking__title">跨章问题（不属于某一章，处理掉再存档）</div>
        <div v-for="(f, i) in studio.batch.blocking" :key="i" class="blocking__item">
          <Tag size="sm" :tone="sevTone(f.severity)">{{ sevLabel(f.severity) }}</Tag>
          <div class="blocking__body">
            <b>{{ f.message }}</b>
            <p v-if="f.hint">{{ f.hint }}</p>
            <ul v-if="f.items?.length" class="blocking__lines">
              <li v-for="it in f.items" :key="it.id">
                <span class="blocking__name">{{ it.name }}</span>
                <span class="blocking__meta">埋 {{ it.plantedChapter }} · 计划第 {{ it.dueChapter }} 章收</span>
                <Tag v-if="it.overdueBy" size="sm" tone="bad" dot>超期 {{ it.overdueBy }} 章</Tag>
                <Tag v-if="it.duplicates" size="sm" tone="neutral">另有 {{ it.duplicates }} 条重复</Tag>
                <span class="blocking__acts">
                  <Button size="sm" variant="ghost" @click="askPayoff(it)">已经写了 → 标为已收</Button>
                  <Button size="sm" variant="ghost" class="blocking__drop" @click="askAbandon(it)">不写了 → 放弃</Button>
                </span>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </Card>

    <div class="list">
      <div
        v-for="c in rows"
        :key="c.number"
        class="row"
        :class="{ 'row--pending': !c.approved, 'row--open': expanded === c.number, 'row--active': activeRow === c.number, 'row--selected': selected.has(c.number) }"
        :data-chapter="c.number"
      >
        <div class="row__main" @click="toggle(c.number)">
          <label class="row__check" @click.stop>
            <input
              type="checkbox"
              :checked="selected.has(c.number)"
              :disabled="c.chars <= 0"
              :title="c.chars <= 0 ? '这一章还没有正文' : '选择这一章'"
              :aria-label="`选择第 ${c.number} 章`"
              @change="toggleSelected(c.number)"
            />
          </label>
          <span class="row__num ns-mono">{{ String(c.number).padStart(3, '0') }}</span>
          <div class="row__title">
            <b>{{ c.title }}</b>
            <span class="row__summary">{{ c.summary }}</span>
          </div>
          <div class="row__chars" :class="{ 'row__chars--short': c.chars < studio.book.minChars }">
            {{ c.chars }} 字
            <small v-if="c.chars < studio.book.minChars && c.chars > 0">低于下限</small>
          </div>
          <div class="row__tags">
            <Tag v-if="studio.checks[c.number]?.fromBatch" size="sm" tone="info" dot>按批体检</Tag>
            <button
              type="button"
              class="row__checkchip"
              :class="{
                'row__checkchip--bad': tally(c.number).high > 0,
                'row__checkchip--warn': !tally(c.number).high && tally(c.number).mid > 0,
                'row__checkchip--ok': studio.checkResults[c.number] && !tally(c.number).high && !tally(c.number).mid,
              }"
              :title="studio.checkResults[c.number] ? '打开体检面板' : '还没体检'"
              @click.stop="openCheck(c.number)"
            >
              {{
                studio.checkResults[c.number]
                  ? tally(c.number).high
                    ? `体检 ${tally(c.number).high} 硬伤`
                    : tally(c.number).mid
                      ? `体检 ${tally(c.number).mid} 条建议`
                      : '体检通过'
                  : '未体检'
              }}
            </button>
            <Tag v-if="!c.endHook.ok" size="sm" tone="warn">章尾弱</Tag>
            <Tag v-if="!c.approved" size="sm" tone="pink" dot>待确认</Tag>
            <Tag v-else-if="c.chapterVerdict === 'needs_fix'" size="sm" tone="bad">待修</Tag>
            <Tag v-else size="sm" tone="ok">已存档</Tag>
          </div>
          <span class="row__caret">{{ expanded === c.number ? '⌃' : '⌄' }}</span>
        </div>

        <div v-if="!c.approved" class="row__acts row__acts--pending">
          <Button size="sm" variant="ghost" class="row__discard" @click="startRewrite(c.number)">退回并重写</Button>
          <Button size="sm" :disabled="studio.aiCheckLoading[c.number]" @click="aiReview(c.number)">
            {{ studio.aiCheckLoading[c.number] ? 'AI 复检中…' : 'AI 复检' }}
          </Button>
          <Button size="sm" @click="openCopy(c.number)">复制</Button>
          <div class="row__pending-tail">
            <span class="row__pending-label">待确认</span>
            <Button size="sm" variant="pink" :disabled="studio.saving === c.number" @click="studio.archive(c.number)">存档</Button>
          </div>
        </div>
        <div v-else class="row__acts">
          <Button v-if="tally(c.number).high || c.chapterVerdict === 'needs_fix'" size="sm" variant="primary" @click="startRewrite(c.number)">按问题重写</Button>
          <Button size="sm" :disabled="studio.checkLoading[c.number]" @click="studio.check(c.number)">
            {{ studio.checkLoading[c.number] ? '体检中…' : '体检' }}
          </Button>
          <Button size="sm" :disabled="studio.aiCheckLoading[c.number]" @click="aiReview(c.number)">
            {{ studio.aiCheckLoading[c.number] ? 'AI 复检中…' : 'AI 复检' }}
          </Button>
          <Button size="sm" variant="ghost" @click="openCopy(c.number)">复制</Button>
          <Button size="sm" variant="ghost" class="row__discard" :disabled="studio.saving === c.number" @click="studio.reject(c.number)">退回</Button>
        </div>

        <div v-if="studio.checks[c.number] && !studio.checkResults[c.number]" class="findings">
          <div class="findings__head">
            <span class="ns-eyebrow">第 {{ c.number }} 章体检</span>
            <Tag size="sm" :tone="tally(c.number).high ? 'bad' : tally(c.number).mid ? 'warn' : 'ok'">
              {{ tally(c.number).high }} 硬伤 · {{ tally(c.number).mid }} 条建议 · {{ tally(c.number).total }} 条
            </Tag>
            <span v-if="!tally(c.number).total" class="findings__ok">没发现连续性问题</span>
            <Button size="sm" variant="ghost" class="findings__rw" @click="startRewrite(c.number)">重写本章</Button>
          </div>
          <ul v-if="tally(c.number).total" class="findings__list">
            <li v-for="(f, i) in studio.checks[c.number].findings" :key="i" :class="`findings__item findings__item--${f.severity}`">
              <Tag size="sm" :tone="sevTone(f.severity)">{{ sevLabel(f.severity) }}</Tag>
              <div>
                <b>{{ f.message }}</b>
                <p v-if="f.hint">{{ f.hint }}</p>
              </div>
            </li>
          </ul>
        </div>

        <Transition name="expand">
          <div v-if="expanded === c.number" class="row__body">
            <div class="row__search">
              <Input v-model="search[c.number]" size="sm" type="search" placeholder="在正文里搜（断层位置、某句原话都可以）">
                <template #prefix>⌕</template>
              </Input>
              <span v-if="search[c.number]" class="row__hits">命中高亮显示</span>
            </div>
            <div v-if="studio.textLoading[c.number]" class="row__loading">正在读正文…</div>
            <div v-else class="ns-prose row__prose">
              <p v-for="(para, i) in paragraphs(c.number)" :key="i">
                <template
                  v-for="(seg, j) in highlightSegments(para, search[c.number] ?? '')"
                  :key="j"
                >
                  <mark v-if="seg.hit" class="row__mark">{{ seg.text }}</mark>
                  <template v-else>{{ seg.text }}</template>
                </template>
              </p>
              <p v-if="!studio.texts[c.number]" class="row__fallback">{{ c.summary || '正文还没读出来。' }}</p>
            </div>
            <div class="row__bodyfoot">
              <RuleChip :ok="c.endHook.ok" :label="c.endHook.ok ? '章尾有钩子' : `章尾没钩子：${c.endHook.reason ?? ''}`" />
              <RuleChip :ok="c.dialogueRatio >= 0.2" :label="`对话比 ${Math.round(c.dialogueRatio * 100)}%`" />
              <RuleChip :ok="c.chars >= studio.book.minChars || studio.book.targetChapters <= 50" :label="`${c.chars} 字`" />
              <Button size="sm" variant="ghost" :disabled="studio.checkLoading[c.number]" @click="studio.check(c.number)">
                {{ studio.checkLoading[c.number] ? '体检中…' : '体检' }}
              </Button>
              <Button size="sm" variant="ghost" :disabled="studio.aiCheckLoading[c.number]" @click="aiReview(c.number)">
                {{ studio.aiCheckLoading[c.number] ? 'AI 复检中…' : 'AI 复检' }}
              </Button>
              <Button size="sm" variant="ghost" @click="startRewrite(c.number)">按技能改写</Button>
            </div>

            <ChapterCheckPanel
              v-if="studio.checkResults[c.number]"
              :chapter="c.number"
              :result="studio.checkResults[c.number]"
              :ai-result="studio.aiChecks[c.number] ?? null"
              :stale="!!studio.checkStale[c.number]"
              :loading="!!studio.checkLoading[c.number]"
              :ai-loading="!!studio.aiCheckLoading[c.number]"
              :ai-stream="studio.liveGen.active && studio.liveGen.kind === 'ai-check' ? studio.liveGen : null"
              :paragraph-busy="!!studio.paragraphBusy[c.number]"
              :paragraph-stream="studio.liveGen.active && studio.liveGen.kind === 'paragraph' ? studio.liveGen : null"
              :can-rewrite="c.chars > 0"
              @refresh="studio.check(c.number)"
              @ai-check="aiReview(c.number)"
              @ai-rescan="rescanAi(c.number)"
              @rewrite-paragraph="(finding) => rewritePara(c.number, finding)"
              @resolve-finding="(finding) => resolveFinding(c.number, finding)"
              @dismiss-sample="(payload) => studio.dismissCheck(c.number, payload)"
              @rewrite="startRewrite(c.number)"
              @close="expanded = null"
              @locate="(payload) => locateSample(c.number, payload)"
            />
          </div>
        </Transition>
      </div>
      <EmptyState
        v-if="!rows.length"
        icon="▦"
        :title="studio.chapters.length ? '这个筛选下没有章节' : '还没有可审阅的章'"
        :desc="studio.chapters.length ? '换一个筛选，或者回「今日」规划下一批。' : '先去「今日」开写第一批；写完回来存档，或退回重写。'"
      />
    </div>

    <Modal :open="showCopy" :title="`第 ${copyTarget} 章正文`" desc="整章复制，不改任何文件。粘贴到你的编辑器里改。" width="680px" @close="showCopy = false">
      <div class="ns-prose copybox">
        <pre>{{ studio.texts[copyTarget] ?? studio.findChapter(copyTarget)?.summary }}</pre>
      </div>
      <template #footer>
        <Button variant="ghost" @click="showCopy = false">关闭</Button>
        <Button variant="primary" @click="doCopy">复制全文</Button>
      </template>
    </Modal>

    <SkillRewriteModal
      :open="rewriteOpen"
      :chapter="rewriteChapter"
      :suggested="studio.checkResults[rewriteChapter]?.suggestedSkills ?? []"
      :findings="(studio.aiChecks[rewriteChapter] ?? studio.checkResults[rewriteChapter])?.findings ?? []"
      :ai-tells="studio.checkResults[rewriteChapter]?.aiTells ?? null"
      :busy="rewriteBusy"
      :error="rewriteError"
      :stream="studio.liveGen.active && studio.liveGen.kind === 'rewrite' ? studio.liveGen : null"
      @close="rewriteOpen = false"
      @submit="submitRewrite"
    />

    <Modal
      :open="!!studio.blocked"
      title="这一章还有硬伤"
      :desc="studio.blocked?.message"
      width="640px"
      @close="studio.blocked = null"
    >
      <ul class="blockedlist">
        <li v-for="(f, i) in studio.blocked?.findings ?? []" :key="i" :class="`blockedlist__item blockedlist__item--${f.severity}`">
          <Tag size="sm" :tone="sevTone(f.severity)">{{ sevLabel(f.severity) }}</Tag>
          <div>
            <b>{{ f.message }}</b>
            <p v-if="f.hint">{{ f.hint }}</p>
          </div>
        </li>
      </ul>
      <template #footer>
        <Button variant="ghost" @click="studio.blocked = null">先不改</Button>
        <Button variant="primary" @click="studio.blocked && studio.archive(studio.blocked.number, true)">
          仍然存档
        </Button>
      </template>
    </Modal>

    <Modal
      :open="!!fsAction"
      :title="fsAction?.mode === 'payoff' ? `收线：${fsAction?.line.name}` : `放弃：${fsAction?.line.name}`"
      :desc="
        fsAction?.mode === 'payoff'
          ? '正文里已经写出来了，就标成已收。记下它是在第几章被读回来的。'
          : '这条线不打算交代了。账本只追加一条放弃事件，正文不用改，体检也不再追。'
      "
      width="480px"
      @close="fsAction = null"
    >
      <div v-if="fsAction?.mode === 'payoff'" class="fsact">
        <Input v-model="fsPayoffChapter" label="收在第几章" type="number" />
        <p class="fsact__note">
          埋于第 {{ fsAction.line.plantedChapter }} 章，计划第 {{ fsAction.line.dueChapter }} 章收。
          <template v-if="fsAction.line.duplicates">
            这一行合并了 {{ fsAction.line.duplicates }} 条重复录入，标一次会一起处理。
          </template>
        </p>
      </div>
      <p v-else class="fsact__note">
        埋于第 {{ fsAction?.line.plantedChapter }} 章，计划第 {{ fsAction?.line.dueChapter }} 章收，
        已超期 {{ fsAction?.line.overdueBy }} 章。放弃不删账，只是不再提醒。
        <template v-if="fsAction?.line.duplicates">
          这一行合并了 {{ fsAction.line.duplicates }} 条重复录入，放弃一次会一起处理。
        </template>
      </p>
      <template #footer>
        <Button variant="ghost" :disabled="fsBusy" @click="fsAction = null">取消</Button>
        <Button variant="primary" :disabled="fsBusy" @click="confirmFsAction">
          {{ fsBusy ? '处理中…' : fsAction?.mode === 'payoff' ? '标为已收' : '放弃这条线' }}
        </Button>
      </template>
    </Modal>

    <Modal
      :open="rejectConfirmOpen"
      :title="`退回 ${rejectTargets.length} 章？`"
      desc="旧稿会进「废章」，章号释放，可以立刻重写。这个动作不会自动重写。"
      width="520px"
      @close="rejectConfirmOpen = false"
    >
      <p class="reject-list">
        第 {{ rejectTargets.join('、') }} 章
      </p>
      <template #footer>
        <Button variant="ghost" @click="rejectConfirmOpen = false">取消</Button>
        <Button variant="danger" @click="confirmBatchReject">退回 {{ rejectTargets.length }} 章</Button>
      </template>
    </Modal>

    <Modal
      :open="syncOpen"
      title="手改回灌"
      desc="应用外直接改过 chapters/*.md 之后，索引、章记忆、人物状态都还停在旧稿上。这里按正文指纹找出差异，重走一遍写正文后的回灌。"
      width="680px"
      @close="syncOpen = false"
    >
      <div v-if="syncScanData" class="sync">
        <p class="sync__sum">
          目录 {{ syncScanData.chapters }} 章 · 索引 {{ syncScanData.indexed }} 章 ·
          改过 {{ syncScanData.counts.edited }} · 未进索引 {{ syncScanData.counts.untracked }} ·
          记忆过期 {{ syncScanData.counts.memoryStale }} · 旧书基线 {{ syncScanData.counts.baseline }}
        </p>
        <ul v-if="syncScanData.items.length" class="sync__list">
          <li v-for="x in syncScanData.items" :key="x.number" class="sync__row" :class="{ 'sync__row--skip': x.kind === 'missing' }">
            <label class="sync__pick">
              <input
                type="checkbox"
                :disabled="x.kind === 'missing'"
                :checked="syncPicked.has(x.number)"
                @change="toggleSync(x.number)"
              />
              <b>第 {{ x.number }} 章</b>
              <span class="sync__title">{{ x.title }}</span>
            </label>
            <Tag size="sm" :tone="x.kind === 'missing' ? 'bad' : x.kind === 'edited' ? 'warn' : 'neutral'">
              {{ SYNC_LABEL[x.kind] || x.kind }}
            </Tag>
            <span class="sync__reason">{{ x.reason }}</span>
          </li>
        </ul>
        <p v-else class="sync__ok">正文、索引和记忆都对得上，没有要回灌的章。</p>
        <label class="sync__memory">
          <input v-model="syncMemory" type="checkbox" :disabled="!syncPicked.size" />
          <span>重新提炼章记忆（会调模型，一章一次；关掉只重算字数 / 判定 / 指纹）</span>
        </label>
        <p class="sync__note">
          「旧书补基线」只记指纹、不重跑记忆；「正文缺失」不处理，正文文件不在了不能凭空补。
        </p>
      </div>
      <p v-else class="sync__ok">正在扫描…</p>
      <template #footer>
        <Button variant="ghost" @click="syncOpen = false">关闭</Button>
        <Button
          variant="primary"
          :disabled="studio.syncBusy || !syncPicked.size"
          @click="applySyncPicked"
        >
          {{ studio.syncBusy ? '回灌中…' : `回灌 ${syncPicked.size} 章` }}
        </Button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.page {
  max-width: 1120px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.batchbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.batchbar__left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.batchbar__range {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-18);
  font-weight: 700;
  padding-right: 12px;
  border-right: 1px solid var(--ns-line);
}
.batchbar__meta {
  display: grid;
  line-height: 1.4;
}
.batchbar__meta b {
  font-size: 12.5px;
}
.batchbar__meta span {
  font-size: 11px;
  color: var(--ns-ink-3);
}
.batchbar__track {
  flex: 1 1 120px;
  min-width: 80px;
  height: 5px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-card-2);
  overflow: hidden;
}
.batchbar__track i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--ns-pink), #f27ab1);
  border-radius: inherit;
  transition: width 0.4s ease;
}
.batchbar__filters {
  display: inline-flex;
  padding: 2px;
  gap: 1px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.batchbar__filter {
  border: 0;
  background: transparent;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 11.5px;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}
.batchbar__filter:hover {
  color: var(--ns-ink);
}
.batchbar__filter.on {
  background: var(--ns-card);
  color: var(--ns-ink);
  font-weight: 600;
  box-shadow: var(--ns-shadow-1);
}
.batchbar__keys {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding-left: 12px;
  border-left: 1px solid var(--ns-line);
  font-size: 10.5px;
  color: var(--ns-ink-4);
}
.batchbar__keys span {
  margin-right: 5px;
}
@media (max-width: 1100px) {
  .batchbar__keys {
    display: none;
  }
}
.batchcard {
  margin-bottom: 14px;
}
.batchcard__summary {
  font-size: 12.5px;
  color: var(--ns-ink-2);
  margin-bottom: 12px;
}
.batchcard__autopaid {
  margin: -4px 0 12px;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--ns-ink-3);
}
.batchcard__autopaid a {
  color: var(--ns-ink-2);
  text-decoration: underline;
}
.blocking {
  border: 1px solid color-mix(in srgb, var(--ns-warn) 28%, transparent);
  background: var(--ns-warn-soft);
  border-radius: var(--ns-r-sm);
  padding: 11px 13px;
  display: grid;
  gap: 8px;
}
.blocking__title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.03em;
  color: var(--ns-warn);
  text-transform: uppercase;
}
.blocking__item {
  display: flex;
  gap: 9px;
  align-items: flex-start;
}
.blocking__item b {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ns-ink);
}
.blocking__item p {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--ns-ink-2);
}
.blocking__body {
  flex: 1;
  min-width: 0;
}
.blocking__lines {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.blocking__lines li {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 5px 9px;
  border-radius: var(--ns-r-xs);
  background: color-mix(in srgb, var(--ns-card) 72%, transparent);
}
.blocking__name {
  font-size: 12px;
  font-weight: 600;
  color: var(--ns-ink);
}
.blocking__meta {
  font-size: 10.5px;
  color: var(--ns-ink-3);
  font-variant-numeric: tabular-nums;
}
.blocking__acts {
  margin-left: auto;
  display: flex;
  gap: 2px;
}
.blocking__drop {
  color: var(--ns-ink-3);
}
.blocking__drop:hover {
  color: var(--ns-bad);
}
.fsact {
  display: grid;
  gap: 8px;
}
.fsact__note {
  margin: 0;
  font-size: 11.5px;
  color: var(--ns-ink-3);
  line-height: 1.65;
}
.list {
  display: grid;
  gap: 8px;
}
.row {
  background: var(--ns-card);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  padding: 0 16px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.row:hover {
  border-color: var(--ns-line-2);
}
.row--pending {
  border-color: var(--ns-pink-line);
  background: linear-gradient(0deg, var(--ns-card), var(--ns-card)) padding-box, linear-gradient(90deg, var(--ns-pink-line), transparent) border-box;
}
.row--open {
  box-shadow: var(--ns-shadow-1);
}
.row--active {
  border-color: var(--ns-ink-4);
  box-shadow: 0 0 0 1px var(--ns-ink-4) inset;
}
.row--active .row__num {
  color: var(--ns-pink);
}
.row__main {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 13px 0 10px;
  cursor: pointer;
}
.row__num {
  flex: none;
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-4);
  padding-top: 2px;
  letter-spacing: 0.02em;
}
.row__title {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 3px;
}
.row__title b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  line-height: 1.4;
}
.row__summary {
  font-size: 11.5px;
  color: var(--ns-ink-3);
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.row__chars {
  flex: none;
  font-size: 11.5px;
  color: var(--ns-ink-3);
  text-align: right;
  font-variant-numeric: tabular-nums;
  padding-top: 2px;
  display: grid;
  justify-items: end;
}
.row__chars small {
  font-size: 10px;
  color: var(--ns-bad);
}
.row__chars--short {
  color: var(--ns-bad);
}
.row__tags {
  flex: none;
  display: flex;
  gap: 4px;
  align-items: center;
  padding-top: 1px;
}
.row__checkchip {
  border: 1px solid var(--ns-line);
  background: var(--ns-card-2);
  color: var(--ns-ink-2);
  border-radius: var(--ns-r-pill);
  font: inherit;
  font-size: 10.5px;
  font-weight: 600;
  line-height: 1.7;
  padding: 0 7px;
  cursor: pointer;
  white-space: nowrap;
}
.row__checkchip--bad {
  color: var(--ns-bad);
  border-color: color-mix(in srgb, var(--ns-bad) 26%, transparent);
  background: var(--ns-bad-soft, var(--ns-card-2));
}
.row__checkchip--warn {
  color: var(--ns-warn);
  border-color: color-mix(in srgb, var(--ns-warn) 26%, transparent);
}
.row__checkchip--ok {
  color: var(--ns-ok);
  border-color: color-mix(in srgb, var(--ns-ok) 22%, transparent);
}
.row__caret {
  flex: none;
  color: var(--ns-ink-4);
  font-size: 12px;
  width: 14px;
  text-align: center;
  padding-top: 2px;
}
.row__acts {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  padding: 0 0 12px 40px;
}
.row__acts--pending {
  align-items: center;
  padding-left: 0;
}
.row__pending-tail {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  padding-left: 10px;
  border-left: 1px dashed var(--ns-line-2);
}
.row__pending-label {
  font-size: 11px;
  color: var(--ns-pink-ink, var(--ns-pink));
  letter-spacing: 0.04em;
}
.row__discard {
  color: var(--ns-bad);
}
.findings {
  margin: 0 0 12px 40px;
  padding: 10px 12px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  border: 1px solid var(--ns-line);
}
.findings__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.findings__ok {
  font-size: 11.5px;
  color: var(--ns-ok);
}
.findings__rw {
  margin-left: auto;
}
.findings__list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.findings__item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding-left: 8px;
  border-left: 2px solid var(--ns-line-2);
}
.findings__item--high {
  border-left-color: var(--ns-bad);
}
.findings__item--mid {
  border-left-color: var(--ns-warn);
}
.findings__item b {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--ns-ink);
}
.findings__item p {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--ns-ink-3);
  line-height: 1.55;
}
.row__body {
  border-top: 1px dashed var(--ns-line);
  padding: 12px 0 14px 40px;
}
.row__search {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.row__hits {
  font-size: 11px;
  color: var(--ns-ink-3);
  white-space: nowrap;
}
.row__mark {
  padding: 0 1px;
  border-radius: 2px;
  background: color-mix(in srgb, var(--ns-gold) 38%, transparent);
  color: inherit;
}
.row__prose {
  max-height: 380px;
  overflow: auto;
  padding: 4px 14px 4px 0;
  background: var(--ns-paper);
  border-radius: var(--ns-r-sm);
  padding-left: 16px;
}
.row__prose :deep(p) {
  text-indent: 0;
  margin-bottom: 0.75em;
}
.row__loading,
.row__fallback {
  padding: 16px;
  color: var(--ns-ink-3);
  font-size: 13px;
  background: var(--ns-paper);
  border-radius: var(--ns-r-sm);
}
.row__fallback {
  margin: 0;
}
.blockedlist {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 10px;
  max-height: 50vh;
  overflow: auto;
}
.blockedlist__item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 10px 12px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
}
.blockedlist__item b {
  display: block;
  font-size: 13px;
  line-height: 1.6;
}
.blockedlist__item p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ns-ink-3);
  line-height: 1.6;
}
.row__bodyfoot {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.copybox pre {
  margin: 0;
  white-space: pre-wrap;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  line-height: 1.95;
  max-height: 380px;
  overflow: auto;
}
.expand-enter-active,
.expand-leave-active {
  transition: opacity 0.15s ease;
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
}
@media (max-width: 760px) {
  .page {
    padding: 20px 16px 64px;
  }
  .row__summary,
  .row__chars {
    display: none;
  }
  .row__acts,
  .findings,
  .row__body {
    padding-left: 0;
    margin-left: 0;
  }
}
.sync {
  display: grid;
  gap: var(--ns-s3);
}
.sync__sum {
  margin: 0;
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
}
.sync__list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 320px;
  overflow-y: auto;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
}
.sync__row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--ns-line);
  font-size: var(--ns-fs-12);
}
.sync__row:last-child {
  border-bottom: 0;
}
.sync__row--skip {
  opacity: 0.6;
}
.sync__pick {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 180px;
}
.sync__title {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.sync__reason {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.sync__ok {
  margin: 0;
  padding: var(--ns-s4);
  text-align: center;
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-3);
}
.sync__memory {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-2);
}
.sync__note {
  margin: 0;
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
}
</style>

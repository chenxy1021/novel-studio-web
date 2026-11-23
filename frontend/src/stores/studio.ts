import { computed, reactive, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { foreshadows as signalForeshadows } from '@/mocks/signalTower'
import { segmentStages, type SegmentStage } from '@/mocks'
import {
  batchCheckOf,
  bookData,
  bookOf,
  type BatchCheck,
  type BookKey,
  type Chapter,
  type Finding,
} from '@/mocks'

export type Toast = { id: number; text: string; tone: 'ok' | 'warn' | 'info' }

type CheckEntry = { pass: boolean; findings: Finding[]; fromBatch: boolean }

// localStorage 可能被浏览器策略禁用（Safari 无痕、隐私模式），读写都要兜底
function readLS(name: string): string | null {
  try {
    return localStorage.getItem(name)
  } catch {
    return null
  }
}
function writeLS(name: string, value: string) {
  try {
    localStorage.setItem(name, value)
  } catch {
    /* 写不进去就算了，内存里的状态照常用 */
  }
}
function readArchived(): Record<string, number[]> {
  try {
    return JSON.parse(readLS('ns.archived') ?? '{}') as Record<string, number[]>
  } catch {
    return {}
  }
}

export const useStudio = defineStore('studio', () => {
  const key = ref<BookKey>((readLS('ns.book') as BookKey) || 'signalTower')
  const data = computed(() => bookData(key.value))
  const book = computed(() => bookOf(key.value))

  /** chapters/index.json 的可变副本；存档/退回都会改动它 */
  const archived = ref<Record<string, number[]>>(readArchived())
  const seed = (k: BookKey): Chapter[] => {
    const list = structuredClone(bookData(k).chapters as Chapter[])
    for (const c of list) if (archived.value[k]?.includes(c.number)) c.approved = true
    return list
  }
  const chapters = ref<Chapter[]>(seed(key.value))
  const segList = ref(structuredClone(data.value.segments))
  const openThreads = ref<string[]>([])
  const foreshadows = ref(structuredClone(signalForeshadows))

  const checks = reactive<Record<number, CheckEntry>>({})
  const batch = ref<BatchCheck | null>(null)
  const batchBusy = ref(false)
  const saving = ref<number | null>(null)
  const autoArchived = computed(() => archived.value[key.value] ?? [])

  function markArchived(n: number) {
    const list = new Set(archived.value[key.value] ?? [])
    list.add(n)
    archived.value[key.value] = [...list]
    writeLS('ns.archived', JSON.stringify(archived.value))
  }

  /** 已处理过的章（存档或退回）不再被自动存档接管；退回后应停在待确认，等人改。 */
  function markHandled(n: number) {
    const k = key.value
    const list = new Set(archived.value[k] ?? [])
    if (list.has(n)) return
    list.add(n)
    archived.value[k] = [...list]
    writeLS('ns.archived', JSON.stringify(archived.value))
  }

  const toasts = ref<Toast[]>([])
  let toastId = 0
  function toast(text: string, tone: Toast['tone'] = 'info') {
    const id = ++toastId
    toasts.value.push({ id, text, tone })
    setTimeout(() => (toasts.value = toasts.value.filter((t) => t.id !== id)), 3200)
  }

  watch(key, (k) => {
    writeLS('ns.book', k)
    chapters.value = seed(k)
    segList.value = structuredClone(bookData(k).segments)
    Object.keys(checks).forEach((n) => delete checks[Number(n)])
    batch.value = null
    openThreads.value = []
  })

  const pending = computed(() => chapters.value.filter((c) => !c.approved))
  const approved = computed(() => chapters.value.filter((c) => c.approved))
  const totalChars = computed(() => approved.value.reduce((s, c) => s + c.chars, 0))
  const maxNumber = computed(() => chapters.value.reduce((m, c) => Math.max(m, c.number), 0))
  const nextNumber = computed(() => maxNumber.value + 1)
  const sortedChapters = computed(() => [...chapters.value].sort((a, b) => a.number - b.number))

  const currentSegment = computed(() => {
    const n = book.value.gate.chapter || nextNumber.value
    return segList.value.find((s) => n >= s.from && n <= s.to) ?? segList.value[segList.value.length - 1] ?? null
  })

  /** 进度页看"最近一批"：有已写正文章的那一段；正在写但一章没落的段也算。 */
  const recentSegment = computed(() => {
    const written = new Set(approved.value.map((c) => c.number))
    const hit = segList.value.find((s) => s.plan.stages.some((st) => st.chapters.some((n) => written.has(n))))
    if (hit) return hit
    const gate = book.value.gate.chapter || nextNumber.value
    return currentSegment.value ?? segList.value.find((s) => gate >= s.from && gate <= s.to) ?? null
  })

  const findChapter = (n: number) => chapters.value.find((c) => c.number === n) ?? null

  /** 待确认章进页面自动存档：作者要「直接存」，不弹确认框。 */
  function autoArchivePending() {
    const list = pending.value.filter((c) => !autoArchived.value.includes(c.number))
    if (!list.length) return
    for (const c of list) {
      c.approved = true
      markArchived(c.number)
    }
    toast(list.length > 1 ? `已自动存档 ${list.length} 章，问题见下面每章的体检` : `第 ${list[0].number} 章已自动存档，问题见下面体检`, 'ok')
  }

  function archive(n: number) {
    const c = findChapter(n)
    if (!c || c.approved) return
    c.approved = true
    markArchived(n)
    toast(`第 ${n} 章已确认存档`, 'ok')
  }

  function rewrite(n: number, note?: string) {
    const c = findChapter(n)
    if (!c) return
    c.approved = false
    c.chars = 0
    markHandled(n)
    const issues = checks[n]?.findings ?? []
    c.fixReasons = issues.filter((f) => f.severity === 'high').map((f) => f.message)
    toast(`第 ${n} 章已退回重写，旧稿存进「废章」${note ?? ''}`.trim(), 'warn')
  }

  function runBatchCheck() {
    const seg = currentSegment.value
    batchBusy.value = true
    setTimeout(() => {
      const result = batchCheckOf(key.value, seg ? seg.from : 1, seg ? seg.to : book.value.gate.chapter)
      batch.value = result
      for (const row of result.chapters) {
        checks[row.number] = { pass: row.pass, findings: row.findings, fromBatch: true }
      }
      batchBusy.value = false
      const todo = result.chapters.filter((c) => !c.pass).map((c) => c.number)
      toast(
        `按批体检第 ${result.from}–${result.to} 章：${todo.length ? `第 ${todo.join('、')} 章要重写` : '没有要重写的章'}${result.blocking.length ? `；${result.blocking.length} 条整批问题` : ''}，问题已铺在各章下面`,
        todo.length ? 'warn' : 'ok',
      )
    }, 420)
  }

  function saveSegment(planSpine: string, stages: SegmentStage[]) {
    const hit = segList.value.find((s) => s.from === stages[0]?.chapters[0])
    if (hit) {
      hit.spine = planSpine
      hit.plan.spine = planSpine
    }
    toast('段落纲已落账（ledger/segments.jsonl）', 'ok')
  }

  const wordsToday = computed(() => 4600)
  const streak = computed(() => 12)

  return {
    key,
    book,
    data,
    chapters,
    sortedChapters,
    pending,
    approved,
    totalChars,
    maxNumber,
    nextNumber,
    segList,
    currentSegment,
    recentSegment,
    checks,
    batch,
    batchBusy,
    saving,
    autoArchived,
    toasts,
    openThreads,
    foreshadows,
    wordsToday,
    streak,
    toast,
    findChapter,
    autoArchivePending,
    archive,
    rewrite,
    runBatchCheck,
    saveSegment,
    segmentStages,
  }
})

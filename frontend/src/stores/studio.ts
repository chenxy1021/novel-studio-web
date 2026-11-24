import { computed, reactive, ref } from 'vue'
import { defineStore } from 'pinia'
import { ApiError, getJSON, postJSON, type Finding } from '@/api/client'
import {
  fetchAiCheckStream,
  fetchChapterCheck,
  fetchRewrite,
  type AiCheckResult,
  type CheckResult,
} from '@/api/checkup'
import {
  archiveBatch as apiArchiveBatch,
  applyStylePreset as apiApplyStylePreset,
  fetchBook,
  fetchForeshadows,
  fetchMemoryOverview,
  fetchOutlines,
  fetchPlatforms,
  fetchShelf,
  fetchStyle,
  fetchStylePresets,
  fetchWritingSkills,
  generateBlueprint as apiGenerateBlueprint,
  generateForeshadows as apiGenerateForeshadows,
  generateMemoryChapter as apiGenerateMemoryChapter,
  generateMemoryVolume as apiGenerateMemoryVolume,
  generateOutline as apiGenerateOutline,
  generateBatchOutline as apiGenerateBatchOutline,
  generateProse as apiGenerateProse,
  generateSettings as apiGenerateSettings,
  mapSegment,
  recallMemory as apiRecallMemory,
  saveBookSettings as apiSaveBookSettings,
  saveStyle as apiSaveStyle,
  saveWritingSkills as apiSaveWritingSkills,
  supplementSettings as apiSupplementSettings,
  type ApiPlan,
  type ApiStyle,
  type ArchiveBatchResult,
  type CreateBookInput,
  type FocusItem,
  type MemoryGenResult,
  type MemoryOverview,
  type MemoryRecallHit,
  type MemoryWriteBack,
  type NuewenPlan,
  type ShelfBook,
  type StylePreset,
  type WritingSkills,
} from '@/api/studio'
import type {
  BatchCheck,
  Book,
  Chapter,
  ChapterOutline,
  Discard,
  CharacterRelation,
  Faction,
  Foreshadow,
  GlossaryTerm,
  HistoryEvent,
  InfoGap,
  Item,
  Location,
  OutlineVolume,
  PowerSystem,
  Rule,
  SocietyProfile,
  Segment,
  TimelineRow,
  UsagePoint,
  WorldHabit,
  BibleCharacter,
} from '@/mocks/types'

export type Toast = { id: number; text: string; tone: 'ok' | 'warn' | 'info' }
type CheckEntry = { pass: boolean; findings: Finding[]; fromBatch: boolean }
type Blocked = { number: number; message: string; findings: Finding[] }

export type WriteLogRow = { n: number; title: string; chars: number; status: 'ok' | 'skip' | 'fail'; message?: string }
/** 正在生成的内容：边收边显示，让作者看着文字长出来。 */
export type LiveGen = {
  active: boolean
  kind: '' | 'blueprint' | 'settings' | 'supplement' | 'foreshadow' | 'outline' | 'prose' | 'rewrite' | 'ai-check'
  title: string
  stage: string
  text: string
  /** 模型思考过程（AI 复检时显示，让作者看见它怎么查跨章）。 */
  reason: string
  chapter: number
  startedAt: number
}

export type WriteChapterState = {
  number: number
  stage: 'queued' | 'outline' | 'prose' | 'done' | 'failed' | 'skipped'
  error?: string
  chars?: number
  title?: string
  /** 正文落盘后记忆回写的结果：已回写 / 待补。 */
  memory?: string
}
export type WriteRun = {
  active: boolean
  runId: string
  from: number
  to: number
  current: number
  done: number
  total: number
  error: string
  log: WriteLogRow[]
  pauseAfterCurrent: boolean
  chapters: WriteChapterState[]
  snapshotAt?: string
}

export type WritePanelSource = 'today' | 'workflow' | 'detail' | 'foreshadow' | 'command'

export type WritePanelPreset = {
  source?: WritePanelSource
  from?: number
  to?: number
  numbers?: number[]
  focus?: FocusItem[]
}

type WriteSnapshot = {
  runId: string
  from: number
  to: number
  active: boolean
  current: number
  total: number
  done: number
  error: string
  chapters: WriteChapterState[]
  at: string
}

const emptyWriteRun = (): WriteRun => ({
  active: false,
  runId: '',
  from: 0,
  to: 0,
  current: 0,
  done: 0,
  total: 0,
  error: '',
  log: [],
  pauseAfterCurrent: false,
  chapters: [],
})

const outlineTitle = (outline: Record<string, unknown>): string =>
  typeof outline.title === 'string' ? outline.title : ''
const chapterTitle = (chapter: Record<string, unknown>): string =>
  typeof chapter.title === 'string' ? chapter.title : ''

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

// sessionStorage 同样可能不可用（隐私模式 / 非浏览器测试环境），读写都兜底
function readSS(name: string): string | null {
  try {
    return sessionStorage.getItem(name)
  } catch {
    return null
  }
}
function writeSS(name: string, value: string) {
  try {
    sessionStorage.setItem(name, value)
  } catch {
    /* 快照写不进去只影响刷新恢复 */
  }
}
function removeSS(name: string) {
  try {
    sessionStorage.removeItem(name)
  } catch {
    /* 同上 */
  }
}

const snapshotKey = (dir: string) => `ns.writeRun.${dir}`

function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message
  if (e instanceof Error) return e.message
  return String(e)
}

function nowLabel(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const emptyBook = (): Book => ({
  dir: '',
  title: '正在打开…',
  genre: '',
  platform: '',
  logline: '',
  synopsis: '',
  theme: '',
  targetChapters: 0,
  currentChapter: 0,
  wordsPerChapter: 0,
  minChars: 1800,
  segmentSize: 10,
  tone: '',
  gate: { phase: 'writing', chapter: 1, reason: '', at: '' },
  gates: {},
  updatedAt: '',
  spine: '',
})

export const useStudio = defineStore('studio', () => {
  const shelf = ref<ShelfBook[]>([])
  /** 后端还能连，但书架上一本书都没有：AppShell 据此显示「选题」而不是错误页。 */
  const emptyShelf = ref(false)
  const key = ref<string>(readLS('ns.dir') || '')
  const book = ref<Book>(emptyBook())
  const chapters = ref<Chapter[]>([])
  const segList = ref<Segment[]>([])
  /** 批次细纲按章落盘（ledger/outline 折叠后）；没有段落纲时细纲页按批归组显示。 */
  const outlineRows = ref<ChapterOutline[]>([])
  const foreshadows = ref<Foreshadow[]>([])
  const characters = ref<BibleCharacter[]>([])
  const world = ref<WorldHabit[]>([])
  const rules = ref<Rule[]>([])
  const factions = ref<Faction[]>([])
  const locations = ref<Location[]>([])
  const items = ref<Item[]>([])
  const powerSystem = ref<PowerSystem>({
    name: '', summary: '', levels: [], advancement: '', costs: '', limits: '', balance: '',
  })
  const society = ref<SocietyProfile>({
    politics: '', economy: '', currency: '', law: '', taboo: '',
    customs: '', religion: '', language: '', technology: '',
  })
  const history = ref<HistoryEvent[]>([])
  const glossary = ref<GlossaryTerm[]>([])
  const relations = ref<CharacterRelation[]>([])
  const infoGaps = ref<InfoGap[]>([])
  const outline = ref<OutlineVolume[]>([])
  const timeline = ref<TimelineRow[]>([])
  const usage = ref<UsagePoint[]>([])
  const discarded = ref<Discard[]>([])
  const nuewen = ref<NuewenPlan>({ text: '', at: '', model: '', enabled: false })
  const nuewenBusy = ref(false)

  // 记忆页：整包只读数据 + 生成进度 + 关键词回查
  const memory = ref<MemoryOverview | null>(null)
  const memoryBusy = ref(false)
  const memoryError = ref('')
  const memoryGen = reactive({
    running: false,
    total: 0,
    done: 0,
    current: 0,
    failed: [] as Array<{ chapter: number; error: string }>,
    paused: false,
  })
  const memoryQuery = ref('')
  const recallHits = ref<MemoryRecallHit[]>([])
  const recallBusy = ref(false)
  let memorySeq = 0

  // 开书流水线：大纲+世界观 → 设定 → 伏笔 → 逐章细纲+正文
  const blueprintBusy = ref(false)
  const settingsBusy = ref(false)
  const foreshadowBusy = ref(false)
  const writeRun = ref<WriteRun>(emptyWriteRun())
  const writingBusy = computed(() => writeRun.value.active)

  // 流式生成：同一时刻只显示一路（批量写作时逐章切换）
  const liveGen = reactive<LiveGen>({
    active: false, kind: '', title: '', stage: '', text: '', reason: '', chapter: 0, startedAt: 0,
  })

  function startLive(kind: LiveGen['kind'], title: string, chapter = 0) {
    liveGen.active = true
    liveGen.kind = kind
    liveGen.title = title
    liveGen.chapter = chapter
    liveGen.stage = '准备中'
    liveGen.text = ''
    liveGen.reason = ''
    liveGen.startedAt = Date.now()
    return {
      onStage: (label: string) => { liveGen.stage = label },
      onDelta: (t: string) => { liveGen.text += t },
      onReason: (t: string) => { liveGen.reason += t },
    }
  }

  function endLive() {
    liveGen.active = false
    liveGen.stage = ''
  }

  // 文风 / 写作技能：按书加载，设定页与开写面板共用
  const style = ref<ApiStyle | null>(null)
  const styleSource = ref('platform')
  const stylePresets = ref<StylePreset[]>([])
  const styleBusy = ref(false)
  const skills = ref<WritingSkills | null>(null)
  const skillsAvailable = ref<Record<string, { enabled: boolean; reason?: string }>>({})
  const skillsBusy = ref(false)
  const archiveResults = ref<ArchiveBatchResult['results'] | null>(null)
  const archiveBusy = ref(false)

  // 开写面板（临时态）：关闭即丢弃本批覆盖，不写 localStorage
  const writePanel = reactive({
    open: false,
    source: 'today' as WritePanelSource,
    from: 0,
    to: 0,
    numbers: [] as number[],
    overwrite: false,
    styleConfirmed: false,
    styleOverride: {} as Partial<ApiStyle>,
    skillOverride: {} as Partial<WritingSkills>,
    focus: [] as FocusItem[],
  })

  /** 正文按需拉取：列表页不需要把 100 章全文塞进内存。 */
  const texts = reactive<Record<number, string>>({})
  const textLoading = reactive<Record<number, boolean>>({})
  const checks = reactive<Record<number, CheckEntry>>({})
  /** 完整体检结果（确定性 + 语义分组），面板直接读；``checks`` 只保留旧列表用的摘要。 */
  const checkResults = reactive<Record<number, CheckResult | AiCheckResult>>({})
  const checkLoading = reactive<Record<number, boolean>>({})
  const aiCheckLoading = reactive<Record<number, boolean>>({})
  const batch = ref<BatchCheck | null>(null)
  const batchBusy = ref(false)
  const saving = ref<number | null>(null)
  const blocked = ref<Blocked | null>(null)

  const ready = ref(false)
  const loading = ref(false)
  const error = ref('')
  let loadSeq = 0

  const data = computed(() => ({
    chapters: chapters.value,
    segments: segList.value,
    foreshadows: foreshadows.value,
    characters: characters.value,
    world: world.value,
    rules: rules.value,
    factions: factions.value,
    locations: locations.value,
    items: items.value,
    powerSystem: powerSystem.value,
    society: society.value,
    history: history.value,
    glossary: glossary.value,
    relations: relations.value,
    infoGaps: infoGaps.value,
    outline: outline.value,
    timeline: timeline.value,
    usage: usage.value,
    discarded: discarded.value,
  }))

  const pending = computed(() => chapters.value.filter((c) => !c.approved))
  const approved = computed(() => chapters.value.filter((c) => c.approved))
  const totalChars = computed(() => approved.value.reduce((s, c) => s + c.chars, 0))
  const maxNumber = computed(() => chapters.value.reduce((m, c) => Math.max(m, c.number), 0))
  const nextNumber = computed(() => maxNumber.value + 1)
  const sortedChapters = computed(() => [...chapters.value].sort((a, b) => a.number - b.number))

  const currentSegment = computed(() => {
    const n = book.value.gate.chapter || nextNumber.value
    return segList.value.find((s) => n >= s.from && n <= s.to)
      ?? segList.value.find((s) => n - 1 >= s.from && n - 1 <= s.to)
      ?? segList.value[segList.value.length - 1]
      ?? null
  })

  /** 进度页看"最近一批"：有已写正文章的那一段；正在写但一章没落的段也算。 */
  const recentSegment = computed(() => {
    const written = new Set(chapters.value.map((c) => c.number))
    const hit = segList.value.find((s) => s.plan.stages.some((st) => st.chapters.some((n) => written.has(n))))
    if (hit) return hit
    return currentSegment.value
  })

  const findChapter = (n: number) => chapters.value.find((c) => c.number === n) ?? null

  function clearMemoryState() {
    memorySeq++
    memory.value = null
    memoryBusy.value = false
    memoryError.value = ''
    memoryGen.running = false
    memoryGen.total = 0
    memoryGen.done = 0
    memoryGen.current = 0
    memoryGen.failed = []
    memoryGen.paused = false
    memoryQuery.value = ''
    recallHits.value = []
    recallBusy.value = false
  }

  function clearBookState() {
    clearMemoryState()
    liveGen.active = false
    liveGen.kind = ''
    liveGen.title = ''
    liveGen.stage = ''
    liveGen.text = ''
    liveGen.reason = ''
    liveGen.chapter = 0
    chapters.value = []
    segList.value = []
    outlineRows.value = []
    foreshadows.value = []
    characters.value = []
    world.value = []
    rules.value = []
    factions.value = []
    locations.value = []
    items.value = []
    powerSystem.value = {
      name: '', summary: '', levels: [], advancement: '', costs: '', limits: '', balance: '',
    }
    society.value = {
      politics: '', economy: '', currency: '', law: '', taboo: '',
      customs: '', religion: '', language: '', technology: '',
    }
    history.value = []
    glossary.value = []
    relations.value = []
    infoGaps.value = []
    outline.value = []
    timeline.value = []
    usage.value = []
    discarded.value = []
    nuewen.value = { text: '', at: '', model: '', enabled: false }
    batch.value = null
    blocked.value = null
    for (const k of Object.keys(checks)) delete checks[Number(k)]
    for (const k of Object.keys(checkResults)) delete checkResults[Number(k)]
    for (const k of Object.keys(texts)) delete texts[Number(k)]
    for (const k of Object.keys(textLoading)) delete textLoading[Number(k)]
  }

  async function loadBook(dir: string) {
    const seq = ++loadSeq
    const bundle = await fetchBook(dir)
    if (seq !== loadSeq) return
    clearBookState()
    book.value = bundle.book
    chapters.value = bundle.chapters
    segList.value = bundle.segments
    outlineRows.value = bundle.outlines
    foreshadows.value = bundle.foreshadows
    characters.value = bundle.characters
    world.value = bundle.world
    rules.value = bundle.rules
    factions.value = bundle.factions
    locations.value = bundle.locations
    items.value = bundle.items
    powerSystem.value = bundle.powerSystem
    society.value = bundle.society
    history.value = bundle.history
    glossary.value = bundle.glossary
    relations.value = bundle.relations
    infoGaps.value = bundle.infoGaps
    outline.value = bundle.outline
    timeline.value = bundle.timeline
    usage.value = bundle.usage
    discarded.value = bundle.discarded
    nuewen.value = bundle.nuewen
    // 记忆包不阻塞首屏：失败最多 toast 一次，页面自己显示空态
    void loadMemory()
  }

  /** 只刷新批次细纲；失败保持原样，细纲页自己显示空态，不打断写作。 */
  async function refreshOutlines(): Promise<void> {
    if (!key.value) return
    try {
      outlineRows.value = await fetchOutlines(key.value)
    } catch {
      /* 细纲是展示数据，拉不到就不动 */
    }
  }

  /** 记忆页整包；silent=true 时供生成过程中局部刷新，不闪骨架、不重复 toast。 */
  async function loadMemory(silent = false): Promise<void> {
    if (!key.value) return
    const seq = ++memorySeq
    if (!silent) memoryBusy.value = true
    memoryError.value = ''
    try {
      const data = await fetchMemoryOverview(key.value)
      if (seq !== memorySeq) return
      memory.value = data
    } catch (e) {
      if (seq !== memorySeq) return
      memoryError.value = errorText(e)
      if (!silent) toast(`记忆加载失败：${memoryError.value}`, 'warn')
    } finally {
      if (seq === memorySeq) memoryBusy.value = false
    }
  }

  /** 单章生成：成功后重拉整包，避免手写合并。失败由调用方决定是否继续。 */
  async function generateChapterMemory(
    n: number,
    opts: { force?: boolean; model?: string } = {},
  ): Promise<MemoryGenResult | null> {
    if (!key.value) return null
    try {
      const res = await apiGenerateMemoryChapter(key.value, n, opts)
      if (res.skipped) toast(`第 ${n} 章已有记忆，这次没动`, 'info')
      else toast(`第 ${n} 章记忆已生成`, 'ok')
      await loadMemory(true)
      return res
    } catch (e) {
      toast(`第 ${n} 章记忆生成失败：${errorText(e)}`, 'warn')
      return null
    }
  }

  /** 卷摘要生成：成功后重拉整包。 */
  async function generateVolumeMemory(
    idx: number,
    opts: { force?: boolean; model?: string } = {},
  ): Promise<MemoryGenResult | null> {
    if (!key.value) return null
    try {
      const res = await apiGenerateMemoryVolume(key.value, idx, opts)
      const label = res.title ? `《${res.title}》` : `第 ${idx} 卷`
      toast(`${label}卷摘要已生成`, 'ok')
      await loadMemory(true)
      return res
    } catch (e) {
      toast(`卷摘要生成失败：${errorText(e)}`, 'warn')
      return null
    }
  }

  function pauseMemoryGen() {
    if (!memoryGen.running) return
    memoryGen.paused = true
  }

  function resetMemoryGen() {
    memoryGen.running = false
    memoryGen.total = 0
    memoryGen.done = 0
    memoryGen.current = 0
    memoryGen.failed = []
    memoryGen.paused = false
  }

  /**
   * 逐章补齐记忆：按章号升序，每完成一章重拉整包；暂停在本章完成后生效。
   * from/to 缺省时只补 coverage.missing；指定范围时范围里所有已写章都算目标。
   */
  async function generateMissingMemory(
    opts: { from?: number; to?: number; force?: boolean; alsoVolumes?: boolean; model?: string } = {},
  ): Promise<void> {
    if (memoryGen.running || !key.value) return
    const dir = key.value
    if (!memory.value) await loadMemory(true)
    const overview = memory.value
    if (!overview) return

    const written = overview.chapters.map((c) => c.chapter).sort((a, b) => a - b)
    const hasRange = opts.from != null && opts.to != null
    const from = Number(opts.from)
    const to = Number(opts.to)
    const targets = hasRange
      ? written.filter((n) => n >= from && n <= to)
      : [...overview.coverage.missing].sort((a, b) => a - b)

    if (!targets.length) {
      toast(hasRange ? '这个范围里没有可生成的章' : '没有缺记忆的章', 'info')
      return
    }

    resetMemoryGen()
    memoryGen.running = true
    memoryGen.total = targets.length
    memoryGen.current = targets[0]
    let generated = 0
    const touched: number[] = []

    for (const n of targets) {
      if (memoryGen.paused || key.value !== dir) break
      memoryGen.current = n
      try {
        const res = await apiGenerateMemoryChapter(dir, n, { force: Boolean(opts.force), model: opts.model })
        if (!res.skipped) {
          generated++
          touched.push(n)
        }
        memoryGen.done = generated
      } catch (e) {
        memoryGen.failed.push({ chapter: n, error: errorText(e) })
      }
      try {
        const fresh = await fetchMemoryOverview(dir)
        if (key.value === dir) memory.value = fresh
      } catch {
        /* 局部刷新失败不影响继续生成 */
      }
    }

    let volumeCount = 0
    if (opts.alsoVolumes !== false && touched.length && key.value === dir) {
      const used = new Set(touched)
      for (const v of overview.volumes) {
        // 首次生成时 volume.summary 为空，也要能补；只要求这一卷有本次生成的章。
        const hit = [...used].some((n) => n >= v.from && n <= v.to)
        if (!hit) continue
        try {
          await apiGenerateMemoryVolume(dir, v.volume, { force: true, model: opts.model })
          volumeCount++
        } catch (e) {
          memoryGen.failed.push({ chapter: v.from, error: `卷摘要：${errorText(e)}` })
        }
      }
      if (volumeCount) await loadMemory(true)
    }

    const paused = memoryGen.paused
    memoryGen.running = false
    memoryGen.paused = false

    const failed = memoryGen.failed
    if (paused) {
      toast(`已暂停：这轮生成 ${generated} 章${volumeCount ? `、${volumeCount} 卷摘要` : ''}`, 'info')
    } else if (!generated && failed.length) {
      toast(`这一轮没有生成成功：${failed[0].error}`, 'warn')
    } else if (failed.length) {
      toast(`已生成 ${generated} 章；第 ${failed[0].chapter} 章失败：${failed[0].error}`, 'warn')
    } else {
      toast(`已生成 ${generated} 章记忆${volumeCount ? `、${volumeCount} 卷摘要` : ''}`, 'ok')
    }
  }

  async function recallMemory(q: string): Promise<void> {
    memoryQuery.value = q
    const term = q.trim()
    if (term.length < 2) {
      recallHits.value = []
      return
    }
    if (!key.value) return
    recallBusy.value = true
    try {
      recallHits.value = await apiRecallMemory(key.value, term)
    } catch (e) {
      toast(`回查失败：${errorText(e)}`, 'warn')
    } finally {
      recallBusy.value = false
    }
  }

  function clearRecall() {
    memoryQuery.value = ''
    recallHits.value = []
    recallBusy.value = false
  }

  async function init() {
    if (loading.value || ready.value) return
    loading.value = true
    error.value = ''
    try {
      shelf.value = await fetchShelf()
      if (!shelf.value.length) {
        emptyShelf.value = true
        return
      }
      emptyShelf.value = false
      const saved = readLS('ns.dir')
      const pick = shelf.value.find((b) => b.dir === saved) || shelf.value[0]
      key.value = pick.dir
      writeLS('ns.dir', pick.dir)
      await loadBook(pick.dir)
      recoverWriteRun(pick.dir)
      ready.value = true
    } catch (e) {
      error.value = errorText(e)
    } finally {
      loading.value = false
    }
  }

  async function openBook(dir: string) {
    if (!dir) return
    if (key.value && key.value !== dir) {
      // 换书：只清上一本的运行快照，不动别的书
      removeSS(snapshotKey(key.value))
      writeRun.value = emptyWriteRun()
      style.value = null
      styleSource.value = 'platform'
      skills.value = null
      skillsAvailable.value = {}
      clearMemoryState()
    }
    key.value = dir
    writeLS('ns.dir', dir)
    emptyShelf.value = false
    loading.value = true
    error.value = ''
    try {
      await loadBook(dir)
      recoverWriteRun(dir)
      ready.value = true
    } catch (e) {
      error.value = errorText(e)
    } finally {
      loading.value = false
    }
  }

  /** 从「选题」表单建一本新书，落盘后直接打开。 */
  async function createBook(input: CreateBookInput) {
    const res = await postJSON<{ book: ShelfBook }>('/projects/create', input)
    shelf.value = await fetchShelf()
    emptyShelf.value = false
    error.value = ''
    await openBook(res.book.dir)
    toast(`《${res.book.title}》已建好，下一步：生成大纲和世界观`, 'ok')
    return res.book
  }

  /** 删除整本书：后端 rmtree，永久删除，不进回收站。 */
  async function deleteBook(dir: string) {
    const target = shelf.value.find((b) => b.dir === dir)
    const title = target?.title || dir.split('/').pop() || ''
    const res = await postJSON<{ deleted: string }>('/projects/delete', { dir, confirm: title })
    shelf.value = shelf.value.filter((b) => b.dir !== dir)
    if (key.value !== dir) {
      toast(`《${title}》已永久删除`, 'warn')
      return res.deleted
    }

    const next = shelf.value[0]
    if (next) {
      await openBook(next.dir)
      toast(`《${title}》已永久删除，已切到《${next.title}》`, 'warn')
    } else {
      key.value = ''
      try {
        localStorage.removeItem('ns.dir')
      } catch {
        /* 隐私模式下 localStorage 可能不可用 */
      }
      clearBookState()
      book.value = emptyBook()
      ready.value = false
      emptyShelf.value = true
      error.value = ''
      toast(`《${title}》已永久删除`, 'warn')
    }
    return res.deleted
  }

  async function reload() {
    if (!key.value) return
    loading.value = true
    try {
      await loadBook(key.value)
    } catch (e) {
      error.value = errorText(e)
    } finally {
      loading.value = false
    }
  }

  /** 1) 由梗概生成「大纲 + 世界观」，合在一个动作里，虐文模式自动带公式。 */
  async function generateBlueprint(nuewen = false): Promise<void> {
    if (blueprintBusy.value) return
    blueprintBusy.value = true
    toast('模型正在从故事梗概生成大纲和世界观，可能要 1–4 分钟…', 'info')
    const live = startLive('blueprint', '大纲 + 世界观')
    try {
      const res = await apiGenerateBlueprint(key.value, nuewen, live)
      book.value.outlineText = res.outlineText
      book.value.worldText = res.worldText
      book.value.nuewen = nuewen
      await reload()
      toast(
        res.warning
          ? `大纲+世界观已生成，但要注意：${res.warning}`
          : `大纲+世界观已生成：${res.volumes.length || '若干'} 卷`,
        res.warning ? 'warn' : 'ok',
      )
    } catch (e) {
      toast(`生成失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      blueprintBusy.value = false
      endLive()
    }
  }

  /** 2) 从大纲 + 世界观拆出人物 / 势力 / 地点 / 物品 / 规则 / 文风。 */
  async function generateSettings(): Promise<void> {
    if (settingsBusy.value) return
    settingsBusy.value = true
    toast('模型正在拆人物和设定，可能要 1–3 分钟…', 'info')
    const live = startLive('settings', '人物 · 规则 · 物品 · 地点')
    try {
      const res = await apiGenerateSettings(key.value, live)
      await reload()
      toast(res.summary, 'ok')
    } catch (e) {
      toast(`生成设定失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      settingsBusy.value = false
      endLive()
    }
  }

  /** 写完一批后补设定：只收正文里新出现、bible 里没有的条目，同名/别名跳过。 */
  async function supplementSettings(recent = 8): Promise<number> {
    if (settingsBusy.value) return 0
    settingsBusy.value = true
    toast(`模型正在从最近 ${recent} 章里找新内容，不会重复已有设定…`, 'info')
    const live = startLive('supplement', `从最近 ${recent} 章补设定`)
    try {
      const res = await apiSupplementSettings(key.value, { recent }, live)
      await reload()
      toast(res.summary, res.total ? 'ok' : 'info')
      return res.total
    } catch (e) {
      toast(`补充设定失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      settingsBusy.value = false
      endLive()
    }
  }

  /** 设置页可改的书级参数：字数下限、每段章数。 */
  async function saveBookSettings(patch: { minChars?: number; segmentSize?: number }): Promise<void> {
    if (!key.value) return
    try {
      const res = await apiSaveBookSettings(key.value, patch)
      book.value = { ...book.value, minChars: res.minChars, segmentSize: res.segmentSize }
      toast('已写回 project.json', 'ok')
    } catch (e) {
      toast(`保存失败：${errorText(e)}`, 'warn')
      throw e
    }
  }

  /** 3) 从大纲 + 世界观 + 设定设计整套伏笔（草蛇灰线）。 */
  async function generateForeshadows(): Promise<void> {
    if (foreshadowBusy.value) return
    foreshadowBusy.value = true
    toast('模型正在铺伏笔网，可能要 1–3 分钟…', 'info')
    const live = startLive('foreshadow', '伏笔 · 草蛇灰线')
    try {
      const res = await apiGenerateForeshadows(key.value, live)
      await reload()
      toast(res.summary, 'ok')
    } catch (e) {
      toast(`设计伏笔失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      foreshadowBusy.value = false
      endLive()
    }
  }

  /** ---- 切片 1：文风 / 写作技能 / 开写面板 ---- */

  async function loadStyle(): Promise<ApiStyle | null> {
    if (!key.value) return null
    styleBusy.value = true
    try {
      const res = await fetchStyle(key.value)
      style.value = res.style
      styleSource.value = res.source || 'platform'
      return res.style
    } catch (e) {
      toast(`读取文风失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      styleBusy.value = false
    }
  }

  async function saveStyle(patch: Partial<ApiStyle>): Promise<ApiStyle | null> {
    if (!key.value) return null
    styleBusy.value = true
    try {
      const res = await apiSaveStyle(key.value, patch)
      style.value = res.style
      styleSource.value = 'book'
      toast('文风默认已保存', 'ok')
      return res.style
    } catch (e) {
      toast(`保存文风失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      styleBusy.value = false
    }
  }

  async function loadStylePresets(): Promise<StylePreset[]> {
    styleBusy.value = true
    try {
      const res = await fetchStylePresets()
      stylePresets.value = res.presets
      return res.presets
    } catch (e) {
      toast(`读取文风预设失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      styleBusy.value = false
    }
  }

  async function applyPreset(id: string, overwrite = false): Promise<StylePreset | null> {
    if (!key.value) return null
    styleBusy.value = true
    try {
      const res = await apiApplyStylePreset(key.value, id, overwrite)
      style.value = res.style
      styleSource.value = 'book'
      if (res.preset && !stylePresets.value.some((p) => p.id === res.preset.id)) {
        stylePresets.value = [...stylePresets.value, res.preset]
      }
      toast(`已套用文风预设「${res.preset?.name || id}」`, 'ok')
      return res.preset ?? null
    } catch (e) {
      toast(`套用文风预设失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      styleBusy.value = false
    }
  }

  async function loadWritingSkills(): Promise<WritingSkills | null> {
    if (!key.value) return null
    skillsBusy.value = true
    try {
      const res = await fetchWritingSkills(key.value)
      skills.value = res.skills
      skillsAvailable.value = res.availability ?? {}
      return res.skills
    } catch (e) {
      toast(`读取写作技能失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      skillsBusy.value = false
    }
  }

  async function saveWritingSkills(patch: Partial<WritingSkills>): Promise<WritingSkills | null> {
    if (!key.value) return null
    skillsBusy.value = true
    try {
      const res = await apiSaveWritingSkills(key.value, patch)
      skills.value = res.skills
      toast('技能默认已保存', 'ok')
      return res.skills
    } catch (e) {
      toast(`保存写作技能失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      skillsBusy.value = false
    }
  }

  function hasProse(n: number): boolean {
    const c = findChapter(n)
    return Boolean(c && c.chars > 0)
  }

  function normalizeNumbers(list: number[]): number[] {
    const target = book.value.targetChapters || 0
    const out: number[] = []
    for (const raw of list) {
      const n = Number(raw)
      if (!Number.isInteger(n) || n < 1) continue
      if (target > 0 && n > target) continue
      if (!out.includes(n)) out.push(n)
    }
    return out.sort((a, b) => a - b)
  }

  function openWritePanel(preset: WritePanelPreset = {}) {
    const target = book.value.targetChapters || 0
    let from = Number(preset.from) || nextNumber.value
    if (target > 0) from = Math.min(from, target)
    if (from < 1) from = 1
    const span = Math.max(1, book.value.segmentSize || 10) - 1
    let to = Number(preset.to) || (target > 0 ? Math.min(target, from + span) : from + span)
    if (target > 0) to = Math.min(to, target)
    if (to < from) to = from

    const numbers = preset.numbers?.length
      ? normalizeNumbers(preset.numbers)
      : Array.from({ length: to - from + 1 }, (_, i) => from + i).filter((n) => !hasProse(n))

    writePanel.source = preset.source ?? 'today'
    writePanel.from = from
    writePanel.to = to
    writePanel.numbers = numbers
    writePanel.overwrite = false
    writePanel.styleConfirmed = false
    writePanel.styleOverride = {}
    writePanel.skillOverride = {}
    writePanel.focus = preset.focus ? [...preset.focus] : []
    writePanel.open = true

    // 文风 / 预设 / 技能按需并行拉取；首屏不被网络阻塞
    const jobs: Array<Promise<unknown>> = []
    if (!style.value) jobs.push(loadStyle())
    if (!stylePresets.value.length) jobs.push(loadStylePresets())
    if (!skills.value) jobs.push(loadWritingSkills())
    if (jobs.length) void Promise.allSettled(jobs)
  }

  function closeWritePanel() {
    writePanel.open = false
  }

  function toggleChapter(n: number) {
    if (!Number.isInteger(n) || n < 1) return
    const i = writePanel.numbers.indexOf(n)
    if (i >= 0) writePanel.numbers.splice(i, 1)
    else writePanel.numbers = [...writePanel.numbers, n].sort((a, b) => a - b)
  }

  function selectAllPending() {
    writePanel.numbers = chapters.value
      .filter((c) => !c.approved)
      .map((c) => c.number)
      .sort((a, b) => a - b)
  }

  function clearSelection() {
    writePanel.numbers = []
  }

  function makeRunId(): string {
    const d = new Date()
    const pad = (x: number) => String(x).padStart(2, '0')
    const day = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`
    const rand = Math.random().toString(36).slice(2, 6).padEnd(4, '0')
    return `wr-${day}-${rand}`
  }

  function setChapterRow(n: number, patch: Partial<WriteChapterState> & { stage: WriteChapterState['stage'] }) {
    const row = writeRun.value.chapters.find((c) => c.number === n)
    if (row) Object.assign(row, patch)
  }

  function writeSnapshot(status: 'running' | 'done' | 'failed' | 'paused') {
    if (!key.value) return
    const run = writeRun.value
    const snap: WriteSnapshot = {
      runId: run.runId,
      from: run.from,
      to: run.to,
      active: status === 'running',
      current: run.current,
      total: run.total,
      done: run.done,
      error: run.error,
      chapters: run.chapters.map((c) => ({ ...c })),
      at: new Date().toISOString(),
    }
    writeSS(snapshotKey(key.value), JSON.stringify(snap))
  }

  /** 刷新后：只把上次未完成的运行恢复成「中断」提示，绝不自动重发。 */
  function recoverWriteRun(dir: string) {
    if (!dir) return
    const raw = readSS(snapshotKey(dir))
    if (!raw) return
    let snap: Partial<WriteSnapshot> | null = null
    try {
      snap = JSON.parse(raw) as Partial<WriteSnapshot>
    } catch {
      return
    }
    if (!snap || !snap.active || !Array.isArray(snap.chapters)) return
    if (writeRun.value.active) return
    const rows = snap.chapters as WriteChapterState[]
    const running = rows.find((c) => c.stage === 'outline' || c.stage === 'prose')
      ?? rows.find((c) => c.stage === 'failed')
    const n = running?.number ?? (Number(snap.current) || 0)
    writeRun.value = {
      active: false,
      runId: String(snap.runId || ''),
      from: Number(snap.from) || 0,
      to: Number(snap.to) || 0,
      current: 0,
      done: rows.filter((c) => c.stage === 'done' || c.stage === 'skipped').length,
      total: rows.length,
      error: `上次写作${n ? `在第 ${n} 章` : ''}中断；可能已落盘，检查后再重试。`,
      log: rows
        .filter((c) => c.stage === 'done')
        .map((c) => ({ n: c.number, title: c.title || '', chars: c.chars || 0, status: 'ok' as const })),
      pauseAfterCurrent: false,
      chapters: rows,
      snapshotAt: String(snap.at || ''),
    }
  }

  /** 记忆回写只影响记忆页；失败不算这一章失败。 */
  function memoryNote(m?: MemoryWriteBack): string {
    if (!m) return ''
    if (m.skipped) return ''
    if (m.error) return '记忆待补'
    return m.volume ? '记忆与卷摘要已回写' : '记忆已回写'
  }

  /** 4) 分批生成：本批先一次出细纲（每章一条节拍），再逐章照细纲写正文；一章失败就停，方便作者查看原因。 */
  async function startWriteBatch(): Promise<WriteRun> {
    if (writeRun.value.active) return writeRun.value
    if (!writePanel.numbers.length) {
      toast('先选至少一章', 'warn')
      return writeRun.value
    }
    if (!writePanel.styleConfirmed) {
      toast('开写前先确认这一批的文风', 'warn')
      return writeRun.value
    }
    const numbers = normalizeNumbers(writePanel.numbers)
    if (!numbers.length) {
      toast('先选至少一章', 'warn')
      return writeRun.value
    }

    const runId = makeRunId()
    const from = numbers[0]
    const to = numbers[numbers.length - 1]
    writeRun.value = {
      active: true,
      runId,
      from,
      to,
      current: from,
      done: 0,
      total: numbers.length,
      error: '',
      log: [],
      pauseAfterCurrent: false,
      chapters: numbers.map((number) => ({ number, stage: 'queued' as const })),
    }
    writePanel.numbers = numbers
    writeSnapshot('running')

    let status: 'done' | 'failed' | 'paused' = 'done'
    // 一批共用一条细纲：整批一次生成，每章拿回自己那段节拍；正文仍然一章一章写。
    const outlineByChapter = new Map<number, Record<string, unknown>>()
    const pending = numbers.filter((n) => {
      const c = findChapter(n)
      return !(c && c.chars > 0 && !writePanel.overwrite)
    })
    if (pending.length) {
      toast(`先出第 ${from}–${to} 章的细纲，再按细纲逐章写正文，别关页面…`, 'info')
    }
    try {
      if (pending.length) {
        try {
          const batch = await apiGenerateBatchOutline(
            key.value,
            from,
            to,
            {
              force: false,
              styleOverride: writePanel.styleOverride,
              skills: writePanel.skillOverride,
              focus: writePanel.focus,
              runId,
            },
            startLive('outline', `第 ${from}–${to} 章 · 细纲`, from),
          )
          for (const outline of batch.outlines || []) {
            const n = Number(outline.chapter)
            if (Number.isFinite(n)) outlineByChapter.set(n, outline)
          }
          void refreshOutlines()
        } catch (e) {
          const message = errorText(e)
          writeRun.value.error = `第 ${from}–${to} 章细纲失败：${message}`
          writeRun.value.log = [
            ...writeRun.value.log,
            { n: from, title: '', chars: 0, status: 'fail', message },
          ]
          for (const n of pending) setChapterRow(n, { stage: 'failed', error: message })
          status = 'failed'
        }
      }

      if (status !== 'failed') {
        for (const n of numbers) {
          if (writeRun.value.pauseAfterCurrent && writeRun.value.done > 0) {
            status = 'paused'
            break
          }
          writeRun.value.current = n
          const existing = findChapter(n)
          if (existing && existing.chars > 0 && !writePanel.overwrite) {
            setChapterRow(n, { stage: 'skipped', title: existing.title, chars: existing.chars })
            writeRun.value.done += 1
            writeRun.value.log = [
              ...writeRun.value.log,
              { n, title: existing.title, chars: existing.chars, status: 'skip', message: '已有正文，跳过' },
            ]
            writeSnapshot('running')
            continue
          }

          try {
            const title = outlineTitle(outlineByChapter.get(n) || {})
            setChapterRow(n, { stage: 'prose', title })
            writeSnapshot('running')
            const proseRes = await apiGenerateProse(
              key.value,
              n,
              {
                overwrite: writePanel.overwrite,
                styleOverride: writePanel.styleOverride,
                skills: writePanel.skillOverride,
                focus: writePanel.focus,
                runId,
              },
              startLive('prose', `第 ${n} 章 · 正文`, n),
            )
            const doneTitle = chapterTitle(proseRes.chapter) || title
            setChapterRow(n, {
              stage: 'done', title: doneTitle, chars: proseRes.chars, error: undefined,
              memory: memoryNote(proseRes.memory),
            })
            writeRun.value.done += 1
            writeRun.value.log = [
              ...writeRun.value.log,
              { n, title: doneTitle, chars: proseRes.chars, status: 'ok' },
            ]
            writeSnapshot('running')
          } catch (e) {
            const message = errorText(e)
            setChapterRow(n, { stage: 'failed', error: message })
            writeRun.value.error = `第 ${n} 章失败：${message}`
            writeRun.value.log = [
              ...writeRun.value.log,
              { n, title: '', chars: 0, status: 'fail', message },
            ]
            status = 'failed'
            break
          }
        }
      }
    } finally {
      writeRun.value.active = false
      writeRun.value.current = 0
      writeSnapshot(status)
      await reload()
      endLive()
    }

    const run = writeRun.value
    const ok = run.log.filter((r) => r.status === 'ok').length
    const skipped = run.log.filter((r) => r.status === 'skip').length
    // 记忆是正文的派生数据：写完就拉一次，记忆页不用手动刷新。
    if (ok) void loadMemory(true)
    const needMemory = run.chapters.filter((c) => c.memory === '记忆待补').length
    const memTip = needMemory ? ` 有 ${needMemory} 章记忆没回写，可在「记忆」页补齐。` : ''
    if (run.error) toast(run.error, 'warn')
    else if (status === 'paused') toast(`已暂停：本批已完成 ${ok} 章，剩余下次再写。${memTip}`, 'info')
    else toast(`写作完成：新写 ${ok} 章${skipped ? `，跳过 ${skipped} 章` : ''}。到「进度」页逐章确认。${memTip}`, needMemory ? 'info' : 'ok')
    return run
  }

  /** 只重试失败的那一章；不自动继续后面的章。 */
  async function retryChapter(n: number): Promise<WriteRun> {
    if (writeRun.value.active) return writeRun.value
    const row = writeRun.value.chapters.find((c) => c.number === n)
    if (!row) {
      toast(`第 ${n} 章不在本批中`, 'warn')
      return writeRun.value
    }
    if (row.stage === 'done') return writeRun.value

    const runId = writeRun.value.runId || makeRunId()
    writeRun.value.runId = runId
    writeRun.value.active = true
    writeRun.value.current = n
    writeRun.value.error = ''
    writeSnapshot('running')

    let status: 'done' | 'failed' = 'done'
    let title = row.title || ''
    try {
      setChapterRow(n, { stage: 'outline', error: undefined })
      writeSnapshot('running')
      const outlineRes = await apiGenerateOutline(
        key.value,
        n,
        {
          force: false,
          styleOverride: writePanel.styleOverride,
          skills: writePanel.skillOverride,
          focus: writePanel.focus,
          runId,
        },
        startLive('outline', `第 ${n} 章 · 细纲`, n),
      )
      title = outlineTitle(outlineRes.outline) || title
      void refreshOutlines()

      setChapterRow(n, { stage: 'prose', title })
      writeSnapshot('running')
      const proseRes = await apiGenerateProse(
        key.value,
        n,
        {
          overwrite: writePanel.overwrite,
          styleOverride: writePanel.styleOverride,
          skills: writePanel.skillOverride,
          focus: writePanel.focus,
          runId,
        },
        startLive('prose', `第 ${n} 章 · 正文`, n),
      )
      const doneTitle = chapterTitle(proseRes.chapter) || title
      setChapterRow(n, {
        stage: 'done', title: doneTitle, chars: proseRes.chars, error: undefined,
        memory: memoryNote(proseRes.memory),
      })
      writeRun.value.done = writeRun.value.chapters.filter(
        (c) => c.stage === 'done' || c.stage === 'skipped',
      ).length
      writeRun.value.log = [
        ...writeRun.value.log,
        { n, title: doneTitle, chars: proseRes.chars, status: 'ok' },
      ]
      toast(`第 ${n} 章重试成功`, 'ok')
    } catch (e) {
      const message = errorText(e)
      setChapterRow(n, { stage: 'failed', error: message })
      writeRun.value.error = `第 ${n} 章失败：${message}`
      writeRun.value.log = [
        ...writeRun.value.log,
        { n, title: '', chars: 0, status: 'fail', message },
      ]
      status = 'failed'
      toast(writeRun.value.error, 'warn')
    } finally {
      writeRun.value.active = false
      writeRun.value.current = 0
      writeSnapshot(status)
      await reload()
      endLive()
    }
    return writeRun.value
  }

  function pauseAfterCurrent() {
    writeRun.value.pauseAfterCurrent = true
    toast('本章完成后暂停', 'info')
  }

  async function archiveSelected(numbers: number[], force = false): Promise<ArchiveBatchResult | null> {
    const list = normalizeNumbers(numbers)
    if (!list.length) {
      toast('先选至少一章', 'warn')
      return null
    }
    archiveBusy.value = true
    try {
      const res = await apiArchiveBatch(key.value, list, force)
      archiveResults.value = res.results
      for (const r of res.results) {
        if (!r.ok) continue
        const c = findChapter(r.number)
        if (c) c.approved = true
      }
      const ok = res.results.filter((r) => r.ok).length
      const failed = res.results.filter((r) => !r.ok)
      if (failed.length) {
        toast(`已存档 ${ok} 章；${failed.length} 章有硬伤或不存在，等你决定`, 'warn')
      } else {
        toast(`已存档 ${ok} 章`, 'ok')
      }
      book.value.currentChapter = chapters.value.reduce(
        (m, c) => Math.max(m, c.number),
        book.value.currentChapter,
      )
      recalcSegments()
      await reload()
      return res
    } catch (e) {
      toast(`批量存档失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      archiveBusy.value = false
    }
  }

  /** 旧入口：连续范围写作。内部构造一次面板选择，行为与返回保持兼容。 */
  async function writeChapters(from: number, to: number, options: { overwrite?: boolean } = {}) {
    const start = Number(from) || 1
    const end = Number(to) || start
    if (writeRun.value.active) return writeRun.value
    if (end < start) {
      toast('结束章不能早于起始章', 'warn')
      return writeRun.value
    }
    writePanel.source = 'workflow'
    writePanel.from = start
    writePanel.to = end
    writePanel.numbers = normalizeNumbers(
      Array.from({ length: end - start + 1 }, (_, i) => start + i),
    )
    writePanel.overwrite = Boolean(options.overwrite)
    // 旧页面没有文风确认 UI；保留旧行为，直接按书默认开写
    writePanel.styleConfirmed = true
    return startWriteBatch()
  }

  const toasts = ref<Toast[]>([])
  let toastId = 0
  function toast(text: string, tone: Toast['tone'] = 'info') {
    const id = ++toastId
    toasts.value.push({ id, text, tone })
    setTimeout(() => (toasts.value = toasts.value.filter((t) => t.id !== id)), 3600)
  }

  function applyGate(gate: Partial<Book['gate']> | undefined) {
    if (!gate) return
    book.value.gate = {
      phase: gate.phase || 'writing',
      chapter: Number(gate.chapter) || book.value.gate.chapter,
      reason: gate.reason || book.value.gate.reason,
      at: gate.at || nowLabel(),
    }
  }

  function recalcSegments() {
    for (const s of segList.value) {
      const written = chapters.value.some((c) => c.number >= s.from && c.number <= s.to && c.chars > 0)
      const done = chapters.value.some((c) => c.number === s.to && c.approved)
      s.status = done ? 'done' : written ? 'writing' : 'planned'
    }
  }

  async function archive(n: number, force = false) {
    saving.value = n
    blocked.value = null
    try {
      const res = await postJSON<{ approved: number; nextChapter: number; gate: Book['gate'] }>(
        `/projects/chapters/${n}/archive`,
        { force },
        { dir: key.value },
      )
      const c = findChapter(n)
      if (c) c.approved = true
      applyGate(res.gate)
      book.value.currentChapter = Math.max(book.value.currentChapter, n)
      recalcSegments()
      toast(`第 ${n} 章已确认存档`, 'ok')
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.findings.length) {
        blocked.value = { number: n, message: e.message, findings: e.findings }
      } else {
        toast(errorText(e), 'warn')
      }
    } finally {
      saving.value = null
    }
  }

  /** 待确认章自动存档：默认关闭；开启后仍然逐章过体检，硬伤会停下来问作者。 */
  async function autoArchivePending() {
    if (!pending.value.length) return
    const list = [...pending.value]
    let done = 0
    for (const c of list) {
      if (blocked.value) break
      await archive(c.number)
      if (!blocked.value) done += 1
    }
    if (done) toast(`已自动存档 ${done} 章，剩下 ${list.length - done} 章有硬伤，等你确认`, 'ok')
  }

  async function reject(n: number, reason = '') {
    saving.value = n
    try {
      await postJSON(`/projects/chapters/${n}/reject`, { reason }, { dir: key.value })
      chapters.value = chapters.value.filter((c) => c.number !== n)
      book.value.currentChapter = chapters.value.reduce((m, c) => Math.max(m, c.number), 0)
      applyGate({ phase: 'writing', chapter: n, reason: `第${n}章已退回，可重写这一章` })
      recalcSegments()
      await refreshDiscarded()
      toast(`第 ${n} 章已退回，旧稿存进「废章」`, 'warn')
    } catch (e) {
      toast(errorText(e), 'warn')
    } finally {
      saving.value = null
    }
  }

  /** 让模型按体检问题改写本章；后端在成功后才会把旧稿挪进废章。 */
  async function rewrite(
    n: number, note = '', skills?: string[], instruction = '', extraFindings?: Finding[],
  ) {
    saving.value = n
    // 体检/复检出的问题要进提示词：优先用调用方给的，其次用当前页面上这一章的结果。
    const known = extraFindings ?? checkResults[n]?.findings ?? checks[n]?.findings ?? []
    const findings = known
      .filter((f) => f.severity === 'high' || f.severity === 'mid')
      .slice(0, 16)
      .map((f) => ({
        severity: f.severity,
        code: f.code,
        message: f.message,
        hint: f.hint ?? '',
        source: typeof f.source === 'string' ? f.source : '',
      }))
    toast(`第 ${n} 章正在按技能改写，可能要 1–3 分钟…`, 'info')
    try {
      const res = await fetchRewrite(
        key.value,
        n,
        { reason: note, skills, instruction, findings },
        startLive('rewrite', `第 ${n} 章 · 按技能改写`, n),
      )
      texts[n] = res.text
      const c = findChapter(n)
      if (c) {
        c.approved = false
        c.chars = res.chars
        c.chapterVerdict = res.check.pass ? 'pass' : 'needs_fix'
        c.fixReasons = res.check.findings.filter((f) => f.severity === 'high').map((f) => f.message)
        if (res.check.endHook) c.endHook = res.check.endHook
        if (typeof res.check.dialogueRatio === 'number') c.dialogueRatio = res.check.dialogueRatio
        c.searchText = `${c.title} ${c.summary}`
      }
      checkResults[n] = res.check
      checks[n] = { pass: res.check.pass, findings: res.check.findings, fromBatch: false }
      await refreshDiscarded()
      toast(
        `第 ${n} 章已按 ${res.skills.length} 个技能改写，停在待确认；AI 痕迹 ${res.aiTellsBefore.total} → ${res.aiTellsAfter.total}`,
        'ok',
      )
      return res
    } catch (e) {
      toast(`改写失败，旧稿没动：${errorText(e)}`, 'warn')
      throw e
    } finally {
      saving.value = null
      endLive()
    }
  }

  async function check(n: number) {
    checkLoading[n] = true
    try {
      const res = await fetchChapterCheck(key.value, n)
      checkResults[n] = res
      checks[n] = { pass: res.pass, findings: res.findings, fromBatch: false }
      toast(res.pass ? `第 ${n} 章体检通过` : `第 ${n} 章有硬伤，见章下问题`, res.pass ? 'ok' : 'warn')
      return res
    } catch (e) {
      toast(errorText(e), 'warn')
      throw e
    } finally {
      checkLoading[n] = false
    }
  }

  async function aiCheck(n: number) {
    aiCheckLoading[n] = true
    toast(`第 ${n} 章 AI 复检中：对照前情、上一章结尾和本章细纲，可能要 1–2 分钟…`, 'info')
    try {
      const res = await fetchAiCheckStream(
        key.value, n, undefined,
        startLive('ai-check', `第 ${n} 章 · AI 复检`, n),
      )
      checkResults[n] = res
      checks[n] = { pass: res.pass, findings: res.findings, fromBatch: false }
      toast(res.pass ? `第 ${n} 章 AI 复检通过` : `第 ${n} 章 AI 复检发现问题，见章下`, res.pass ? 'ok' : 'warn')
      return res
    } catch (e) {
      toast(`AI 复检失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      endLive()
      aiCheckLoading[n] = false
    }
  }

  async function runBatchCheck(from?: number, to?: number) {
    const seg = currentSegment.value
    batchBusy.value = true
    try {
      const res = await postJSON<BatchCheck>(
        '/projects/check-batch',
        { from: from ?? seg?.from, to: to ?? seg?.to },
        { dir: key.value },
      )
      batch.value = res
      for (const row of res.chapters) {
        checks[row.number] = { pass: row.pass, findings: row.findings, fromBatch: true }
      }
      const todo = res.chapters.filter((c) => !c.pass).map((c) => c.number)
      toast(
        `按批体检第 ${res.from}–${res.to} 章：${todo.length ? `第 ${todo.join('、')} 章要改` : '没有硬伤'}` +
          `${res.blocking.length ? `；${res.blocking.length} 条跨章提醒` : ''}`,
        todo.length ? 'warn' : 'ok',
      )
    } catch (e) {
      toast(errorText(e), 'warn')
    } finally {
      batchBusy.value = false
    }
  }

  async function loadText(n: number): Promise<string | null> {
    if (texts[n] != null) return texts[n]
    if (textLoading[n]) return null
    textLoading[n] = true
    try {
      const res = await getJSON<{ text: string }>(`/projects/chapters/${n}`, { dir: key.value })
      texts[n] = res.text
      return res.text
    } catch (e) {
      toast(`读第 ${n} 章正文失败：${errorText(e)}`, 'warn')
      return null
    } finally {
      textLoading[n] = false
    }
  }

  /** 按「最 X → 最非 X」文案生成人物反转表 + 分章骨架，落 ledger/nuewen.jsonl。 */
  async function generateNuewen(instruction = ''): Promise<NuewenPlan> {
    nuewenBusy.value = true
    toast('模型正在按虐文公式搭骨架，可能要 1–3 分钟…', 'info')
    try {
      const res = await postJSON<NuewenPlan>(
        '/projects/nuewen/plan',
        { instruction },
        { dir: key.value },
      )
      nuewen.value = res
      toast('虐文骨架已生成并落账', 'ok')
      return res
    } catch (e) {
      toast(`生成失败：${errorText(e)}`, 'warn')
      throw e
    } finally {
      nuewenBusy.value = false
    }
  }

  const nuewenEnabled = computed(() => nuewen.value.enabled)

  async function setNuewenMode(enabled: boolean) {
    const res = await postJSON<{ enabled: boolean }>(
      '/projects/nuewen/mode',
      { enabled },
      { dir: key.value },
    )
    nuewen.value = { ...nuewen.value, enabled: res.enabled }
    toast(res.enabled ? '已开启：改写正文时套用虐文原则' : '已关闭：改写正文不再套用虐文原则', 'ok')
  }

  async function planSegment(from: number, to: number): Promise<Segment> {
    const plan = await postJSON<ApiPlan>('/projects/segments/plan', { from, to }, { dir: key.value })
    return mapSegment({ from: plan.from, to: plan.to, plan, at: nowLabel() }, chapters.value)
  }

  async function saveSegmentPlan(from: number, to: number): Promise<Segment> {
    const res = await postJSON<{ segment: ApiPlan }>('/projects/segments', { from, to }, { dir: key.value })
    const seg = mapSegment({ from: res.segment.from, to: res.segment.to, plan: res.segment, at: nowLabel() }, chapters.value)
    segList.value = [...segList.value.filter((s) => !(s.from === seg.from && s.to === seg.to)), seg]
      .sort((a, b) => a.from - b.from)
    toast(`第 ${seg.from}–${seg.to} 章段落纲已落账`, 'ok')
    return seg
  }

  async function deleteSegment(from: number, to: number) {
    try {
      await postJSON('/projects/segments/delete', { from, to }, { dir: key.value })
      segList.value = segList.value.filter((s) => !(s.from === from && s.to === to))
      toast(`已删掉第 ${from}–${to} 章段落纲（已写正文不受影响）`, 'warn')
    } catch (e) {
      toast(errorText(e), 'warn')
      throw e
    }
  }

  async function addForeshadow(input: {
    name: string
    kind: Foreshadow['kind']
    plantedChapter: number
    dueChapter?: number | null
    revealWho?: string
    hint?: string
  }) {
    const res = await postJSON<{ row: Record<string, unknown> }>('/projects/foreshadow', input, { dir: key.value })
    foreshadows.value = await fetchForeshadows(key.value, book.value.currentChapter)
    toast(`伏笔「${String(res.row.name || input.name)}」已落账（ledger/foreshadow.jsonl）`, 'ok')
    return res.row
  }

  async function payoffForeshadow(id: string, chapter: number) {
    await postJSON('/projects/foreshadow/payoff', { id, chapter }, { dir: key.value })
    foreshadows.value = await fetchForeshadows(key.value, book.value.currentChapter)
    toast(`「${foreshadows.value.find((f) => f.id === id)?.name || id}」已标记为第 ${chapter} 章回收`, 'ok')
  }

  /** 明确放弃一条伏笔：只追加一条放弃事件，不再被体检追。 */
  async function abandonForeshadow(id: string, note = '') {
    const name = foreshadows.value.find((f) => f.id === id)?.name || id
    await postJSON('/projects/foreshadow/abandon', { id, note }, { dir: key.value })
    foreshadows.value = await fetchForeshadows(key.value, book.value.currentChapter)
    toast(`「${name}」已放弃，体检不再追这条线`, 'ok')
  }

  async function refreshDiscarded() {
    try {
      const res = await getJSON<{ rows: Discard[] }>('/projects/discarded', { dir: key.value })
      discarded.value = res.rows
    } catch {
      /* 废章刷新失败不阻塞主流程 */
    }
  }

  async function restoreDiscard(draftFile: string, number = 0, title = '') {
    try {
      await postJSON('/projects/discarded/restore', { draftFile, number, title }, { dir: key.value })
      await reload()
      toast('废章已恢复到正文，等你在进度页确认', 'ok')
    } catch (e) {
      toast(`恢复失败：${errorText(e)}`, 'warn')
      throw e
    }
  }

  async function purgeDiscard(draftFile: string) {
    try {
      await postJSON('/projects/discarded/purge', { draftFile }, { dir: key.value })
      await refreshDiscarded()
      toast('废章已永久删除', 'warn')
    } catch (e) {
      toast(`删除失败：${errorText(e)}`, 'warn')
      throw e
    }
  }

  const wordsToday = computed(() => {
    const today = new Date().toISOString().slice(0, 10)
    return chapters.value
      .filter((c) => c.committedAt?.slice(0, 10) === today)
      .reduce((s, c) => s + c.chars, 0)
  })

  const streak = computed(() => {
    const days = new Set(
      chapters.value.map((c) => c.committedAt?.slice(0, 10)).filter((x): x is string => Boolean(x)),
    )
    let n = 0
    const d = new Date()
    for (;;) {
      const key = d.toISOString().slice(0, 10)
      if (!days.has(key)) break
      n += 1
      d.setDate(d.getDate() - 1)
    }
    return n
  })

  return {
    shelf,
    emptyShelf,
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
    checkResults,
    checkLoading,
    aiCheckLoading,
    batch,
    batchBusy,
    saving,
    blocked,
    texts,
    textLoading,
    toasts,
    foreshadows,
    characters,
    relations,
    infoGaps,
    world,
    rules,
    factions,
    locations,
    items,
    outline,
    outlineRows,
    timeline,
    usage,
    discarded,
    ready,
    loading,
    error,
    wordsToday,
    streak,
    toast,
    init,
    openBook,
    createBook,
    deleteBook,
    reload,
    findChapter,
    autoArchivePending,
    archive,
    reject,
    rewrite,
    check,
    aiCheck,
    runBatchCheck,
    loadText,
    nuewen,
    nuewenBusy,
    memory,
    memoryBusy,
    memoryError,
    memoryGen,
    memoryQuery,
    recallHits,
    recallBusy,
    loadMemory,
    refreshOutlines,
    generateChapterMemory,
    generateVolumeMemory,
    generateMissingMemory,
    pauseMemoryGen,
    resetMemoryGen,
    recallMemory,
    clearRecall,
    nuewenEnabled,
    generateNuewen,
    setNuewenMode,
    blueprintBusy,
    settingsBusy,
    foreshadowBusy,
    writingBusy,
    writeRun,
    liveGen,
    style,
    styleSource,
    stylePresets,
    styleBusy,
    skills,
    skillsAvailable,
    skillsBusy,
    archiveResults,
    archiveBusy,
    writePanel,
    loadStyle,
    saveStyle,
    loadStylePresets,
    applyPreset,
    loadWritingSkills,
    saveWritingSkills,
    openWritePanel,
    closeWritePanel,
    toggleChapter,
    selectAllPending,
    clearSelection,
    startWriteBatch,
    retryChapter,
    pauseAfterCurrent,
    archiveSelected,
    recoverWriteRun,
    generateBlueprint,
    generateSettings,
    supplementSettings,
    saveBookSettings,
    generateForeshadows,
    writeChapters,
    planSegment,
    saveSegmentPlan,
    deleteSegment,
    addForeshadow,
    payoffForeshadow,
    abandonForeshadow,
    refreshDiscarded,
    restoreDiscard,
    purgeDiscard,
  }
})

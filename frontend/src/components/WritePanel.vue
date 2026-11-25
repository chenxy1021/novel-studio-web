<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Card, Input, Modal, Tag } from '@/design'
import { fetchPlatforms, type ApiStyle, type PlatformOption, type WritingSkills } from '@/api/studio'
import { fetchReferences, previewReferences, type ReferencePack } from '@/api/references'
import { useStudio, type WriteChapterState } from '@/stores/studio'
import StyleFields from './StyleFields.vue'
import WritingSkillPicker from './WritingSkillPicker.vue'
import GenStream from './GenStream.vue'

const studio = useStudio()
const router = useRouter()
const panel = studio.writePanel

const DEFAULT_SKILLS: WritingSkills = {
  deai: true,
  dialogue: true,
  scene: true,
  hook: true,
  continuity: true,
  platform: true,
  nuewen: false,
  styleSamples: true,
}

const mode = ref<'prep' | 'running' | 'done'>('prep')
const openStyleFields = ref(false)
const openSkills = ref(false)
const targetWords = ref(studio.book.wordsPerChapter || 0)
const platforms = ref<PlatformOption[]>([])
const seenRunId = ref('')

const run = computed(() => studio.writeRun)
const isRunning = computed(() => run.value.active)
const live = computed(() => studio.liveGen)
/** 批量写作时只跟当前这一章的细纲 / 正文，别的生成不在这里抢位置。 */
const liveWriting = computed(
  () => live.value.active && (live.value.kind === 'outline' || live.value.kind === 'prose'),
)
/** 写完整批后的「补进设定」也在面板里给实况，不然只剩一个转圈按钮。 */
const liveSupplement = computed(
  () => live.value.active && live.value.kind === 'supplement',
)

const modalTitle = computed(() => (isRunning.value ? '正在写作' : '开写'))
const modalDesc = computed(() =>
  isRunning.value
    ? '先给本批出一份细纲，再按细纲逐章写正文；失败会停在本章，已完成的章不受影响。'
    : '选本批要写的章，确认文风和参考资料，然后按本批细纲逐章写正文。',
)

onMounted(async () => {
  try {
    platforms.value = await fetchPlatforms()
  } catch {
    /* 平台列表拿不到时只显示书名里的平台名 */
  }
  targetWords.value = studio.book.wordsPerChapter || targetWords.value
})

watch(
  () => panel.open,
  (open) => {
    if (!open) return
    targetWords.value = studio.book.wordsPerChapter || targetWords.value
    if (run.value.active) {
      mode.value = 'running'
    } else if (
      run.value.runId &&
      run.value.runId !== seenRunId.value &&
      (run.value.error || run.value.log.length)
    ) {
      mode.value = 'done'
    } else {
      mode.value = 'prep'
    }
  },
)

watch(
  () => run.value.active,
  (active) => {
    if (!panel.open) return
    if (active) mode.value = 'running'
    else if (mode.value === 'running') mode.value = 'done'
  },
)

/* ---------- ① 章节选择 ---------- */

const fromModel = computed({
  get: () => String(panel.from || ''),
  set: (v: string) => {
    panel.from = Math.max(1, Number(v) || 1)
  },
})
const toModel = computed({
  get: () => String(panel.to || ''),
  set: (v: string) => {
    panel.to = Math.max(1, Number(v) || Number(fromModel.value) || 1)
  },
})

const rangeError = computed(() => (panel.to < panel.from ? '结束章不能早于起始章' : ''))

const rangeNumbers = computed<number[]>(() => {
  const from = Math.max(1, Number(panel.from) || 1)
  const to = Math.max(from, Number(panel.to) || from)
  const set = new Set<number>()
  for (let n = from; n <= to; n += 1) set.add(n)
  for (const n of panel.numbers) set.add(n)
  return [...set].sort((a, b) => a - b)
})

function chapterOf(n: number) {
  return studio.findChapter(n)
}
function hasProse(n: number): boolean {
  const c = chapterOf(n)
  return Boolean(c && c.chars > 0)
}
function selectable(n: number): boolean {
  return !hasProse(n) || panel.overwrite
}
function checked(n: number): boolean {
  return panel.numbers.includes(n)
}
function toggleChapter(n: number) {
  if (!selectable(n)) return
  studio.toggleChapter(n)
}

type ChapterStatus = { label: string; tone: 'neutral' | 'gold' | 'ok' }
function statusOf(n: number): ChapterStatus {
  const c = chapterOf(n)
  if (!c) return { label: '未写', tone: 'neutral' }
  if (c.approved) return { label: '已存档', tone: 'ok' }
  return { label: '待确认', tone: 'gold' }
}

const pad3 = (n: number) => String(n).padStart(3, '0')

function selectRange() {
  panel.numbers = rangeNumbers.value.filter((n) => !hasProse(n))
}
function selectAllWritable() {
  const target = studio.book.targetChapters || 0
  const end = target > 0 ? target : Math.max(panel.to || 0, studio.maxNumber + 10)
  const list: number[] = []
  for (let n = 1; n <= end; n += 1) if (!hasProse(n)) list.push(n)
  panel.numbers = list
}
function selectSegment() {
  // 「本段」指下一章所在的段落纲，不是刚写完的那一段；否则写完一段后会选中整段已写章。
  const seg = studio.currentSegment
  if (!seg) {
    studio.toast('这一段还没排台阶，去细纲页规划本段', 'warn')
    return
  }
  const list: number[] = []
  for (let n = seg.from; n <= seg.to; n += 1) if (!hasProse(n)) list.push(n)
  panel.numbers = list
}
function clearSelection() {
  studio.clearSelection()
}

/* ---------- ② 写作设置 ---------- */

const platform = computed(
  () => platforms.value.find((p) => p.name === studio.book.platform) ?? null,
)
const platformLabel = computed(() =>
  platform.value
    ? `${platform.value.name} · ${platform.value.wordsMin}–${platform.value.wordsMax} 字/章`
    : studio.book.platform || '通用',
)
const targetModel = computed({
  get: () => String(targetWords.value || ''),
  set: (v: string) => {
    targetWords.value = Math.max(0, Number(v) || 0)
  },
})
const targetHint = computed(() => {
  const low = platform.value?.wordsMin ?? 1800
  return targetWords.value && targetWords.value < low
    ? `低于平台下限 ${low}，体检会打回`
    : `平台区间 ${platform.value ? `${platform.value.wordsMin}–${platform.value.wordsMax}` : '由本书平台决定'} 字`
})
function setOverwrite(v: boolean) {
  panel.overwrite = v
}

/* ---------- ③ 文风确认 ---------- */

const bookStyle = computed<ApiStyle>(() => studio.style ?? {})
const hasOverride = computed(() => Object.keys(panel.styleOverride).length > 0)

const styleDraft = computed<ApiStyle>({
  get: () => ({ ...bookStyle.value, ...panel.styleOverride }),
  set: (v) => {
    const next = diffStyle(v, bookStyle.value)
    const changed = JSON.stringify(next) !== JSON.stringify(panel.styleOverride)
    panel.styleOverride = next
    // 改过字段就作废上一次确认：确认的是哪一版，就得写哪一版。
    if (changed) panel.styleConfirmed = false
  },
})

function diffStyle(next: ApiStyle, base: ApiStyle): Partial<ApiStyle> {
  const out: Record<string, unknown> = {}
  for (const key of Object.keys(next) as (keyof ApiStyle)[]) {
    if (key === 'version') continue
    if (JSON.stringify(next[key]) !== JSON.stringify(base[key])) out[key] = next[key]
  }
  return out as Partial<ApiStyle>
}

function textOf(v: unknown): string {
  return Array.isArray(v) ? String(v.length) : v == null ? '' : String(v)
}

const styleSummary = computed(() => {
  const s = { ...bookStyle.value, ...panel.styleOverride }
  const parts = [s.pov, s.person, s.sentence, s.rhythm, s.dialogueRatio].map(textOf).filter(Boolean)
  const banned = Array.isArray(s.banned) ? s.banned.filter((x) => String(x).trim()).length : 0
  const samples = Array.isArray(s.samples) ? s.samples.length : 0
  if (!parts.length && !banned && !samples) return '按平台默认'
  return [...parts, banned ? `禁用 ${banned} 条` : '', samples ? `样章 ${samples} 段` : '']
    .filter(Boolean)
    .join(' · ')
})

const styleTag = computed<{ label: string; tone: 'neutral' | 'ok' | 'info' }>(() => {
  if (!panel.styleConfirmed) return { label: '待确认', tone: 'neutral' }
  return hasOverride.value ? { label: '已确认 · 本批覆盖', tone: 'info' } : { label: '已确认 · 书默认', tone: 'ok' }
})

const OVERRIDE_LABELS: Record<string, string> = {
  pov: '视角',
  person: '人称',
  sentence: '句长',
  paragraph: '段落',
  rhythm: '节奏',
  dialogueRatio: '对话比例',
  banned: '禁用表达',
  samples: '样章',
  references: '参考',
  notes: '补充说明',
  presetId: '预设',
}

const overrideChips = computed(() =>
  Object.entries(panel.styleOverride)
    .filter(([, v]) => {
      if (Array.isArray(v)) return v.some((x) => (typeof x === 'string' ? x.trim() : true))
      return v !== '' && v != null
    })
    .map(([key, value]) => ({ key, label: chipLabel(key, value) })),
)

function chipLabel(key: string, value: unknown): string {
  const label = OVERRIDE_LABELS[key] ?? key
  if (Array.isArray(value)) return `${label} ${value.length} 条`
  return `${label}=${textOf(value)}`
}

function removeOverride(key: string) {
  const next = { ...panel.styleOverride }
  delete next[key as keyof ApiStyle]
  panel.styleOverride = next
}

function useBookStyle() {
  panel.styleOverride = {}
  panel.styleConfirmed = true
  openStyleFields.value = false
}
function confirmOverride() {
  panel.styleConfirmed = true
}
function resetOverride() {
  panel.styleOverride = {}
  panel.styleConfirmed = false
}
async function saveStyleAsDefault() {
  if (!hasOverride.value) return
  if (!window.confirm('把本次改动存为书默认？\n以后每次开写都会带上；只影响这本书。')) return
  try {
    await studio.saveStyle(panel.styleOverride)
    panel.styleOverride = {}
    panel.styleConfirmed = true
  } catch {
    /* saveStyle 已 toast */
  }
}

/* ---------- ④ 写作技能 ---------- */

const bookSkills = computed<WritingSkills>(() => studio.skills ?? DEFAULT_SKILLS)
const effectiveSkills = computed<WritingSkills>(() => ({ ...bookSkills.value, ...panel.skillOverride }))
const skillCount = computed(() => Object.values(effectiveSkills.value).filter(Boolean).length)
const nuewenEnabled = computed(
  () => studio.skillsAvailable.nuewen?.enabled ?? Boolean(studio.book.nuewen),
)
const hasSamples = computed(() => (studio.style?.samples?.length ?? 0) > 0)

function onSkills(v: Partial<WritingSkills>) {
  const diff: Partial<WritingSkills> = {}
  for (const key of Object.keys(DEFAULT_SKILLS) as (keyof WritingSkills)[]) {
    if (typeof v[key] === 'boolean' && v[key] !== bookSkills.value[key]) diff[key] = v[key]
  }
  panel.skillOverride = diff
}
function resetSkills() {
  panel.skillOverride = {}
}
async function saveSkillsAsDefault() {
  if (!window.confirm('把这一批的技能选择存为书默认？\n以后每次开写都会带上；只影响这本书。')) return
  try {
    await studio.saveWritingSkills(effectiveSkills.value)
    panel.skillOverride = {}
  } catch {
    /* saveWritingSkills 已 toast */
  }
}

/* ---------- ⑤ 参考资料（条数以 /references 为准，不在前端估算） ---------- */

type RefRow = {
  group: string
  label: string
  count: string
  status: 'ok' | 'missing' | 'optional'
  to?: string
  hint?: string
}

const firstSelected = computed(() => {
  if (panel.numbers.length) return Math.min(...panel.numbers)
  return Math.max(1, Number(panel.from) || 1)
})

const refPack = ref<ReferencePack | null>(null)
const refPackLoading = ref(false)
let refSeq = 0

/** 与真实生成同源：拿到 pack 的 section.count，面板不再自己猜。 */
async function loadRefPack() {
  if (!studio.key || !panel.open) return
  const seq = ++refSeq
  refPackLoading.value = true
  try {
    const focus = panel.focus.map((f) => ({ type: f.type, key: f.key, label: f.label }))
    const skills = effectiveSkills.value
    const pack = focus.length
      ? await previewReferences(studio.key, firstSelected.value, focus, 'prose', skills)
      : await fetchReferences(studio.key, firstSelected.value, 'prose', skills)
    if (seq === refSeq) refPack.value = pack
  } catch {
    if (seq === refSeq) refPack.value = null
  } finally {
    if (seq === refSeq) refPackLoading.value = false
  }
}

watch(
  () => [
    panel.open,
    firstSelected.value,
    JSON.stringify(panel.focus),
    JSON.stringify(effectiveSkills.value),
  ] as const,
  () => void loadRefPack(),
  { immediate: true },
)

function refRoute(key: string): string | undefined {
  if (key.startsWith('foreshadow')) return '/foreshadow'
  if (key === 'volume-outline' || key === 'stage') return '/detail'
  if (key === 'characters' || key === 'continuity-state') return '/characters'
  if (key.startsWith('character')) return '/memory'
  if (key === 'relations') return '/characters?view=relations'
  if (key === 'info-gaps') return '/setup?tab=gaps'
  if (key === 'rules' || key === 'style' || key === 'platform') return '/setup'
  if (key === 'power-system' || key === 'society' || key === 'history' || key === 'glossary') {
    return '/setup?tab=world'
  }
  if (key === 'world' || key === 'factions' || key === 'locations' || key === 'items') return '/outline?tab=world'
  if (key === 'chapter-memory' || key === 'volume-memory' || key === 'timeline') return '/memory'
  return undefined
}

const packRows = computed<RefRow[]>(() => {
  const pack = refPack.value
  if (!pack) return []
  return pack.sections
    .filter((s) => s.key !== 'extra-focus')
    .map((s) => ({
      group: s.group,
      label: s.label,
      count: s.missing ? '缺' : `${s.count} 条`,
      status: s.missing ? 'missing' : s.optional && !s.count ? 'optional' : 'ok',
      to: s.missing ? refRoute(s.key) : undefined,
      hint: s.truncated
        ? (s.kept === 0 && s.count
          ? `本章没用到，只留名录 ${s.count} 条`
          : s.kept < s.count ? `已按预算收口 ${s.kept}/${s.count} 条` : '已按预算截断')
        : s.source,
    }))
})

const localReferenceRows = computed<RefRow[]>(() => {
  const rows: RefRow[] = []
  const seg = studio.currentSegment
  const openFs = studio.foreshadows.filter((f) => f.status === 'open').length
  const dueFs = studio.foreshadows.filter(
    (f) => f.status === 'open' && f.dueChapter != null && f.dueChapter >= firstSelected.value &&
      f.dueChapter <= Math.max(panel.to, firstSelected.value),
  ).length
  const prev = firstSelected.value - 1

  rows.push(
    studio.outline.length
      ? { group: '结构', label: '本卷大纲', count: `${studio.outline.length} 卷`, status: 'ok' }
      : { group: '结构', label: '本卷大纲', count: '缺', status: 'missing', to: '/outline', hint: '去大纲页生成卷结构' },
  )
  rows.push(
    seg
      ? { group: '结构', label: '本章台阶', count: `${seg.plan.stages.length} 台阶`, status: 'ok' }
      : { group: '结构', label: '本章台阶', count: '无', status: 'optional', to: '/detail', hint: '去细纲页规划本段' },
  )
  rows.push({ group: '伏笔', label: '本章应埋收', count: dueFs ? `${dueFs} 条` : '无', status: 'optional' })
  rows.push(
    openFs
      ? { group: '伏笔', label: '其他未收', count: `${openFs} 条`, status: 'ok' }
      : { group: '伏笔', label: '其他未收', count: '缺', status: 'missing', to: '/foreshadow', hint: '去伏笔页设计' },
  )
  rows.push(
    studio.characters.length
      ? { group: '人物', label: '人物卡', count: `${studio.characters.length} 人`, status: 'ok' }
      : { group: '人物', label: '人物卡', count: '缺', status: 'missing', to: '/characters', hint: '去人物页补齐' },
  )
  rows.push(
    studio.memory?.characters.length
      ? { group: '人物', label: '人物当前状态', count: `${studio.memory.characters.length} 人`, status: 'ok' }
      : { group: '人物', label: '人物当前状态', count: '缺', status: 'missing', to: '/memory', hint: '去记忆页生成' },
  )
  rows.push(
    studio.memory?.relations.length
      ? { group: '人物', label: '人物关系', count: `${studio.memory.relations.length} 组`, status: 'ok' }
      : { group: '人物', label: '人物关系', count: '缺', status: 'missing', to: '/characters?view=relations', hint: '去人物页补齐' },
  )
  const withLocation = studio.characters.filter((c) => c.location).length
  rows.push(
    withLocation
      ? { group: '人物', label: '位置与轨迹', count: `${withLocation} 人`, status: 'ok' }
      : { group: '人物', label: '位置与轨迹', count: '缺', status: 'optional', to: '/characters', hint: '写正文时自动回写' },
  )
  rows.push(
    studio.infoGaps.length
      ? { group: '人物', label: '信息差', count: `${studio.infoGaps.length} 条`, status: 'ok' }
      : { group: '人物', label: '信息差', count: '无', status: 'optional', to: '/setup?tab=gaps', hint: '生成设定时一起补齐' },
  )
  rows.push(
    studio.rules.length
      ? { group: '世界', label: '规则', count: `${studio.rules.length} 条`, status: 'ok' }
      : { group: '世界', label: '规则', count: '缺', status: 'missing', to: '/setup', hint: '去设定页补齐' },
  )
  const power = studio.data.powerSystem
  const loreCount =
    (power.name || power.levels.length ? 1 : 0) +
    studio.data.history.length +
    studio.data.glossary.length +
    (Object.values(studio.data.society).some(Boolean) ? 1 : 0)
  rows.push(
    loreCount
      ? { group: '世界', label: '世界纵深', count: `${loreCount} 项`, status: 'ok', hint: '力量体系 / 社会 / 大事记 / 术语' }
      : { group: '世界', label: '世界纵深', count: '无', status: 'optional', to: '/setup?tab=world', hint: '补力量体系、大事记与术语' },
  )
  rows.push(
    studio.book.worldText
      ? { group: '世界', label: '世界观', count: '有', status: 'ok' }
      : { group: '世界', label: '世界观', count: '缺', status: 'missing', to: '/outline?tab=world', hint: '去大纲页的世界观栏生成' },
  )
  rows.push(
    studio.factions.length
      ? { group: '世界', label: '势力', count: `${studio.factions.length} 个`, status: 'ok' }
      : { group: '世界', label: '势力', count: '缺', status: 'missing', to: '/setup', hint: '去设定页补齐' },
  )
  rows.push(
    studio.data.locations.length
      ? { group: '世界', label: '地点', count: `${studio.data.locations.length} 处`, status: 'ok' }
      : { group: '世界', label: '地点', count: '缺', status: 'missing', to: '/setup?tab=locations', hint: '去设定页补齐' },
  )
  rows.push(
    studio.data.items.length
      ? { group: '世界', label: '物品与持有', count: `${studio.data.items.length} 件`, status: 'ok' }
      : { group: '世界', label: '物品与持有', count: '无', status: 'optional', to: '/setup?tab=items', hint: '有物品时自动注入' },
  )
  rows.push(
    studio.memory?.chapters.length
      ? { group: '前情', label: '近章记忆', count: `${studio.memory.chapters.length} 章`, status: 'ok' }
      : { group: '前情', label: '近章记忆', count: '缺', status: 'missing', to: '/memory', hint: '去记忆页生成' },
  )
  rows.push(
    studio.memory?.volumes.some((v) => v.summary)
      ? { group: '前情', label: '卷摘要', count: `${studio.memory.volumes.filter((v) => v.summary).length} 卷`, status: 'ok' }
      : { group: '前情', label: '卷摘要', count: '缺', status: 'missing', to: '/memory', hint: '去记忆页生成' },
  )
  rows.push(
    studio.timeline.length
      ? { group: '前情', label: '时间线', count: `${studio.timeline.length} 条`, status: 'ok' }
      : { group: '前情', label: '时间线', count: '无', status: 'optional', hint: '还没有故事内时间记录' },
  )
  rows.push(
    prev >= 1 && studio.findChapter(prev)
      ? { group: '前情', label: '上一章结尾', count: `第 ${prev} 章`, status: 'ok' }
      : { group: '前情', label: '上一章结尾', count: prev < 1 ? '本章是开篇' : '无', status: 'optional' },
  )
  rows.push(
    studio.styleSource === 'book'
      ? { group: '写法', label: '文风', count: '书默认', status: 'ok', to: '/setup' }
      : { group: '写法', label: '文风', count: '按平台默认', status: 'optional', to: '/setup', hint: '去设定页填文风' },
  )
  if (effectiveSkills.value.platform) {
    rows.push({ group: '写法', label: '平台打法', count: platformLabel.value, status: 'ok' })
  }
  rows.push(
    studio.book.nuewen
      ? { group: '写法', label: '虐文原则', count: '已开启', status: 'ok' }
      : { group: '写法', label: '虐文原则', count: '未开启', status: 'optional', hint: '可选，不标灰' },
  )
  return rows
})

const referenceRows = computed<RefRow[]>(() => (packRows.value.length ? packRows.value : localReferenceRows.value))

const referenceGroups = computed(() => {
  const map = new Map<string, RefRow[]>()
  for (const row of referenceRows.value) {
    if (!map.has(row.group)) map.set(row.group, [])
    map.get(row.group)!.push(row)
  }
  return [...map.entries()].map(([group, rows]) => ({ group, rows }))
})

/* ---------- 页脚估算与启动 ---------- */

const selectedCount = computed(() => panel.numbers.length)
const deaiOn = computed(() => effectiveSkills.value.deai)
const callHint = computed(() => {
  const n = selectedCount.value
  if (!n) return '预计 0 章'
  const base = 1 + n * 2 // 本批 1 次细纲 + 每章正文 + 记忆回写
  return deaiOn.value
    ? `预计 ${n} 章 · ${base} 次基础调用（本批细纲 / 每章正文与记忆）+ 最多 ${n} 次去 AI 味改写 · ${n * 2}–${n * 5} 分钟`
    : `预计 ${n} 章 · ${base} 次基础调用（本批细纲 / 每章正文与记忆）· ${n * 2}–${n * 5} 分钟`
})

const noOutline = computed(() => !String(studio.book.outlineText || '').trim())
/** 正文必须按伏笔网推进：一条伏笔都没有时，先设计伏笔再开写。 */
const noForeshadow = computed(() => studio.foreshadows.length === 0)
const canStart = computed(
  () =>
    !isRunning.value &&
    selectedCount.value > 0 &&
    panel.styleConfirmed &&
    !noOutline.value &&
    !noForeshadow.value &&
    !rangeError.value,
)
const startHint = computed(() => {
  if (noOutline.value) return '还没有大纲，写不了正文'
  if (noForeshadow.value) return '还没有伏笔，正文会一路丢线'
  if (!selectedCount.value) return '先选至少一章'
  if (!panel.styleConfirmed) return '开写前先确认这一批的文风'
  if (rangeError.value) return rangeError.value
  return ''
})

async function start() {
  if (!canStart.value) return
  mode.value = 'running'
  await studio.startWriteBatch()
  mode.value = 'done'
}

/* ---------- 运行态 / 完成态 ---------- */

function stageLabel(stage: WriteChapterState['stage']): string {
  switch (stage) {
    case 'queued': return '等待'
    case 'outline': return '生成细纲…'
    case 'prose': return '写正文…'
    case 'done': return '已完成'
    case 'failed': return '失败'
    case 'skipped': return '已跳过'
  }
}
function rowTitle(row: WriteChapterState): string {
  return row.title || chapterOf(row.number)?.title || '—'
}

/** 一批写完后，把正文里新出现的内容补进设定（同名不重复）。 */
const supplemented = ref(false)
async function supplementAfterRun() {
  try {
    await studio.supplementSettings(8)
    supplemented.value = true
  } catch {
    /* store 已 toast */
  }
}
watch(
  () => run.value.runId,
  () => {
    supplemented.value = false
  },
)

const failedRow = computed(() => run.value.chapters.find((c) => c.stage === 'failed') ?? null)
const doneCount = computed(() => run.value.chapters.filter((c) => c.stage === 'done').length)
const skippedCount = computed(() => run.value.chapters.filter((c) => c.stage === 'skipped').length)
const failedCount = computed(() => run.value.chapters.filter((c) => c.stage === 'failed').length)
const progressPct = computed(() =>
  run.value.total ? Math.round((run.value.done / run.value.total) * 100) : 0,
)

const runRangeLabel = computed(() =>
  run.value.from === run.value.to ? `第 ${run.value.from} 章` : `第 ${run.value.from}–${run.value.to} 章`,
)

const doneTitle = computed(() => {
  if (failedCount.value && !doneCount.value && !skippedCount.value) return '这一批没有写成'
  if (failedCount.value) return `完成 ${doneCount.value} 章，${failedCount.value} 章失败`
  if (!doneCount.value && skippedCount.value) return '没有需要写的章'
  return '本批完成'
})
const doneDesc = computed(() => {
  if (failedCount.value) {
    const row = failedRow.value
    return row?.error
      ? `第 ${row.number} 章停在生成阶段：${row.error}。本章没有落盘，前面的章不受影响。`
      : '部分章节没有写成，已完成章不受影响。'
  }
  if (!doneCount.value && skippedCount.value) {
    return '选中的章都已有正文。要重写请在设置里选「覆盖」。'
  }
  return `新写 ${doneCount.value} 章${skippedCount.value ? `，跳过 ${skippedCount.value} 章` : ''}。都停在待确认，不会自动存档。`
})

async function retryFailed() {
  const row = failedRow.value
  if (!row) return
  mode.value = 'running'
  await studio.retryChapter(row.number)
  mode.value = 'done'
}

async function skipAndContinue() {
  const remaining = run.value.chapters.filter((c) => c.stage === 'queued').map((c) => c.number)
  if (!remaining.length) {
    studio.toast('后面没有待写的章了', 'info')
    return
  }
  panel.numbers = remaining
  mode.value = 'running'
  await studio.startWriteBatch()
  mode.value = 'done'
}

function pauseAfterCurrent() {
  studio.pauseAfterCurrent()
}

function stopBatch() {
  studio.pauseAfterCurrent()
  studio.toast('当前章完成后停止本批', 'info')
}

function collapse() {
  seenRunId.value = run.value.runId
  studio.closeWritePanel()
}

function close() {
  seenRunId.value = run.value.runId
  studio.closeWritePanel()
}

function continueWriting() {
  seenRunId.value = run.value.runId
  studio.openWritePanel({ source: 'today' })
  mode.value = 'prep'
}

function goReview() {
  const query: Record<string, string> = { from: String(run.value.from), to: String(run.value.to), filter: 'pending' }
  seenRunId.value = run.value.runId
  studio.closeWritePanel()
  void router.push({ path: '/progress', query })
}
</script>

<template>
  <Modal
    :open="panel.open"
    :title="modalTitle"
    :desc="modalDesc"
    width="1000px"
    @close="close"
  >
    <!-- 准备态 -->
    <div v-if="mode === 'prep'" class="wp">
      <div class="wp__banner" :class="{ 'wp__banner--bad': noOutline || noForeshadow }" role="status">
        <template v-if="noOutline">
          <b>还没有大纲</b>
          <span>开写需要先有骨架：这一章落在哪一卷、往哪儿走，都从大纲来。</span>
          <RouterLink to="/outline" class="wp__link">去开书流程 →</RouterLink>
        </template>
        <template v-else-if="noForeshadow">
          <b>还没有伏笔</b>
          <span>正文要按伏笔网推进：先埋线，再写这一批，后面的回收才有落点。</span>
          <RouterLink to="/foreshadow" class="wp__link">去设计伏笔 →</RouterLink>
        </template>
        <template v-else>
          <b>第 {{ panel.from }}–{{ panel.to }} 章</b>
          <span>已按「{{ panel.source }}」带入，可调整。写完停在待确认，不会自动存档。</span>
        </template>
      </div>

      <div class="wp__cols">
        <Card title="① 本批章节">
          <div class="wp__range">
            <Input v-model="fromModel" label="从" type="number" min="1" size="sm" />
            <Input v-model="toModel" label="到" type="number" min="1" size="sm" />
            <div class="wp__rangeacts">
              <Button size="sm" variant="ghost" :disabled="!!rangeError" @click="selectRange">选中范围</Button>
              <Button size="sm" variant="ghost" @click="selectAllWritable">全选待写</Button>
              <Button size="sm" variant="ghost" @click="selectSegment">选中本段</Button>
              <Button size="sm" variant="ghost" @click="clearSelection">清空</Button>
            </div>
          </div>
          <p v-if="rangeError" class="wp__error" role="alert">{{ rangeError }}</p>

          <div class="wp__list" role="group" aria-label="本批章节">
            <div
              v-for="n in rangeNumbers"
              :key="n"
              class="wp__row"
              :class="{ 'wp__row--off': !selectable(n) }"
            >
              <label class="wp__rowmain">
                <input
                  type="checkbox"
                  class="wp__check"
                  :checked="checked(n)"
                  :disabled="!selectable(n)"
                  :title="!selectable(n) ? '已有正文，将跳过' : ''"
                  @change="toggleChapter(n)"
                />
                <span class="wp__no">{{ pad3(n) }}</span>
                <span class="wp__name">{{ chapterOf(n)?.title || '—' }}</span>
              </label>
              <Tag size="sm" :tone="statusOf(n).tone">{{ statusOf(n).label }}</Tag>
              <span class="wp__chars">
                {{ chapterOf(n)?.chars ?? 0 }} / {{ targetWords || '—' }}
              </span>
              <span v-if="hasProse(n) && !panel.overwrite" class="wp__note">已有正文，将跳过</span>
              <span v-else-if="hasProse(n) && panel.overwrite && checked(n)" class="wp__note wp__note--warn">
                重写会进废章
              </span>
            </div>
            <p v-if="!rangeNumbers.length" class="wp__muted">这个范围里没有章。换个起止试试。</p>
          </div>

          <p class="wp__summary">
            将写 {{ selectedCount }} 章 · 跳过
            {{ rangeNumbers.filter((n) => hasProse(n) && !checked(n)).length }} 章
          </p>
        </Card>

        <div class="wp__side">
          <Card title="② 写作设置">
            <div class="wp__setting">
              <Input
                v-model="targetModel"
                label="每章目标字数"
                type="number"
                min="0"
                step="100"
                size="sm"
                :hint="targetHint"
              />
              <div class="wp__kv">
                <span>平台区间</span>
                <Tag size="sm" tone="neutral">{{ platformLabel }}</Tag>
              </div>
              <div class="wp__kv">
                <span>虐文模式</span>
                <span class="wp__inline">
                  <Tag size="sm" :tone="studio.book.nuewen ? 'pink' : 'neutral'">
                    {{ studio.book.nuewen ? '已开启' : '未开启' }}
                  </Tag>
                  <RouterLink to="/detail" class="wp__link">去细纲页切换 →</RouterLink>
                </span>
              </div>
              <div class="wp__kv">
                <span>已有正文</span>
                <span class="wp__seg">
                  <button
                    type="button"
                    class="wp__segbtn"
                    :class="{ on: !panel.overwrite }"
                    @click="setOverwrite(false)"
                  >跳过（推荐）</button>
                  <button
                    type="button"
                    class="wp__segbtn"
                    :class="{ on: panel.overwrite }"
                    @click="setOverwrite(true)"
                  >覆盖</button>
                </span>
              </div>
              <p v-if="panel.overwrite" class="wp__warn" role="alert">
                覆盖会把旧稿存进「废章」，新稿回到待确认。
              </p>
              <div class="wp__kv">
                <span>写作技能</span>
                <span class="wp__inline">
                  <Tag size="sm" tone="info">{{ skillCount }} / 8 开</Tag>
                  <Button size="sm" variant="ghost" @click="openSkills = !openSkills">调整技能</Button>
                </span>
              </div>
            </div>
          </Card>

          <Card title="③ 文风确认">
            <template #actions>
              <Tag size="sm" :tone="styleTag.tone">{{ styleTag.label }}</Tag>
            </template>
            <p class="wp__styleline">{{ styleSummary }}</p>
            <p v-if="!panel.styleConfirmed" class="wp__muted">开写前先确认这一批的文风。</p>
            <p v-if="studio.styleSource !== 'book'" class="wp__muted">
              这本书还没定文风；不填也能写，但句长、对话比和禁用表达会按平台默认。
              <RouterLink to="/style" class="wp__link">去文风页定默认 →</RouterLink>
            </p>
            <p v-else class="wp__muted">
              <RouterLink to="/style" class="wp__link">改全书默认文风 →</RouterLink>
            </p>

            <div v-if="overrideChips.length" class="wp__chips">
              <span class="wp__chipslabel">本次覆盖：</span>
              <button
                v-for="chip in overrideChips"
                :key="chip.key"
                type="button"
                class="wp__chip"
                :title="`清除 ${chip.label}`"
                @click="removeOverride(chip.key)"
              >{{ chip.label }} <i aria-hidden="true">×</i></button>
            </div>

            <div class="wp__acts">
              <Button size="sm" variant="primary" @click="useBookStyle">使用书默认</Button>
              <Button size="sm" variant="ghost" @click="openStyleFields = !openStyleFields">
                {{ openStyleFields ? '收起字段' : '调整本次' }}
              </Button>
              <Button v-if="hasOverride" size="sm" variant="secondary" @click="confirmOverride">
                确认本次文风
              </Button>
              <Button v-if="hasOverride" size="sm" variant="ghost" @click="resetOverride">
                重置本次覆盖
              </Button>
              <Button v-if="hasOverride" size="sm" variant="ghost" @click="saveStyleAsDefault">
                另存为书默认
              </Button>
            </div>

            <div v-if="openStyleFields" class="wp__stylefields">
              <StyleFields v-model="styleDraft" compact local-presets />
            </div>
          </Card>

          <Card title="④ 写作技能">
            <template #actions>
              <Tag size="sm" tone="neutral">{{ skillCount }} / 8 开</Tag>
            </template>
            <p class="wp__muted">默认值按书记住；下面的改动只作用于这一批。</p>
            <div class="wp__acts">
              <Button size="sm" variant="ghost" @click="openSkills = !openSkills">
                {{ openSkills ? '收起技能' : '调整技能' }}
              </Button>
              <Button size="sm" variant="ghost" @click="resetSkills">重置为书默认</Button>
              <Button size="sm" variant="ghost" @click="saveSkillsAsDefault">另存为书默认</Button>
            </div>
            <div v-if="openSkills" class="wp__skills">
              <WritingSkillPicker
                :model-value="effectiveSkills"
                :nuewen-enabled="nuewenEnabled"
                :has-samples="hasSamples"
                @update:model-value="onSkills"
              />
            </div>
          </Card>

          <Card title="⑤ 参考资料">
            <template #actions>
              <Tag size="sm" tone="neutral">
                {{ refPack ? `${refPack.summary.items} 条 · 约 ${refPack.summary.chars} 字` : `${referenceRows.filter((r) => r.status === 'ok').length} / ${referenceRows.length}` }}
              </Tag>
            </template>
            <div v-for="group in referenceGroups" :key="group.group" class="wp__refgroup">
              <div class="wp__refhead">{{ group.group }}</div>
              <div
                v-for="row in group.rows"
                :key="row.label"
                class="wp__refrow"
                :class="`wp__refrow--${row.status}`"
              >
                <Tag size="sm" :tone="row.status === 'ok' ? 'ok' : row.status === 'missing' ? 'warn' : 'neutral'" dot>
                  {{ row.status === 'ok' ? '有' : row.status === 'missing' ? '缺' : '可选' }}
                </Tag>
                <span class="wp__refname">{{ row.label }}</span>
                <span class="wp__refcount">{{ row.count }}</span>
                <RouterLink v-if="row.to" :to="row.to" class="wp__link">补齐 →</RouterLink>
                <span v-else-if="row.hint" class="wp__refhint">{{ row.hint }}</span>
              </div>
            </div>
            <p class="wp__muted">
              {{ refPackLoading ? '正在打包本章参考资料…' : '条数与生成提示词一致；标灰项补齐后会减少跑偏。' }}
            </p>
          </Card>
        </div>
      </div>
    </div>

    <!-- 运行态 -->
    <div v-else-if="mode === 'running'" class="wp wp--run">
      <div class="wp__runhead" role="status" aria-live="polite">
        <span>{{ runRangeLabel }} · {{ run.done }} / {{ run.total }} 完成</span>
        <span v-if="run.pauseAfterCurrent" class="wp__pausetag">已安排暂停</span>
      </div>
      <div class="wp__bar" aria-hidden="true"><span :style="{ width: `${progressPct}%` }" /></div>

      <GenStream
        v-if="liveWriting"
        :active="live.active"
        :text="live.text"
        :title="live.title"
        :stage="live.stage"
        :kind="live.kind"
        :started-at="live.startedAt"
      />

      <div class="wp__runlist">
        <div
          v-for="row in run.chapters"
          :key="row.number"
          class="wp__runrow"
          :class="`wp__runrow--${row.stage}`"
        >
          <span class="wp__runicon" aria-hidden="true">
            {{ row.stage === 'done' ? '✓' : row.stage === 'failed' ? '!' : row.stage === 'skipped' ? '↷' : row.stage === 'outline' || row.stage === 'prose' ? '◐' : '○' }}
          </span>
          <span class="wp__no">{{ pad3(row.number) }}</span>
          <span class="wp__runname">{{ rowTitle(row) }}</span>
          <Tag
            size="sm"
            :tone="row.stage === 'failed' ? 'bad' : row.stage === 'done' ? 'ok' : row.stage === 'skipped' ? 'neutral' : 'info'"
          >{{ stageLabel(row.stage) }}</Tag>
          <span v-if="row.stage === 'done'" class="wp__runmeta">
            {{ row.chars ?? 0 }} 字 → 待确认<span v-if="row.memory" class="wp__runmem"> · {{ row.memory }}</span>
          </span>
          <span v-else-if="row.stage === 'skipped'" class="wp__runmeta">已有正文</span>
        </div>
      </div>

      <p v-if="run.error" class="wp__error" role="alert">{{ run.error }}</p>
      <p class="wp__muted">模型可能失败；失败会停在本章，已完成的章不受影响。</p>
      <p class="wp__muted">每章落盘后 AI 会自动回写「记忆」（时间线 · 人物 · 事件），不用手写；回写失败不影响正文，可在记忆页补齐。</p>

      <div v-if="failedRow" class="wp__acts">
        <Button size="sm" variant="primary" @click="retryFailed">只重试这一章</Button>
        <Button size="sm" variant="secondary" @click="skipAndContinue">跳过并继续</Button>
        <Button size="sm" variant="ghost" @click="stopBatch">停止本批</Button>
      </div>
    </div>

    <!-- 完成态 -->
    <div v-else class="wp wp--done">
      <header class="wp__donehead">
        <h3>{{ doneTitle }}</h3>
        <p>{{ doneDesc }}</p>
      </header>
      <ul class="wp__donelist">
        <li v-for="row in run.chapters" :key="row.number" :class="`wp__donerow--${row.stage}`">
          <span class="wp__no">{{ pad3(row.number) }}</span>
          <span class="wp__runname">{{ rowTitle(row) }}</span>
          <span class="wp__runmeta">
            {{ row.stage === 'done' ? `${row.chars ?? 0} 字 · 待确认` : stageLabel(row.stage) }}
          </span>
        </li>
      </ul>

      <div v-if="doneCount" class="wp__supp">
        <div>
          <b>这批新出现的人、地、物，要不要补进设定？</b>
          <p>只看最近 8 章正文；已有条目（含别名）一律跳过，不会覆盖旧设定。记忆已自动回写，伏笔可在「伏笔」页补。</p>
        </div>
        <Button
          size="sm"
          :variant="supplemented ? 'ghost' : 'secondary'"
          :disabled="studio.settingsBusy || supplemented"
          @click="supplementAfterRun"
        >
          {{ supplemented ? '已补进设定' : studio.settingsBusy ? '正在补…' : '补进设定（不重复）' }}
        </Button>
      </div>

      <GenStream
        v-if="liveSupplement"
        :active="live.active"
        :text="live.text"
        :title="live.title"
        :stage="live.stage"
        :kind="live.kind"
        :started-at="live.startedAt"
        label="补设定实况"
      />
    </div>

    <template #footer>
      <template v-if="mode === 'prep'">
        <div class="wp__footinfo">
          <span>{{ callHint }}</span>
          <span v-if="startHint" class="wp__foothint">{{ startHint }}</span>
          <span class="wp__muted">模型可能失败；失败会停在本章，已完成的章不受影响。</span>
        </div>
        <div class="wp__footacts">
          <Button variant="ghost" @click="close">取消</Button>
          <Button variant="pink" :disabled="!canStart" :title="startHint" @click="start">
            开始写 {{ selectedCount }} 章
          </Button>
        </div>
      </template>
      <template v-else-if="mode === 'running'">
        <div class="wp__footinfo">
          <span>{{ runRangeLabel }} · 正在写第 {{ run.current || run.from }} 章…</span>
        </div>
        <div class="wp__footacts">
          <Button variant="ghost" @click="collapse">收起（后台继续）</Button>
          <Button variant="secondary" :disabled="run.pauseAfterCurrent" @click="pauseAfterCurrent">
            {{ run.pauseAfterCurrent ? '已安排暂停' : '本章完成后暂停' }}
          </Button>
        </div>
      </template>
      <template v-else>
        <div class="wp__footinfo">
          <span>{{ doneTitle }}</span>
        </div>
        <div class="wp__footacts">
          <Button v-if="failedRow" variant="primary" @click="retryFailed">
            重试第 {{ failedRow.number }} 章
          </Button>
          <Button v-if="doneCount || skippedCount" variant="secondary" @click="goReview">逐章审阅</Button>
          <Button v-if="!doneCount && skippedCount" variant="secondary" @click="continueWriting">返回修改</Button>
          <Button v-else variant="ghost" @click="continueWriting">继续开写</Button>
          <Button variant="ghost" @click="close">关闭</Button>
        </div>
      </template>
    </template>
  </Modal>
</template>

<style scoped>
.wp {
  display: grid;
  gap: var(--ns-s4);
}
.wp__banner {
  display: flex;
  align-items: baseline;
  gap: var(--ns-s3);
  flex-wrap: wrap;
  padding: var(--ns-s3) var(--ns-s4);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
}
.wp__banner b {
  color: var(--ns-ink);
}
.wp__banner--bad {
  border-color: color-mix(in srgb, var(--ns-warn) 30%, transparent);
  background: var(--ns-warn-soft);
}
.wp__cols {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  gap: var(--ns-s4);
  align-items: start;
}
.wp__side {
  display: grid;
  gap: var(--ns-s4);
  min-width: 0;
}
.wp__range {
  display: grid;
  grid-template-columns: 84px 84px minmax(0, 1fr);
  gap: var(--ns-s2);
  align-items: end;
}
.wp__rangeacts {
  display: flex;
  gap: var(--ns-s1);
  flex-wrap: wrap;
  justify-content: flex-end;
}
.wp__list {
  display: grid;
  gap: 1px;
  margin-top: var(--ns-s3);
  max-height: 340px;
  overflow: auto;
}
.wp__row {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  padding: 5px 6px;
  border-radius: var(--ns-r-xs);
  font-size: var(--ns-fs-12);
}
.wp__row:hover {
  background: var(--ns-card-2);
}
.wp__row--off {
  opacity: 0.55;
}
.wp__rowmain {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  flex: 1;
  min-width: 0;
  cursor: pointer;
}
.wp__row--off .wp__rowmain {
  cursor: not-allowed;
}
.wp__check {
  flex: none;
  width: 15px;
  height: 15px;
  accent-color: var(--ns-pink);
}
.wp__no {
  flex: none;
  color: var(--ns-ink-4);
  font-family: var(--ns-mono, monospace);
  font-size: var(--ns-fs-11);
  font-variant-numeric: tabular-nums;
}
.wp__name,
.wp__runname {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp__chars {
  flex: none;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  font-variant-numeric: tabular-nums;
}
.wp__note {
  flex: none;
  color: var(--ns-ink-4);
  font-size: var(--ns-fs-11);
}
.wp__note--warn {
  color: var(--ns-warn);
}
.wp__summary {
  margin: var(--ns-s3) 0 0;
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-11);
  font-variant-numeric: tabular-nums;
}
.wp__setting {
  display: grid;
  gap: var(--ns-s3);
}
.wp__kv {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ns-s2);
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  flex-wrap: wrap;
}
.wp__inline {
  display: inline-flex;
  align-items: center;
  gap: var(--ns-s2);
  flex-wrap: wrap;
}
.wp__seg {
  display: inline-flex;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  overflow: hidden;
}
.wp__segbtn {
  border: 0;
  background: transparent;
  color: var(--ns-ink-2);
  font: inherit;
  font-size: var(--ns-fs-11);
  padding: 4px 9px;
  cursor: pointer;
}
.wp__segbtn.on {
  background: var(--ns-ink);
  color: var(--ns-paper);
}
.wp__warn {
  margin: 0;
  padding: 7px 9px;
  border-radius: var(--ns-r-xs);
  background: var(--ns-warn-soft);
  color: var(--ns-warn);
  font-size: var(--ns-fs-11);
  line-height: 1.6;
}
.wp__styleline {
  margin: 0 0 var(--ns-s2);
  color: var(--ns-ink);
  font-size: var(--ns-fs-12);
  line-height: 1.7;
}
.wp__muted {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  line-height: 1.7;
}
.wp__link {
  color: var(--ns-pink-2);
  font-size: var(--ns-fs-11);
  text-decoration: none;
  white-space: nowrap;
}
.wp__link:hover {
  text-decoration: underline;
}
.wp__chips {
  display: flex;
  align-items: center;
  gap: var(--ns-s1);
  flex-wrap: wrap;
  margin: var(--ns-s2) 0;
}
.wp__chipslabel {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.wp__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--ns-pink-line);
  border-radius: var(--ns-r-pill);
  background: var(--ns-pink-soft);
  color: var(--ns-pink-2);
  font: inherit;
  font-size: var(--ns-fs-11);
  padding: 1px 7px;
  cursor: pointer;
}
.wp__chip i {
  font-style: normal;
  opacity: 0.8;
}
.wp__acts {
  display: flex;
  gap: var(--ns-s2);
  flex-wrap: wrap;
  margin-top: var(--ns-s2);
}
.wp__stylefields,
.wp__skills {
  margin-top: var(--ns-s3);
  padding-top: var(--ns-s3);
  border-top: 1px dashed var(--ns-line-2);
}
.wp__refgroup {
  display: grid;
  gap: 2px;
  margin-bottom: var(--ns-s2);
}
.wp__refhead {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  font-weight: 700;
  letter-spacing: 0.08em;
}
.wp__refrow {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  padding: 3px 4px;
  border-radius: var(--ns-r-xs);
  font-size: var(--ns-fs-11);
}
.wp__refrow--missing {
  opacity: 0.6;
}
.wp__refname {
  flex: none;
  color: var(--ns-ink-2);
}
.wp__refcount {
  flex: 1;
  min-width: 0;
  color: var(--ns-ink-3);
  font-variant-numeric: tabular-nums;
}
.wp__refhint {
  flex: none;
  color: var(--ns-ink-4);
  font-size: var(--ns-fs-11);
}
.wp__error {
  margin: 0;
  color: var(--ns-bad);
  font-size: var(--ns-fs-12);
}
.wp__runhead {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ns-s3);
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  font-variant-numeric: tabular-nums;
}
.wp__pausetag {
  color: var(--ns-info);
  font-weight: 600;
}
.wp__bar {
  height: 4px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-line);
  overflow: hidden;
}
.wp__bar span {
  display: block;
  height: 100%;
  background: var(--ns-pink);
  transition: width 0.2s ease;
}
.wp__runlist {
  display: grid;
  gap: 2px;
  max-height: 360px;
  overflow: auto;
}
.wp__runrow {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  padding: 6px 8px;
  border-radius: var(--ns-r-xs);
  font-size: var(--ns-fs-12);
}
.wp__runrow--outline,
.wp__runrow--prose {
  background: var(--ns-info-soft);
}
.wp__runrow--failed {
  background: var(--ns-bad-soft);
}
.wp__runrow--skipped {
  color: var(--ns-ink-3);
}
.wp__runicon {
  flex: none;
  width: 16px;
  color: var(--ns-ink-3);
  text-align: center;
}
.wp__runrow--done .wp__runicon {
  color: var(--ns-ok);
}
.wp__runrow--failed .wp__runicon {
  color: var(--ns-bad);
  font-weight: 700;
}
.wp__runmeta {
  flex: none;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.wp__runmem {
  color: var(--ns-ok);
}
.wp--done {
  gap: var(--ns-s3);
}
.wp__donehead h3 {
  margin: 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-18);
}
.wp__donehead p {
  margin: 6px 0 0;
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  line-height: 1.7;
}
.wp__donelist {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: var(--ns-fs-12);
}
.wp__donelist li {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  padding: 4px 6px;
}
.wp__supp {
  display: flex;
  align-items: center;
  gap: var(--ns-s4);
  padding: 12px 14px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card-2);
}
.wp__supp > div {
  flex: 1;
  min-width: 0;
}
.wp__supp b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-13);
}
.wp__supp p {
  margin: 3px 0 0;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--ns-ink-3);
}
.wp__donerow--failed .wp__runmeta {
  color: var(--ns-bad);
}
.wp__footinfo {
  display: grid;
  gap: 3px;
  flex: 1;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  line-height: 1.6;
  font-variant-numeric: tabular-nums;
}
.wp__foothint {
  color: var(--ns-warn);
  font-weight: 600;
}
.wp__footacts {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  flex-wrap: wrap;
}
@media (max-width: 1099px) {
  .wp__cols {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 760px) {
  .wp__range {
    grid-template-columns: 1fr 1fr;
  }
  .wp__rangeacts {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }
  .wp__footinfo {
    flex-basis: 100%;
  }
}
</style>

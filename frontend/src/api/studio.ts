/** 后端数据 → 视图模型。这里是 mock 与真实书的唯一换乘点。 */
import { getJSON, postJSON, putJSON, streamPost, type StreamHandlers } from './client'
import type {
  BatchCheck,
  BibleCharacter,
  Book,
  Chapter,
  CharacterRelation,
  Discard,
  Faction,
  Foreshadow,
  GlossaryTerm,
  HistoryEvent,
  InfoGap,
  Item,
  Location,
  OutlineVolume,
  PlaceMove,
  PowerSystem,
  Rule,
  Segment,
  SocietyProfile,
  TimelineRow,
  Transfer,
  UsagePoint,
  WorldHabit,
} from '@/mocks'

export type ShelfBook = {
  dir: string
  title: string
  genre: string
  targetChapters: number
  currentChapter: number
  chapterCount: number
  updatedAt: string
}

export type PlatformOption = {
  id: string
  name: string
  wordsMin: number
  wordsMax: number
  dialogueMin: number
  short: boolean
  reader?: string
  opening?: string
  rhythm?: string
}

export type NuewenPlan = {
  text: string
  at: string
  model: string
  enabled: boolean
}

export type ConceptReversal = {
  most: string
  turns: string[]
  witness: string
  chain: string
}

/** AI 出的选题候选：书名和简介都跟着选题生成；虐文模式额外带反转结构。 */
export type Concept = {
  id: string
  title: string
  titleOptions: string[]
  genre: string
  oneLine: string
  synopsis: string
  hitRate: 'high' | 'mid' | 'low' | ''
  hitReason: string
  differentiation: string
  risk: string
  platform: string
  nuewen?: ConceptReversal | null
}

export type ConceptInput = {
  direction?: string
  genre?: string
  logline?: string
  platform?: string
  /** 必填：决定选题体量 */
  targetChapters: number
  /** 必填：决定选题体量 */
  wordsPerChapter: number
  count?: number
  avoid?: string[]
  /** true = 按「最 X → 最非 X」出虐文选题 */
  nuewen?: boolean
}

export type CreateBookInput = {
  title: string
  genre?: string
  platform?: string
  targetChapters?: number
  wordsPerChapter?: number
  logline?: string
  synopsis?: string
  theme?: string
  tone?: string
  concepts?: Concept[]
  selectedConceptId?: string
  /** 建书时一并打开虐文模式（改写/复检会套用虐文原则） */
  nuewen?: boolean
}

type ApiOverview = {
  dir: string
  title: string
  genre: string
  platform: string
  logline: string
  synopsis: string
  theme: string
  tone: string
  targetChapters: number
  currentChapter: number
  wordsPerChapter: number
  minChars: number
  segmentSize?: number
  updatedAt: string
  gate: Record<string, unknown>
  gates: Record<string, unknown>
  spine: string
  outlineText?: string
  worldText?: string
  nuewen?: boolean
  outlineAt?: string
  settingsAt?: string
  foreshadowAt?: string
  chapters: ApiChapterMeta[]
  pending: number[]
}

type ApiChapterMeta = {
  number: number
  title: string
  chars: number
  approved: boolean
  chapterVerdict: string
  endHook: { ok?: boolean; reason?: string } | null
}

type ApiChapter = {
  number: number
  title?: string
  file?: string
  chars?: number
  summary?: string
  characters?: string[]
  approved?: boolean
  verdict?: string
  chapterVerdict?: string
  fixReasons?: string[]
  endHook?: { ok?: boolean; reason?: string }
  dialogueRatio?: number
  committedAt?: string
}

type ApiCharacter = Record<string, unknown>
type ApiBible = {
  characters?: ApiCharacter[]
  world?: Array<Record<string, unknown>>
  locations?: Array<Record<string, unknown>>
  rules?: Array<Record<string, unknown>>
  factions?: Array<Record<string, unknown>>
  items?: Array<Record<string, unknown>>
  relations?: Array<Record<string, unknown>>
  infoGaps?: Array<Record<string, unknown>>
  powerSystem?: Record<string, unknown>
  society?: Record<string, unknown>
  history?: Array<Record<string, unknown>>
  glossary?: Array<Record<string, unknown>>
  style?: Record<string, unknown>
}

export type ApiPlan = {
  from: number
  to: number
  spine?: string
  stages?: Array<Record<string, unknown>>
}

export type ApiSegment = {
  from: number
  to: number
  at?: string
  spine?: string
  plan?: ApiPlan
}

type ApiForeshadow = Record<string, unknown>
type ApiTimeline = Record<string, unknown>
type ApiUsage = Record<string, unknown>
type ApiVolume = { title?: string; from?: number; to?: number }

const COLORS = ['#e0357f', '#2f5f8a', '#9a7b3f', '#2f7d5b', '#b4232c', '#7a5aa6', '#3a7f8c', '#8a5a2f']

const str = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : v == null ? fallback : String(v))
const num = (v: unknown, fallback = 0): number => {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}
const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : [])

function fmtTime(value: unknown): string {
  const s = str(value)
  if (!s) return ''
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function toneLabel(overview: ApiOverview, bible: ApiBible): string {
  const notes = str(bible.style?.notes).trim()
  if (notes) return notes.length > 28 ? `${notes.slice(0, 28)}…` : notes
  return overview.tone || ''
}

export function mapChapter(row: ApiChapter, meta?: ApiChapterMeta): Chapter {
  const title = str(row.title, meta?.title || '')
  const summary = str(row.summary)
  const characters = arr<string>(row.characters).map((x) => str(x)).filter(Boolean)
  const hook = row.endHook ?? meta?.endHook ?? null
  return {
    number: num(row.number),
    title,
    chars: num(row.chars, meta?.chars ?? 0),
    summary,
    characters,
    approved: Boolean(row.approved ?? meta?.approved),
    verdict: (row.verdict as Chapter['verdict']) || '良',
    chapterVerdict: (row.chapterVerdict || meta?.chapterVerdict || 'pass') as Chapter['chapterVerdict'],
    fixReasons: arr<string>(row.fixReasons),
    endHook: { ok: hook?.ok !== false, reason: str(hook?.reason) || undefined },
    dialogueRatio: num(row.dialogueRatio),
    searchText: [title, summary, characters.join(' ')].join(' '),
    committedAt: str(row.committedAt) || undefined,
  }
}

export function mapSegment(row: ApiSegment, chapters: Chapter[]): Segment {
  const from = num(row.from)
  const to = num(row.to)
  const plan: ApiPlan = row.plan ?? { from, to }
  const stages = arr<Record<string, unknown>>(plan.stages).map((st) => ({
    chapters: arr<number>(st.chapters).map(Number),
    goal: str(st.goal),
    turn: str(st.turn),
    foreshadow: {
      plant: arr<string>((st.foreshadow as Record<string, unknown> | undefined)?.plant),
      payoff: arr<string>((st.foreshadow as Record<string, unknown> | undefined)?.payoff),
    },
    pace: (st.pace as '紧' | '缓' | '平') || '平',
    places: arr<string>(st.places),
    cast: arr<string>(st.cast),
  }))
  const written = chapters.some((c) => c.number >= from && c.number <= to && c.chars > 0)
  const done = chapters.some((c) => c.number === to && c.approved)
  return {
    from,
    to,
    at: str(row.at),
    stages: stages.length,
    spine: str(row.spine, str(plan.spine)),
    plan: { from: num(plan.from, from), to: num(plan.to, to), spine: str(plan.spine, str(row.spine)), stages },
    status: done ? 'done' : written ? 'writing' : 'planned',
  }
}

export function mapForeshadow(row: ApiForeshadow, currentChapter: number): Foreshadow {
  const status = str(row.status, 'open') as Foreshadow['status']
  const due = row.dueChapter == null ? null : num(row.dueChapter)
  const kind = str(row.kind, 'detail')
  return {
    id: str(row.id),
    name: str(row.name),
    kind: (kind === 'main' || kind === 'volume' ? kind : 'detail') as Foreshadow['kind'],
    plantedChapter: num(row.plantedChapter),
    dueChapter: due,
    status,
    payoffChapter: row.payoffChapter == null ? undefined : num(row.payoffChapter),
    source: str(row.source) || undefined,
    plantBeat: str(row.plantBeat) || undefined,
    revealWho: str(row.revealWho) || undefined,
    revealChange: str(row.revealChange) || undefined,
    hint: str(row.hint) || undefined,
    overdue: status === 'open' && due != null && due <= currentChapter,
  }
}

function characterStatus(raw: unknown): BibleCharacter['status'] {
  const s = str(raw)
  if (/退场|exited/i.test(s)) return 'exited'
  if (/死|亡|dead/i.test(s)) return 'dead'
  if (/失踪|missing/i.test(s)) return 'missing'
  return 'active'
}

function mapMoves(raw: unknown): PlaceMove[] {
  return arr<Record<string, unknown>>(raw)
    .map((r) => ({ chapter: num(r.chapter), place: str(r.place, str(r.to)), note: str(r.note) || undefined }))
    .filter((r) => r.place)
}

function mapTransfers(raw: unknown): Transfer[] {
  return arr<Record<string, unknown>>(raw)
    .map((r) => ({ chapter: num(r.chapter), from: str(r.from) || undefined, to: str(r.to, str(r.holder)), note: str(r.note) || undefined }))
    .filter((r) => r.to)
}

function mapCharacters(bible: ApiBible, chapters: Chapter[]): BibleCharacter[] {
  return arr<ApiCharacter>(bible.characters).map((c, i) => {
    const name = str(c.name)
    const aliases = arr<string>(c.aliases)
    const appears = chapters
      .filter((ch) => ch.characters.some((x) => x === name || aliases.includes(x)))
      .map((ch) => ch.number)
    const moves = mapMoves(c.locationHistory)
    const latest = moves.length ? moves.reduce((a, b) => (b.chapter >= a.chapter ? b : a)) : null
    return {
      name,
      aliases,
      role: str(c.role, str(c.rolePosition)),
      identity: str(c.rolePosition, str(c.role)),
      importance: str(c.importance),
      tier: str(c.tier, str(c.rolePosition)),
      gender: str(c.gender),
      age: str(c.age),
      race: str(c.race),
      personality: str(c.personality),
      appearance: str(c.appearance),
      want: str(c.want),
      fear: str(c.fear),
      bottomLine: str(c.bottomLine),
      flaw: str(c.flaw),
      secret: str(c.secret),
      voice: str(c.voice),
      ability: str(c.ability),
      abilityLimit: str(c.abilityLimit),
      abilityCost: str(c.abilityCost),
      location: latest?.place || str(c.location),
      locationAt: latest ? latest.chapter : num(c.locationAt),
      locationHistory: moves,
      currentGoal: str(c.currentGoal),
      knowledge: str(c.knowledge),
      ignorance: str(c.ignorance),
      misconception: str(c.misconception),
      changeLog: str(c.changeLog),
      status: characterStatus(c.status),
      firstChapter: num(c.firstChapter),
      exitChapter: num(c.exitChapter),
      appears,
      color: COLORS[i % COLORS.length],
    }
  }).filter((c) => c.name)
}

function mapRelations(bible: ApiBible): CharacterRelation[] {
  const base = arr<Record<string, unknown>>(bible.relations).map((r) => ({
    a: str(r.a),
    b: str(r.b),
    state: str(r.state),
    note: str(r.note),
    chapter: num(r.chapter),
  })).filter((r) => r.a && r.b)
  return base
}

function mapInfoGaps(bible: ApiBible): InfoGap[] {
  return arr<Record<string, unknown>>(bible.infoGaps).map((r) => ({
    secret: str(r.secret),
    knows: str(r.knows),
    doesntKnow: str(r.doesntKnow),
    thinksKnows: str(r.thinksKnows),
    revealChapter: r.revealChapter == null ? undefined : num(r.revealChapter),
  })).filter((g) => g.secret)
}

function mapWorld(bible: ApiBible): WorldHabit[] {
  const direct = arr<Record<string, unknown>>(bible.world)
  if (direct.length) {
    return direct.map((w, i) => ({
      key: str(w.key, str(w.id, `w${i}`)),
      name: str(w.name, `设定 ${i + 1}`),
      detail: str(w.detail, str(w.text)),
    }))
  }
  return arr<Record<string, unknown>>(bible.locations).map((l, i) => ({
    key: str(l.id, str(l.name, `l${i}`)),
    name: str(l.name, `地点 ${i + 1}`),
    detail: [str(l.text), str(l.geo), str(l.structure)].filter(Boolean).join('；'),
  }))
}

const RULE_ENFORCE: Rule['enforce'][] = ['铁律', '契约', '惯例', '谣言']

function mapRuleEnforce(raw: unknown, level: unknown): Rule['enforce'] {
  const s = str(raw, str(level))
  for (const k of RULE_ENFORCE) if (s.includes(k)) return k
  if (/不可违反|硬规则|法则|定律|法律/.test(s)) return '铁律'
  if (/代价|誓约|可违反|反噬|交易/.test(s)) return '契约'
  if (/习俗|规矩|门规|潜规则|社会/.test(s)) return '惯例'
  if (/迷信|误传|传说|以为|伪/.test(s)) return '谣言'
  return '铁律'
}

function mapRules(bible: ApiBible): Rule[] {
  return arr<Record<string, unknown>>(bible.rules).map((r, i) => ({
    id: str(r.id, `r${i + 1}`),
    name: str(r.name),
    text: str(r.text, str(r.name)),
    enforce: mapRuleEnforce(r.enforce, r.level),
    enforcer: joinText(r.enforcer),
    cost: str(r.cost),
    loophole: str(r.loophole, str(r.alias) || str(r.boundary)),
    boundary: joinText(r.boundary),
    tested: str(r.tested),
    forbidden: arr<string>(r.forbiddenKeywords).length
      ? arr<string>(r.forbiddenKeywords)
      : arr<string>(r.forbidden),
  })).filter((r) => r.text)
}

function mapFactions(bible: ApiBible): Faction[] {
  const join = (v: unknown, sep = '；') => (Array.isArray(v) ? v.map((x) => str(x)).filter(Boolean).join(sep) : str(v))
  return arr<Record<string, unknown>>(bible.factions).map((f) => ({
    name: str(f.name),
    nature: str(f.nature, str(f.text)),
    openRule: join(f.openRules),
    hiddenRule: join(f.hiddenRules),
    debt: str(f.debt, join(f.relations)),
    state: str(f.state),
    stateAt: num(f.stateAt),
    attitude: str(f.attitude),
  })).filter((f) => f.name)
}

const joinText = (v: unknown, sep = '；') =>
  Array.isArray(v) ? v.map((x) => str(x)).filter(Boolean).join(sep) : str(v)

function mapLocations(bible: ApiBible): Location[] {
  return arr<Record<string, unknown>>(bible.locations).map((l, i) => ({
    id: str(l.id, str(l.name, `l${i + 1}`)),
    name: str(l.name, `地点 ${i + 1}`),
    geo: str(l.geo),
    structure: joinText(l.structure),
    senses: joinText(l.senses),
    owner: joinText(l.owner),
    accessRules: joinText(l.accessRules, '；'),
    occupied: str(l.occupied),
    state: str(l.state),
    stateAt: num(l.stateAt),
    events: str(l.events),
    familiar: str(l.familiar),
    mapX: num(l.mapX),
    mapY: num(l.mapY),
    terrain: str(l.terrain),
    text: str(l.text),
  })).filter((l) => l.name)
}

function mapItems(bible: ApiBible): Item[] {
  return arr<Record<string, unknown>>(bible.items).map((it, i) => ({
    id: str(it.id, str(it.name, `i${i + 1}`)),
    name: str(it.name, `物品 ${i + 1}`),
    aliases: arr<string>(it.aliases),
    type: str(it.type),
    appearance: str(it.appearance),
    origin: str(it.origin),
    function: joinText(it.function),
    limit: str(it.limit),
    cost: str(it.cost),
    holder: str(it.holder),
    holderAt: num(it.holderAt),
    location: str(it.location),
    state: str(it.state),
    stateAt: num(it.stateAt),
    whoKnows: str(it.whoKnows),
    transferLog: mapTransfers(it.transferLog),
    text: str(it.text),
  })).filter((it) => it.name)
}

function mapPowerSystem(bible: ApiBible): PowerSystem {
  const p = bible.powerSystem ?? {}
  return {
    name: str(p.name),
    summary: str(p.summary),
    levels: arr<Record<string, unknown>>(p.levels).map((l) => ({
      name: str(l.name),
      rank: str(l.rank),
      trait: str(l.trait),
      gap: str(l.gap),
    })).filter((l) => l.name),
    advancement: str(p.advancement),
    costs: str(p.costs),
    limits: str(p.limits),
    balance: str(p.balance),
  }
}

function mapSociety(bible: ApiBible): SocietyProfile {
  const s = bible.society ?? {}
  return {
    politics: str(s.politics),
    economy: str(s.economy),
    currency: str(s.currency),
    law: str(s.law),
    taboo: str(s.taboo),
    customs: str(s.customs),
    religion: str(s.religion),
    language: str(s.language),
    technology: str(s.technology),
  }
}

function mapHistory(bible: ApiBible): HistoryEvent[] {
  return arr<Record<string, unknown>>(bible.history).map((h) => ({
    era: str(h.era),
    year: str(h.year),
    event: str(h.event) || str(h.name),
    impact: str(h.impact),
  })).filter((h) => h.event)
}

function mapGlossary(bible: ApiBible): GlossaryTerm[] {
  return arr<Record<string, unknown>>(bible.glossary).map((g) => ({
    term: str(g.term) || str(g.name),
    meaning: str(g.meaning),
    usage: str(g.usage),
  })).filter((g) => g.term)
}

function mapOutline(volumes: ApiVolume[], chapters: Chapter[]): OutlineVolume[] {
  return volumes
    .map((v, i) => {
      const from = num(v.from, 0)
      const to = num(v.to, 0)
      const title = str(v.title, `第 ${i + 1} 卷`)
      return {
        index: i + 1,
        title: title.replace(/^第\s*\d+\s*卷\s*/, ''),
        range: [from, to] as [number, number],
        task: '',
        beats: [],
        hook: '',
        done: chapters.filter((c) => c.number >= from && c.number <= to && c.approved).length,
      }
    })
    .filter((v) => v.range[0] > 0)
    .sort((a, b) => a.range[0] - b.range[0])
}

export async function fetchForeshadows(dir: string, currentChapter: number): Promise<Foreshadow[]> {
  const data = await getJSON<{ rows: ApiForeshadow[] }>('/projects/ledger/foreshadow', { dir, folded: true })
  return arr<ApiForeshadow>(data.rows).map((f) => mapForeshadow(f, currentChapter))
}

export async function fetchShelf(): Promise<ShelfBook[]> {
  const data = await getJSON<{ books: ShelfBook[] }>('/projects')
  return arr<ShelfBook>(data.books)
}

export async function fetchNuewen(dir: string): Promise<NuewenPlan> {
  const data = await getJSON<Partial<NuewenPlan>>('/projects/nuewen', { dir })
  return {
    text: str(data.text),
    at: str(data.at),
    model: str(data.model),
    enabled: Boolean(data.enabled),
  }
}

export async function fetchPlatforms(): Promise<PlatformOption[]> {
  const data = await getJSON<{ platforms: PlatformOption[] }>('/projects/platforms')
  return arr<PlatformOption>(data.platforms)
}

/** 点「让 AI 出选题」：模型按方向/题材/卖点出候选，书名和简介都跟着选题一起生成。 */
export async function generateConcepts(input: ConceptInput): Promise<Concept[]> {
  const data = await postJSON<{ concepts: Concept[] }>('/projects/concepts', input)
  return arr<Concept>(data.concepts).map((c) => ({
    ...c,
    titleOptions: arr<string>(c.titleOptions),
    hitRate: (c.hitRate === 'high' || c.hitRate === 'mid' || c.hitRate === 'low' ? c.hitRate : ''),
  }))
}

export type BlueprintResult = {
  outlineText: string
  worldText: string
  volumes: Array<{ title?: string; from?: number; to?: number }>
  targetChapters: number
  maxChapterSeen: number
  warning: string
  model: string
  at: string
}

export type SettingsResult = {
  ok: boolean
  added: Record<string, number>
  skipped: Record<string, number>
  /** 已有条目补了几个空字段（不覆盖原值）。 */
  filled?: Record<string, number>
  total: number
  summary: string
  model: string
}

export type ForeshadowGenResult = {
  ok: boolean
  asked: number
  planned: number
  count: number
  skipped: number
  guarded: number
  summary: string
  model: string
}

export type GenerateChapterResult = {
  ok: boolean
  chapter: ApiChapter & { number: number }
  outline: {
    chapter: number
    title: string
    beats: string[]
    mustInclude: string[]
    mustAvoid: string[]
    openingState: string
    endingState: string
    detail: string
  }
  text: string
  chars: number
  model: string
}

/** 选题之后：由梗概一次生成大纲 + 世界观。 */
export async function generateBlueprint(
  dir: string,
  nuewen?: boolean,
  handlers?: StreamHandlers,
): Promise<BlueprintResult> {
  if (handlers) {
    return streamPost<BlueprintResult>('/projects/blueprint/stream', { nuewen }, handlers, { dir })
  }
  return postJSON<BlueprintResult>('/projects/blueprint', { nuewen }, { dir })
}

/** 由大纲 + 世界观拆出人物 / 势力 / 地点 / 物品 / 规则 / 文风。 */
export async function generateSettings(
  dir: string,
  handlers?: StreamHandlers,
): Promise<SettingsResult> {
  if (handlers) {
    return streamPost<SettingsResult>('/projects/settings/stream', {}, handlers, { dir })
  }
  return postJSON<SettingsResult>('/projects/settings', {}, { dir })
}

export type SupplementResult = {
  ok: boolean
  added: Record<string, number>
  skipped: Record<string, number>
  /** 已有条目补了几个空字段（不覆盖原值）。 */
  filled?: Record<string, number>
  total: number
  chapters: number[]
  summary: string
  model: string
}

/** 写完一批后：只把正文里新出现、设定里还没有的内容补进去，同名/别名一律跳过。 */
export async function supplementSettings(
  dir: string,
  opts: { recent?: number; model?: string | null } = {},
  handlers?: StreamHandlers,
): Promise<SupplementResult> {
  const body = { recent: opts.recent ?? 8, model: opts.model ?? null }
  if (handlers) {
    return streamPost<SupplementResult>('/projects/settings/supplement/stream', body, handlers, { dir })
  }
  return postJSON<SupplementResult>('/projects/settings/supplement', body, { dir })
}

export type BookSettingsPatch = { minChars?: number; segmentSize?: number }

/** 设置页「写作与存档」的可改项；只写这几个字段，不碰别的项目配置。 */
export async function saveBookSettings(
  dir: string,
  patch: BookSettingsPatch,
): Promise<{ ok: boolean; minChars: number; segmentSize: number }> {
  return putJSON('/projects/book', patch, { dir })
}

/** 由大纲 + 世界观 + 设定设计整套伏笔。 */
export async function generateForeshadows(
  dir: string,
  handlers?: StreamHandlers,
): Promise<ForeshadowGenResult> {
  if (handlers) {
    return streamPost<ForeshadowGenResult>('/projects/foreshadow/generate/stream', {}, handlers, { dir })
  }
  return postJSON<ForeshadowGenResult>('/projects/foreshadow/generate', {}, { dir })
}

/** 写一章：先出细纲，再照细纲写正文。 */
export async function generateChapter(
  dir: string,
  number: number,
  options: { overwrite?: boolean; reuseOutline?: boolean } = {},
): Promise<GenerateChapterResult> {
  return postJSON<GenerateChapterResult>(
    `/projects/chapters/${number}/generate`,
    { overwrite: Boolean(options.overwrite), reuseOutline: options.reuseOutline !== false },
    { dir },
  )
}

export async function fetchBook(dir: string): Promise<{
  book: Book
  chapters: Chapter[]
  segments: Segment[]
  foreshadows: Foreshadow[]
  characters: BibleCharacter[]
  relations: CharacterRelation[]
  infoGaps: InfoGap[]
  world: WorldHabit[]
  rules: Rule[]
  factions: Faction[]
  locations: Location[]
  items: Item[]
  powerSystem: PowerSystem
  society: SocietyProfile
  history: HistoryEvent[]
  glossary: GlossaryTerm[]
  outline: OutlineVolume[]
  timeline: TimelineRow[]
  usage: UsagePoint[]
  discarded: Discard[]
  nuewen: NuewenPlan
}> {
  const [overview, index, bible, segmentRows, foreshadowRows, timelineRows, usageRows, discarded, volumeRows, nuewen] =
    await Promise.all([
      getJSON<ApiOverview>('/projects/overview', { dir }),
      getJSON<{ chapters: ApiChapter[] }>('/projects/chapters', { dir }),
      getJSON<{ bible: ApiBible }>('/projects/bible', { dir }),
      getJSON<{ rows: ApiSegment[] }>('/projects/ledger/segments', { dir, folded: true }),
      getJSON<{ rows: ApiForeshadow[] }>('/projects/ledger/foreshadow', { dir, folded: true }),
      getJSON<{ rows: ApiTimeline[] }>('/projects/ledger/timeline', { dir, folded: true }),
      getJSON<{ rows: ApiUsage[] }>('/projects/ledger/usage', { dir }),
      getJSON<{ rows: Discard[] }>('/projects/discarded', { dir }),
      getJSON<{ volumes: ApiVolume[] }>('/projects/volumes', { dir }),
      fetchNuewen(dir),
    ])

  const meta = new Map(arr<ApiChapterMeta>(overview.chapters).map((c) => [c.number, c]))
  const chapters = arr<ApiChapter>(index.chapters)
    .map((row) => mapChapter(row, meta.get(num(row.number))))
    .sort((a, b) => a.number - b.number)

  const gate = {
    phase: str(overview.gate?.phase, 'writing'),
    chapter: num(overview.gate?.chapter, overview.currentChapter + 1),
    reason: str(overview.gate?.reason),
    at: fmtTime(overview.gate?.at),
  }
  const book: Book = {
    dir: overview.dir || dir,
    title: overview.title,
    genre: overview.genre,
    platform: overview.platform || '通用',
    logline: overview.logline,
    synopsis: overview.synopsis,
    theme: overview.theme || overview.spine || overview.logline,
    targetChapters: num(overview.targetChapters),
    currentChapter: num(overview.currentChapter),
    wordsPerChapter: num(overview.wordsPerChapter),
    minChars: num(overview.minChars, 1800),
    segmentSize: Math.max(3, num(overview.segmentSize, 10)),
    tone: toneLabel(overview, bible.bible || {}),
    gate,
    gates: Object.fromEntries(Object.entries(overview.gates || {}).map(([k, v]) => [k, Boolean(v)])),
    updatedAt: fmtTime(overview.updatedAt),
    spine: overview.spine || '',
    outlineText: str(overview.outlineText),
    worldText: str(overview.worldText),
    nuewen: Boolean(overview.nuewen),
  }

  return {
    book,
    chapters,
    segments: arr<ApiSegment>(segmentRows.rows).map((s) => mapSegment(s, chapters)),
    foreshadows: arr<ApiForeshadow>(foreshadowRows.rows).map((f) => mapForeshadow(f, book.currentChapter)),
    characters: mapCharacters(bible.bible || {}, chapters),
    relations: mapRelations(bible.bible || {}),
    infoGaps: mapInfoGaps(bible.bible || {}),
    world: mapWorld(bible.bible || {}),
    rules: mapRules(bible.bible || {}),
    factions: mapFactions(bible.bible || {}),
    locations: mapLocations(bible.bible || {}),
    items: mapItems(bible.bible || {}),
    powerSystem: mapPowerSystem(bible.bible || {}),
    society: mapSociety(bible.bible || {}),
    history: mapHistory(bible.bible || {}),
    glossary: mapGlossary(bible.bible || {}),
    outline: mapOutline(arr<ApiVolume>(volumeRows.volumes), chapters),
    timeline: arr<ApiTimeline>(timelineRows.rows).map((r) => ({
      chapter: num(r.chapter),
      inWorldDay: num(r.inWorldDay),
      summary: str(r.summary),
    })),
    usage: arr<ApiUsage>(usageRows.rows).map((u) => ({
      at: str(u.at),
      kind: str(u.kind),
      chapter: num(u.chapter),
      tokens: num(u.tokens),
      verdict: str(u.verdict) || undefined,
      rejected: Boolean(u.rejected),
    })),
    discarded: arr<Discard>(discarded.rows),
    nuewen,
  }
}

export type ApiBatch = BatchCheck

// ---- 切片 1：文风 / 写作技能 / 分步写作 / 批量存档 ----

export type ApiStyle = {
  version?: number
  pov?: string
  person?: string
  sentence?: string
  paragraph?: string
  rhythm?: string
  dialogueRatio?: string
  banned?: string[]
  samples?: Array<string | { text: string; label?: string; note?: string; origin?: string }>
  references?: Array<string | { author?: string; work?: string; note?: string }>
  notes?: string
  presetId?: string
}

export type StylePreset = {
  id: string
  name: string
  kind: 'prose' | 'prose+advisor'
  advisor: boolean
  summary: string
  traits: string[]
  fields: ApiStyle
  /** 预设自带的代表性样章（带出处 note），选预设且本书没有样章时补入。 */
  samples?: Array<{ text: string; label?: string; note?: string; origin?: string }>
  applicable: boolean
}

export type WritingSkills = {
  deai: boolean
  dialogue: boolean
  scene: boolean
  hook: boolean
  continuity: boolean
  platform: boolean
  nuewen: boolean
  styleSamples: boolean
}

export type StyleApplied = {
  source: 'platform' | 'book' | 'book+override'
  effective: ApiStyle
}

export type FocusItem = { type: string; key: string; label: string }

export type OutlineResult = {
  ok: boolean
  chapter: number
  outline: Record<string, unknown>
  styleApplied: StyleApplied
  model?: string
  reused: boolean
}

export type MemoryWriteBack = {
  ok: boolean
  skipped?: boolean
  reason?: string
  error?: string
  volumeError?: string
  chapter?: { chapter: number; summary: string; timelineCount?: number; skipped?: boolean }
  volume?: { volume: number; summary: string; skipped?: boolean }
}

export type ProseResult = {
  ok: boolean
  chapter: Record<string, unknown>
  text: string
  chars: number
  styleApplied: StyleApplied
  backupDraft?: string
  model?: string
  /** 正文落盘后 AI 自动回写的本章/本卷记忆。 */
  memory?: MemoryWriteBack
}

export type ArchiveBatchResult = {
  ok: boolean
  results: Array<{
    number: number
    ok: boolean
    error?: string
    code?: string
    findings?: unknown[]
    approved?: number
    skipped?: boolean
  }>
  approvedCount: number
  failedCount: number
}

export type FetchStyleResult = {
  style: ApiStyle
  defaults: ApiStyle
  source: string
  autoGenerated?: boolean
}

export type SaveStyleResult = { ok: boolean; style: ApiStyle; updatedAt?: string }
export type FetchPresetsResult = { presets: StylePreset[] }
export type ApplyPresetResult = { ok: boolean; style: ApiStyle; preset: StylePreset }
export type FetchSkillsResult = {
  skills: WritingSkills
  availability?: Record<string, { enabled: boolean; reason?: string }>
  updatedAt?: string
}
export type SaveSkillsResult = { ok: boolean; skills: WritingSkills; updatedAt?: string }

export type OutlineOptions = {
  force?: boolean
  styleOverride?: Partial<ApiStyle>
  skills?: Partial<WritingSkills>
  focus?: FocusItem[]
  model?: string
  runId?: string
}

export type ProseOptions = {
  overwrite?: boolean
  styleOverride?: Partial<ApiStyle>
  skills?: Partial<WritingSkills>
  focus?: FocusItem[]
  model?: string
  runId?: string
}

/** 书默认文风（v2）+ 平台默认值；缺字段按空对象处理，不阻塞页面。 */
export async function fetchStyle(dir: string): Promise<FetchStyleResult> {
  const data = await getJSON<Partial<FetchStyleResult>>('/projects/style', { dir })
  return {
    style: data.style ?? {},
    defaults: data.defaults ?? {},
    source: str(data.source),
    autoGenerated: Boolean(data.autoGenerated),
  }
}

/** 部分合并：只提交要改的字段，未提交字段保持原值。 */
export async function saveStyle(dir: string, patch: Partial<ApiStyle>): Promise<SaveStyleResult> {
  return putJSON<SaveStyleResult>('/projects/style', { style: patch }, { dir })
}

export async function fetchStylePresets(): Promise<FetchPresetsResult> {
  const data = await getJSON<{ presets?: StylePreset[] }>('/projects/style/presets')
  return { presets: arr<StylePreset>(data.presets) }
}

/** 套用作家文风预设：默认只补空字段，overwrite=true 时覆盖预设维度。 */
export async function applyStylePreset(
  dir: string,
  id: string,
  overwrite = false,
): Promise<ApplyPresetResult> {
  return postJSON<ApplyPresetResult>('/projects/style/preset', { id, overwrite: Boolean(overwrite) }, { dir })
}

export async function fetchWritingSkills(dir: string): Promise<FetchSkillsResult> {
  const data = await getJSON<Partial<FetchSkillsResult>>('/projects/writing-skills', { dir })
  return {
    skills: data.skills ?? defaultSkills(),
    availability: data.availability,
    updatedAt: str(data.updatedAt) || undefined,
  }
}

/** 只合并传入的技能键；书默认，不影响正在运行的批次。 */
export async function saveWritingSkills(
  dir: string,
  patch: Partial<WritingSkills>,
): Promise<SaveSkillsResult> {
  return putJSON<SaveSkillsResult>('/projects/writing-skills', { skills: patch }, { dir })
}

/** 只生成细纲；已有可用细纲且 force=false 时复用（reused=true）。 */
export async function generateOutline(
  dir: string,
  n: number,
  opts: OutlineOptions = {},
  handlers?: StreamHandlers,
): Promise<OutlineResult> {
  const body = {
    force: Boolean(opts.force),
    styleOverride: opts.styleOverride ?? null,
    skills: opts.skills ?? null,
    focus: arr<FocusItem>(opts.focus),
    model: opts.model ?? null,
    runId: opts.runId ?? null,
  }
  if (handlers) {
    return streamPost<OutlineResult>(`/projects/chapters/${n}/outline/stream`, body, handlers, { dir })
  }
  return postJSON<OutlineResult>(`/projects/chapters/${n}/outline`, body, { dir })
}

/** 照细纲写正文；成功落盘为待确认，覆盖时旧稿进 drafts。 */
export async function generateProse(
  dir: string,
  n: number,
  opts: ProseOptions = {},
  handlers?: StreamHandlers,
): Promise<ProseResult> {
  const body = {
    overwrite: Boolean(opts.overwrite),
    styleOverride: opts.styleOverride ?? null,
    skills: opts.skills ?? null,
    focus: arr<FocusItem>(opts.focus),
    model: opts.model ?? null,
    runId: opts.runId ?? null,
  }
  if (handlers) {
    return streamPost<ProseResult>(`/projects/chapters/${n}/prose/stream`, body, handlers, { dir })
  }
  return postJSON<ProseResult>(`/projects/chapters/${n}/prose`, body, { dir })
}

/** 批量存档：整批 200，单章失败不影响其他章；已存档章返回 skipped。 */
export async function archiveBatch(
  dir: string,
  numbers: number[],
  force = false,
): Promise<ArchiveBatchResult> {
  return postJSON<ArchiveBatchResult>(
    '/projects/archive-batch',
    { numbers: arr<number>(numbers).map(Number), force: Boolean(force) },
    { dir },
  )
}

function defaultSkills(): WritingSkills {
  return {
    deai: true,
    dialogue: true,
    scene: true,
    hook: true,
    continuity: true,
    platform: true,
    nuewen: false,
    styleSamples: true,
  }
}

// ---- 记忆页：时间线 / 前情账 / 关键词回查 ----

export type MemoryChapter = {
  chapter: number
  title: string
  summary: string
  characters: string[]
  events: string[]
  storyTime: string
  /** 本章是否以回忆 / 倒叙为主；回忆章的故事时间不是当下。 */
  isFlashback: boolean
  at: string
}

export type MemoryVolume = {
  volume: number
  title: string
  from: number
  to: number
  summary: string
  dims: Record<string, string>
  /** 后端当前不返回生成时间；有就显示，没有就不显示，不编造。 */
  at?: string
}

export type MemoryTimelineEvent = {
  chapter: number
  storyTime: string
  place: string
  characters: string[]
  event: string
  kind: string
  /** 这条事件发生在过去（回忆 / 旧事重提），不是本章的当下时间。 */
  flashback: boolean
  revealChapter: number | null
}

export type MemoryRelation = { a: string; b: string; state: string; chapter: number }

export type MemoryCharacter = { name: string; state: string; chapter: number }

export type MemoryCoverage = {
  chaptersWithText: number
  chaptersWithMemory: number
  volumes: number
  volumesWithMemory: number
  missing: number[]
}

export type MemoryOverview = {
  coverage: MemoryCoverage
  chapters: MemoryChapter[]
  volumes: MemoryVolume[]
  timeline: MemoryTimelineEvent[]
  relations: MemoryRelation[]
  characters: MemoryCharacter[]
}

export type MemoryRecallHit = { chapter: number; title: string; text: string; score: number }

export type MemoryGenResult = {
  ok?: boolean
  skipped?: boolean
  chapter?: number
  summary?: string
  characters?: string[]
  events?: string[]
  timelineCount?: number
  total?: number
  failed?: Array<{ chapter: number; error: string }>
  volume?: number
  title?: string
  from?: number
  to?: number
  dims?: Record<string, string>
}

export type MemoryGenOptions = { force?: boolean; model?: string }

/** 记忆页整包：覆盖度 + 章/卷记忆 + 时间线 + 关系 + 人物状态。只读，不调模型。 */
export async function fetchMemoryOverview(dir: string): Promise<MemoryOverview> {
  const data = await getJSON<Partial<MemoryOverview>>('/projects/memory', { dir })
  const coverage = (data.coverage ?? {}) as Partial<MemoryCoverage>
  return {
    coverage: {
      chaptersWithText: num(coverage.chaptersWithText),
      chaptersWithMemory: num(coverage.chaptersWithMemory),
      volumes: num(coverage.volumes),
      volumesWithMemory: num(coverage.volumesWithMemory),
      missing: arr<unknown>(coverage.missing)
        .map((n) => num(n))
        .filter((n) => n > 0)
        .sort((a, b) => a - b),
    },
    chapters: arr<Record<string, unknown>>(data.chapters).map((row) => ({
      chapter: num(row.chapter),
      title: str(row.title),
      summary: str(row.summary),
      characters: arr<string>(row.characters),
      events: arr<string>(row.events),
      storyTime: str(row.storyTime),
      isFlashback: Boolean(row.isFlashback),
      at: str(row.at),
    })),
    volumes: arr<Record<string, unknown>>(data.volumes).map((row) => ({
      volume: num(row.volume),
      title: str(row.title),
      from: num(row.from),
      to: num(row.to),
      summary: str(row.summary),
      dims: (row.dims && typeof row.dims === 'object' ? row.dims : {}) as Record<string, string>,
      at: str(row.at) || undefined,
    })),
    timeline: arr<Record<string, unknown>>(data.timeline).map((row) => ({
      chapter: num(row.chapter),
      storyTime: str(row.storyTime),
      place: str(row.place),
      characters: arr<string>(row.characters),
      event: str(row.event),
      kind: str(row.kind, 'event'),
      flashback: Boolean(row.flashback),
      revealChapter: row.revealChapter == null ? null : num(row.revealChapter),
    })),
    relations: arr<Record<string, unknown>>(data.relations).map((row) => ({
      a: str(row.a),
      b: str(row.b),
      state: str(row.state),
      chapter: num(row.chapter),
    })),
    characters: arr<Record<string, unknown>>(data.characters).map((row) => ({
      name: str(row.name),
      state: str(row.state),
      chapter: num(row.chapter),
    })),
  }
}

/** 从第 n 章正文提炼章记忆 + 时间线；已有记忆且 force=false 时后端返回 skipped。 */
export async function generateMemoryChapter(
  dir: string,
  chapter: number,
  opts: MemoryGenOptions = {},
): Promise<MemoryGenResult> {
  return postJSON<MemoryGenResult>(
    `/projects/memory/chapter/${chapter}/generate`,
    { force: Boolean(opts.force), model: opts.model ?? null },
    { dir },
  )
}

/** 按卷生成卷摘要 + 六维；已有同范围卷记忆且 force=false 时后端返回 skipped。 */
export async function generateMemoryVolume(
  dir: string,
  idx: number,
  opts: MemoryGenOptions = {},
): Promise<MemoryGenResult> {
  return postJSON<MemoryGenResult>(
    `/projects/memory/volume/${idx}/generate`,
    { force: Boolean(opts.force), model: opts.model ?? null },
    { dir },
  )
}

/** 批量补章记忆。from/to 缺省时后端从第一个缺记忆的章补到 currentChapter。 */
export async function generateMemoryBatch(
  dir: string,
  opts: MemoryGenOptions & { from?: number; to?: number } = {},
): Promise<MemoryGenResult> {
  return postJSON<MemoryGenResult>(
    '/projects/memory/generate',
    {
      from: opts.from ?? null,
      to: opts.to ?? null,
      force: Boolean(opts.force),
      model: opts.model ?? null,
    },
    { dir },
  )
}

/** 关键词回查：正文切片 + 记忆事件/摘要，带章号出处。 */
export async function recallMemory(
  dir: string,
  q: string,
  opts: { from?: number; to?: number } = {},
): Promise<MemoryRecallHit[]> {
  const data = await getJSON<{ hits?: unknown }>('/projects/memory/recall', {
    dir,
    q,
    from: opts.from ?? undefined,
    to: opts.to ?? undefined,
  })
  return arr<Record<string, unknown>>(data.hits).map((row) => ({
    chapter: num(row.chapter),
    title: str(row.title),
    text: str(row.text),
    score: num(row.score),
  }))
}

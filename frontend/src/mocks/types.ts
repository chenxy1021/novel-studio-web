// Shared shapes between mocks and real API responses. Field names follow the book format
// (chapters/index.json entries, ledger rows) so swap-in is a data-source change, not a rewrite.

export type Severity = 'high' | 'mid' | 'info'

export interface Chapter {
  number: number
  title: string
  chars: number
  summary: string
  characters: string[]
  approved: boolean
  verdict: '良' | '中' | '差'
  chapterVerdict: 'pass' | 'needs_fix'
  fixReasons: string[]
  endHook: { ok: boolean; reason?: string }
  dialogueRatio: number
  searchText: string
  /** ISO 时间；真实书用来算「今日字数 / 连续写作」，mock 没有就留空。 */
  committedAt?: string
}

export interface Finding {
  severity: Severity
  code: string
  message: string
  hint?: string
  chapter?: number
}

export interface ChapterCheck {
  number: number
  pass: boolean
  findings: Finding[]
  canRewrite: boolean
}

export interface BatchCheck {
  from: number
  to: number
  chapters: ChapterCheck[]
  blocking: Finding[]
  checkedAt: string
}

export interface SegmentStage {
  chapters: number[]
  goal: string
  turn: string
  foreshadow: { plant: string[]; payoff: string[] }
  pace: '紧' | '缓' | '平'
  places: string[]
  cast: string[]
}

/** Same shape as app/domain/segment.py list_segments(). `stages` is the count;
 *  the stage bodies live in `plan.stages` (plan.spine mirrors `spine`). */
export interface SegmentPlan {
  from: number | null
  to: number | null
  spine: string
  stages: SegmentStage[]
}

export interface Segment {
  from: number
  to: number
  at: string
  stages: number
  spine: string
  plan: SegmentPlan
  /** UI-only: not in API. done = last chapter written, writing = gate inside, planned = nothing written. */
  status: 'done' | 'writing' | 'planned'
}

export function segmentStages(s: Segment): SegmentStage[] {
  return s.plan?.stages ?? []
}

export interface Foreshadow {
  id: string
  name: string
  kind: 'main' | 'volume' | 'detail'
  plantedChapter: number
  dueChapter: number | null
  status: 'open' | 'paid' | 'abandoned'
  payoffChapter?: number
  source?: string
  plantBeat?: string
  revealWho?: string
  revealChange?: string
  hint?: string
  overdue?: boolean
}

/** 人物的一次位置变化；chapter 为 0 表示老数据没记章号。 */
export interface PlaceMove {
  chapter: number
  place: string
  note?: string
}

/** 人物关系底稿（bible.relations）+ 章记忆里汇总的最新状态（ledger/relations）。 */
export interface CharacterRelation {
  a: string
  b: string
  state: string
  note: string
  /** 关系状态截至第几章；bible 底稿没有章号时为 0。 */
  chapter: number
}

/** 信息差：谁知道、谁不知道、谁以为自己知道。 */
export interface InfoGap {
  secret: string
  knows: string
  doesntKnow: string
  thinksKnows: string
  revealChapter?: number
}

export interface BibleCharacter {
  name: string
  aliases: string[]
  role: string
  identity: string
  /** 核心 / 主要 / 次要 / 龙套 */
  importance: string
  /** 主角 / 女主 / 反派 / 常驻配角 / 单卷配角 / 工具人 */
  tier: string
  gender: string
  age: string
  race: string
  personality: string
  appearance: string
  want: string
  fear: string
  bottomLine: string
  flaw: string
  secret: string
  voice: string
  ability: string
  abilityLimit: string
  abilityCost: string
  /** 当前位置（配合 locationAt 章号使用，防人物漂移）。 */
  location: string
  locationAt: number
  locationHistory: PlaceMove[]
  currentGoal: string
  knowledge: string
  ignorance: string
  misconception: string
  changeLog: string
  status: 'active' | 'dead' | 'missing' | 'exited'
  firstChapter: number
  exitChapter: number
  appears: number[]
  color: string
}

export interface WorldHabit {
  key: string
  name: string
  detail: string
}

/** 力量 / 能力体系的一级台阶：修行、异能、魔法、科技分级都按这个结构。 */
export interface PowerLevel {
  name: string
  rank: string
  trait: string
  /** 和上一级的差距：为什么这一级打不过上一级。 */
  gap: string
}

export interface PowerSystem {
  name: string
  summary: string
  levels: PowerLevel[]
  advancement: string
  costs: string
  limits: string
  balance: string
}

/** 社会常识：正文里用来区分阶层、地域、冲突的那一层。 */
export interface SocietyProfile {
  politics: string
  economy: string
  currency: string
  law: string
  taboo: string
  customs: string
  religion: string
  language: string
  technology: string
}

/** 世界大事记：影响当下格局的历史事件，不是编年流水账。 */
export interface HistoryEvent {
  era: string
  year: string
  event: string
  impact: string
}

/** 术语表：专有名词的统一叫法与正文用法，防止同物异名。 */
export interface GlossaryTerm {
  term: string
  meaning: string
  usage: string
}

/** 规则按「可违反程度」分四类：铁律破不了；契约能破但付代价；惯例违反有社会代价；谣言其实不成立。 */
export type RuleEnforce = '铁律' | '契约' | '惯例' | '谣言'

export interface Rule {
  id: string
  name: string
  text: string
  enforce: RuleEnforce
  /** 谁在执行 / 监督这条规则。 */
  enforcer: string
  cost: string
  loophole: string
  boundary: string
  tested: string
  forbidden: string[]
}

export interface Faction {
  name: string
  nature: string
  openRule: string
  hiddenRule: string
  debt: string
  /** 当前状态与截至章：势力会随剧情兴衰，不能只写静态介绍。 */
  state: string
  stateAt: number
  /** 对主角的当前态度。 */
  attitude: string
}

/** 地点：地图节点 + 进出规矩。字段与 bible.locations 对齐。 */
export interface Location {
  id: string
  name: string
  geo: string
  structure: string
  senses: string
  owner: string
  accessRules: string
  occupied: string
  state: string
  /** 状态截至第几章；0 表示底稿没有章号。 */
  stateAt: number
  events: string
  familiar: string
  /** 地图坐标（0–100：西→东、北→南）；0 表示没标，地图会按文字方位推断。 */
  mapX: number
  mapY: number
  /** 地形：城 / 镇 / 村 / 山林 / 水岸 / 废墟 / 关隘 / 营地。 */
  terrain: string
  text: string
}

/** 物品的一次转手；chapter 为 0 表示老数据没记章号。 */
export interface Transfer {
  chapter: number
  from?: string
  to: string
  note?: string
}

/** 物品：会被再次提到 / 使用 / 追查的东西。持有人与状态带章号，防止物品瞬移。 */
export interface Item {
  id: string
  name: string
  aliases: string[]
  type: string
  appearance: string
  origin: string
  function: string
  limit: string
  cost: string
  holder: string
  holderAt: number
  location: string
  state: string
  stateAt: number
  whoKnows: string
  transferLog: Transfer[]
  text: string
}

export interface Discard {
  number: number
  title: string
  reason: string
  chars: number
  at: string
  draftFile: string
  lead: string
}

export interface OutlineVolume {
  index: number
  title: string
  range: [number, number]
  task: string
  beats: string[]
  hook: string
  done: number
}

export interface Book {
  dir: string
  title: string
  genre: string
  platform: string
  logline: string
  synopsis: string
  theme: string
  targetChapters: number
  currentChapter: number
  wordsPerChapter: number
  minChars: number
  /** 批量写作一段多少章（段落纲的跨度）；存 project.json。 */
  segmentSize: number
  tone: string
  gate: { phase: string; chapter: number; reason: string; at: string }
  gates: Record<string, boolean>
  updatedAt: string
  spine: string
  /** 生成的大纲 / 世界观正文；新书在开书流程里逐步补齐。 */
  outlineText?: string
  worldText?: string
  /** 建书时勾选的虐文模式。 */
  nuewen?: boolean
}

export interface UsagePoint {
  at: string
  kind: string
  chapter: number
  tokens: number
  verdict?: string
  rejected?: boolean
}

export interface TimelineRow {
  chapter: number
  inWorldDay: number
  summary: string
}

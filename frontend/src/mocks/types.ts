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

export interface BibleCharacter {
  name: string
  role: string
  identity: string
  want: string
  fear: string
  secret: string
  voice: string
  status: 'active' | 'dead' | 'missing'
  appears: number[]
  color: string
}

export interface WorldHabit {
  key: string
  name: string
  detail: string
}

export interface Rule {
  id: string
  text: string
  cost: string
  loophole: string
  tested: string
  forbidden: string[]
}

export interface Faction {
  name: string
  nature: string
  openRule: string
  hiddenRule: string
  debt: string
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
  tone: string
  gate: { phase: string; chapter: number; reason: string; at: string }
  gates: Record<string, boolean>
  updatedAt: string
  spine: string
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

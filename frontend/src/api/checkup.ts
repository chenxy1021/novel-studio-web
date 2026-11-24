/** 体检与按技能改写的 API 形状。确定性体检和语义复检分开，前端不合并成一个黑箱。 */
import { getJSON, postJSON, streamPost, type StreamHandlers } from './client'
import type { Finding } from './client'

export type TellSample = {
  text: string
  line: number
  paragraph: number
  offset: number
}

export type TellCategory = {
  id: string
  label: string
  severity: 'high' | 'mid' | 'low'
  count: number
  per1000: number
  samples: TellSample[]
}

export type AiTells = {
  level: string
  total: number
  density: number
  verdict?: { level: string; density: number; high: number; mid: number; flatRhythm: boolean }
  categories: TellCategory[]
}

export type RuleCheck = {
  id: string
  label: string
  state: 'ok' | 'warn' | 'bad'
  value: number | string | null
  limit: number | string | null
  message: string
}

export type CheckResult = {
  number: number
  pass: boolean
  findings: Finding[]
  canRewrite: boolean
  chars: number
  dialogueRatio: number
  endHook: { ok: boolean; reason?: string }
  verdict: { level: string; density: number; high: number; mid: number; flatRhythm: boolean }
  aiTells: AiTells
  rules: RuleCheck[]
  checkedAt: string
  textHash: string
  suggestedSkills: string[]
}

export type AiGroup = {
  code: string
  label: string
  count: number
  findings: Finding[]
}

export type ChecklistState = 'pass' | 'fail' | 'skip' | 'resolved'

/** 固定清单的一项：AI 只判这些，判不过才算硬伤。 */
export type ChecklistItem = {
  id: string
  label: string
  state: ChecklistState
}

export type AiCheckResult = CheckResult & {
  model?: string
  groups: AiGroup[]
  /** 这次复检逐项判定的固定清单（细纲 / 前情 / 章内 / 视角）。 */
  checklist?: ChecklistItem[]
  /** 这次复检对照了哪些跨章材料（前情章数、上一章结尾、本章细纲）。 */
  context?: { priorChapters: number; prevTail: boolean; outline: boolean }
  /** 按固定清单给出的结论：fail 才需要重写，minor 只是建议，pass 可以存档。 */
  standard?: {
    verdict: 'fail' | 'minor' | 'pass'
    high: number
    mid: number
    /** 因给不出原句/细纲依据而未被计入的条数。 */
    filtered: number
    /** 清单项总数与各状态数量。 */
    items?: number
    passed?: number
    failed?: number
    skipped?: number
    resolved?: number
    note: string
  }
  /** 模型思考过程；流式显示过，收尾留一份方便回看。 */
  thinking?: string
  /** 正文/前情/细纲都没变，结论沿用上次复检（没有重新调模型）。 */
  cached?: boolean
  /** 这一章还在同一轮复检里：返回的是修完剩下的条目，没有重新扫。 */
  carried?: boolean
  /** 复检轮次 id；一轮里改掉的条目不会再回来，直到整章改写或重扫。 */
  round?: string
  roundAt?: string
  /** 本轮已经确认解决的条数。 */
  resolvedCount?: number
}

/** 后端缓存的最近一次确定性体检；stale 表示体检后正文又改过。 */
export type SavedCheck = {
  chapter: number
  at: string
  stale: boolean
  result: CheckResult
}

export async function fetchChecks(dir: string): Promise<SavedCheck[]> {
  const res = await getJSON<{ rows: SavedCheck[] }>('/projects/checks', { dir })
  return res.rows ?? []
}

export type RewriteResult = {
  ok: boolean
  chapter: Record<string, unknown>
  text: string
  chars: number
  model: string
  check: CheckResult
  skills: string[]
  aiTellsBefore: { total: number; level: string; density: number }
  aiTellsAfter: { total: number; level: string; density: number }
  oldChars: number
  newChars: number
}

export type ParagraphRewriteOptions = {
  paragraph: number
  instruction?: string
  model?: string | null
  finding?: {
    severity?: string
    code?: string
    message?: string
    hint?: string
    source?: string
    quote?: string
    basis?: string
    paragraph?: number
  }
}

export type ParagraphRewriteResult = {
  ok: boolean
  number: number
  paragraph: number
  chapter: Record<string, unknown>
  text: string
  oldParagraph: string
  paragraphText: string
  chars: number
  model: string
  check: CheckResult
  /** 原句已经不在正文里：这条问题算解决，可以从面板上摘掉。 */
  resolved: boolean
}

export async function fetchRewriteParagraph(
  dir: string,
  number: number,
  opts: ParagraphRewriteOptions,
  handlers?: StreamHandlers,
): Promise<ParagraphRewriteResult> {
  const body = {
    paragraph: opts.paragraph,
    instruction: opts.instruction ?? '',
    model: opts.model ?? null,
    finding: opts.finding ?? null,
  }
  return streamPost<ParagraphRewriteResult>(
    `/projects/chapters/${number}/rewrite-paragraph/stream`,
    body,
    handlers,
    { dir },
  )
}

export type RewriteOptions = {
  reason?: string
  instruction?: string
  model?: string | null
  skills?: string[] | null
  /** 屏幕上正看着的检查问题（确定性 + AI 复检），改写时一起交给模型。 */
  findings?: Array<{ severity: string; code?: string; message: string; hint?: string; source?: string }>
}

export async function fetchChapterCheck(dir: string, number: number): Promise<CheckResult> {
  return getJSON<CheckResult>(`/projects/chapters/${number}/check`, { dir })
}

export async function fetchAiCheck(dir: string, number: number, model?: string): Promise<AiCheckResult> {
  return postJSON<AiCheckResult>(
    `/projects/chapters/${number}/ai-check`,
    model ? { model } : {},
    { dir },
  )
}

/** 复检并实时显示思考过程；完成后 payload 与同步接口一致。 */
export async function fetchAiCheckStream(
  dir: string,
  number: number,
  model: string | undefined,
  handlers?: StreamHandlers,
  force = false,
): Promise<AiCheckResult> {
  return streamPost<AiCheckResult>(
    `/projects/chapters/${number}/ai-check/stream`,
    force ? { model, force: true } : model ? { model } : {},
    handlers,
    { dir },
  )
}

/** 把这一轮复检里的一条记成已解决；不重新问模型。 */
export async function fetchResolveAiFinding(
  dir: string,
  number: number,
  finding: { code?: string; message: string },
): Promise<AiCheckResult> {
  return postJSON<AiCheckResult>(
    `/projects/chapters/${number}/ai-check/resolve`,
    { code: finding.code ?? '', message: finding.message },
    { dir },
  )
}

export async function fetchRewrite(
  dir: string,
  number: number,
  opts: RewriteOptions = {},
  handlers?: StreamHandlers,
): Promise<RewriteResult> {
  const body = {
    reason: opts.reason ?? '',
    instruction: opts.instruction ?? '',
    model: opts.model ?? null,
    skills: opts.skills ?? null,
    findings: opts.findings ?? null,
  }
  if (handlers) {
    return streamPost<RewriteResult>(`/projects/chapters/${number}/rewrite/stream`, body, handlers, { dir })
  }
  return postJSON<RewriteResult>(`/projects/chapters/${number}/rewrite`, body, { dir })
}

/** 六个语义组的固定顺序，后端没返回时前端也能给出完整骨架。 */
export const AI_GROUPS: Array<{ code: string; label: string }> = [
  { code: 'continuity', label: '吃书' },
  { code: 'motivation', label: '动机' },
  { code: 'voice', label: '口吻' },
  { code: 'dialogue', label: '对话' },
  { code: 'repetition', label: '信息重复' },
  { code: 'emotion-summary', label: '情绪总结' },
]

export const SEVERITY_LABEL: Record<string, string> = {
  high: '硬伤',
  mid: '建议',
  low: '提醒',
  info: '提醒',
}

export const SEVERITY_TONE: Record<string, 'bad' | 'warn' | 'neutral'> = {
  high: 'bad',
  mid: 'warn',
  low: 'neutral',
  info: 'neutral',
}

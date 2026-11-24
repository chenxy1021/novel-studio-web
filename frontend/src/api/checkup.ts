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

export type AiCheckResult = CheckResult & {
  model?: string
  groups: AiGroup[]
  /** 这次复检对照了哪些跨章材料（前情章数、上一章结尾、本章细纲）。 */
  context?: { priorChapters: number; prevTail: boolean; outline: boolean }
  /** 按复检标准给出的结论：fail 才需要重写，minor 只是建议，pass 可以存档。 */
  standard?: {
    verdict: 'fail' | 'minor' | 'pass'
    high: number
    mid: number
    /** 因给不出原句/细纲依据而未被计入的条数。 */
    filtered: number
    note: string
  }
  /** 模型思考过程；流式显示过，收尾留一份方便回看。 */
  thinking?: string
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
): Promise<AiCheckResult> {
  return streamPost<AiCheckResult>(
    `/projects/chapters/${number}/ai-check/stream`,
    model ? { model } : {},
    handlers,
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
  mid: '需改',
  low: '提醒',
  info: '提醒',
}

export const SEVERITY_TONE: Record<string, 'bad' | 'warn' | 'neutral'> = {
  high: 'bad',
  mid: 'warn',
  low: 'neutral',
  info: 'neutral',
}

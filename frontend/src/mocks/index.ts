// Single swap point: when the FastAPI domain endpoints land, each getter here becomes a fetch.
// Views only import from this module, never from the individual book files.
import { makeBatchCheck } from './demoMail'
import type { BatchCheck, Book, Chapter as BookChapter, Finding } from './types'
import { shelf } from './shelf'

export const books = shelf
export type BookKey = keyof typeof books
export { shelf }

export function bookData(key: BookKey) {
  // 每次调用给新副本：route 层（含后端 /chapters）常常就地改 chapter.approved，
  // 共享同一对象会把「待确认」状态污染给 store 和下一本书。
  // 不能 structuredClone 整个 module namespace（函数不可克隆），只拷会变的部分。
  const src = books[key]
  return {
    ...src,
    chapters: src.chapters.map((c) => ({ ...c })),
    segments: src.segments.map((s) => ({ ...s, plan: { ...s.plan, stages: s.plan.stages.map((st) => ({ ...st, chapters: [...st.chapters] })) } })),
  }
}

export function bookOf(key: BookKey): Book {
  return { ...books[key].book }
}

export const SHELF: Array<{ key: BookKey; title: string; genre: string; done: number; target: number }> = [
  { key: 'demoMail', title: '雾城夜邮', genre: '悬疑 · 山城 · 夜班', done: 10, target: 80 },
  { key: 'demoMarket', title: '夜市最后一摊', genre: '市井 · 美食 · 群像', done: 15, target: 120 },
]

export function batchCheckOf(key: BookKey, from: number, to: number): BatchCheck {
  if (key === 'demoMail') return makeBatchCheck(from, to)
  const src = books[key] as unknown as { chapters: BookChapter[]; chapterIssues?: Record<number, Finding[]> }
  return buildBatch(src.chapters.filter((c) => c.number >= from && c.number <= to), src.chapterIssues ?? {}, from, to)
}

function buildBatch(rows: BookChapter[], issues: Record<number, Finding[]>, from: number, to: number): BatchCheck {
  return {
    from,
    to,
    chapters: rows.map((c) => {
      const findings = issues[c.number] ?? (c.approved ? [] : [{ severity: 'high' as const, code: 'unapproved', message: `第${c.number}章仍在待确认`, hint: '先存档或重写' }])
      return { number: c.number, pass: !findings.some((f) => f.severity === 'high'), findings, canRewrite: true }
    }),
    blocking: [
      { severity: 'mid', code: 'batch-voice', message: '本批三处「算账」比喻重复', hint: '换一处成「分肉」的动作描写' },
    ],
    checkedAt: '刚刚',
  }
}

export * from './types'

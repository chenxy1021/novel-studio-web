/** 记忆页：时间线 / 前情账 / 关键词回查。由 ``./studio`` 统一再导出。 */
import { getJSON, postJSON } from './client'
import { arr, num, str } from './format'

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
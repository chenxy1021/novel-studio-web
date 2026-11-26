/** 结构视图与全书级动作：组织 / 章脉 / 相关章节 / 滚动规划 / 审美 / 回灌 / 导出。 */
import { getJSON, postJSON } from './client'
import { arr, num, str } from './format'

export type OrganizationNode = {
  id: number
  name: string
  kind: string
  parent: string
  parentId: number | null
  leader: string
  summary: string
  members: Array<{ name: string; role: string; rank: string; known: boolean }>
}

export type CareerView = {
  name: string
  summary: string
  appliesTo: string[]
  advancement: string
  levels: Array<{ name: string; rank: string; trait: string; gap: string }>
}

export type HierarchyView = {
  organizations: OrganizationNode[]
  careers: CareerView[]
  warnings: string[]
  counts: { organizations: number; careers: number }
}

export type HierarchyResult = {
  ok: boolean
  added: { organizations: number; careers: number }
  filled: { organizations: number; careers: number }
  organizations: number
  careers: number
  summary: string
  model: string
}

function mapHierarchy(raw: Record<string, unknown>): HierarchyView {
  return {
    organizations: arr<Record<string, unknown>>(raw.organizations).map((o) => ({
      id: num(o.id),
      name: str(o.name),
      kind: str(o.kind),
      parent: str(o.parent),
      parentId: o.parentId == null ? null : num(o.parentId),
      leader: str(o.leader),
      summary: str(o.summary),
      members: arr<Record<string, unknown>>(o.members).map((m) => ({
        name: str(m.name),
        role: str(m.role),
        rank: str(m.rank),
        known: m.known !== false,
      })),
    })).filter((o) => o.name),
    careers: arr<Record<string, unknown>>(raw.careers).map((c) => ({
      name: str(c.name),
      summary: str(c.summary),
      appliesTo: arr<string>(c.appliesTo).map((x) => str(x)).filter(Boolean),
      advancement: str(c.advancement),
      levels: arr<Record<string, unknown>>(c.levels).map((l) => ({
        name: str(l.name),
        rank: str(l.rank),
        trait: str(l.trait),
        gap: str(l.gap),
      })).filter((l) => l.name),
    })).filter((c) => c.name),
    warnings: arr<string>(raw.warnings).map((x) => str(x)).filter(Boolean),
    counts: {
      organizations: num((raw.counts as Record<string, unknown> | undefined)?.organizations),
      careers: num((raw.counts as Record<string, unknown> | undefined)?.careers),
    },
  }
}

export async function fetchHierarchy(dir: string): Promise<HierarchyView> {
  return mapHierarchy(await getJSON<Record<string, unknown>>('/projects/hierarchy', { dir }))
}

export async function generateHierarchy(dir: string, model = ''): Promise<HierarchyResult> {
  const raw = await postJSON<Record<string, unknown>>('/projects/hierarchy/generate', { model }, { dir })
  return {
    ok: raw.ok !== false,
    added: {
      organizations: num((raw.added as Record<string, unknown> | undefined)?.organizations),
      careers: num((raw.added as Record<string, unknown> | undefined)?.careers),
    },
    filled: {
      organizations: num((raw.filled as Record<string, unknown> | undefined)?.organizations),
      careers: num((raw.filled as Record<string, unknown> | undefined)?.careers),
    },
    organizations: num(raw.organizations),
    careers: num(raw.careers),
    summary: str(raw.summary),
    model: str(raw.model),
  }
}

/* ------------------------------- 章脉 ------------------------------- */

export type GraphNode = {
  id: string
  number: number
  title: string
  chars: number
  verdict: string
  approved: boolean
  volume: number
  volumeTitle: string
  cast: string[]
  summary: string
  planted: number
  paid: number
}

export type GraphEdge = {
  id: string
  from: number
  to: number
  kind: 'foreshadow' | 'cast'
  label: string
  status: string
  due: number
}

export type ChapterGraph = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  volumes: Array<{ volume: number; title: string; from: number; to: number }>
  stats: {
    chapters: number
    edges: number
    foreshadowEdges: number
    castEdges: number
    openForeshadows: number
    paidForeshadows: number
    castlessChapters: number
  }
}

export async function fetchChapterGraph(dir: string): Promise<ChapterGraph> {
  const raw = await getJSON<Record<string, unknown>>('/projects/chapter-graph', { dir })
  return {
    nodes: arr<Record<string, unknown>>(raw.nodes).map((n) => ({
      id: str(n.id),
      number: num(n.number),
      title: str(n.title),
      chars: num(n.chars),
      verdict: str(n.verdict),
      approved: Boolean(n.approved),
      volume: num(n.volume),
      volumeTitle: str(n.volumeTitle),
      cast: arr<string>(n.cast).map((x) => str(x)).filter(Boolean),
      summary: str(n.summary),
      planted: num(n.planted),
      paid: num(n.paid),
    })),
    edges: arr<Record<string, unknown>>(raw.edges).map((e) => ({
      id: str(e.id),
      from: num(e.from),
      to: num(e.to),
      kind: str(e.kind) === 'foreshadow' ? 'foreshadow' : 'cast',
      label: str(e.label),
      status: str(e.status),
      due: num(e.due),
    })),
    volumes: arr<Record<string, unknown>>(raw.volumes).map((v) => ({
      volume: num(v.volume),
      title: str(v.title),
      from: num(v.from),
      to: num(v.to),
    })),
    stats: {
      chapters: num((raw.stats as Record<string, unknown> | undefined)?.chapters),
      edges: num((raw.stats as Record<string, unknown> | undefined)?.edges),
      foreshadowEdges: num((raw.stats as Record<string, unknown> | undefined)?.foreshadowEdges),
      castEdges: num((raw.stats as Record<string, unknown> | undefined)?.castEdges),
      openForeshadows: num((raw.stats as Record<string, unknown> | undefined)?.openForeshadows),
      paidForeshadows: num((raw.stats as Record<string, unknown> | undefined)?.paidForeshadows),
      castlessChapters: num((raw.stats as Record<string, unknown> | undefined)?.castlessChapters),
    },
  }
}

/* ---------------------------- 相关章节 ---------------------------- */

export type RelatedChapter = {
  number: number
  title: string
  volume: number
  chars: number
  verdict: string
  summary: string
  score: number
  reasons: string[]
}

export async function fetchRelatedChapters(
  dir: string,
  chapter?: number,
  limit = 8,
): Promise<{ chapter: number; items: RelatedChapter[]; text: string }> {
  const raw = await getJSON<Record<string, unknown>>('/projects/related-chapters', {
    dir, chapter, limit,
  })
  return {
    chapter: num(raw.chapter),
    items: arr<Record<string, unknown>>(raw.items).map((r) => ({
      number: num(r.number),
      title: str(r.title),
      volume: num(r.volume),
      chars: num(r.chars),
      verdict: str(r.verdict),
      summary: str(r.summary),
      score: num(r.score),
      reasons: arr<string>(r.reasons).map((x) => str(x)).filter(Boolean),
    })),
    text: str(raw.text),
  }
}

/* ---------------------------- 滚动规划 ---------------------------- */

export type RollingStatus = {
  writtenThrough: number
  nextChapter: number
  compassText: string
  compassAt: string
  targetChapters: number
  plannedThrough: number
  needsVolume: boolean
  plannedChapters: number
  volumes: Array<{ title: string; from: number; to: number }>
  recentSummaries: Array<{ number: number; summary: string }>
}

export async function fetchRolling(dir: string): Promise<RollingStatus> {
  const raw = await getJSON<Record<string, unknown>>('/projects/rolling', { dir })
  return {
    writtenThrough: num(raw.writtenThrough),
    nextChapter: num(raw.nextChapter),
    compassText: str(raw.compassText),
    compassAt: str(raw.compassAt),
    targetChapters: num(raw.targetChapters),
    plannedThrough: num(raw.plannedThrough),
    needsVolume: Boolean(raw.needsVolume),
    plannedChapters: num(raw.plannedChapters),
    volumes: arr<Record<string, unknown>>(raw.volumes).map((v) => ({
      title: str(v.title),
      from: num(v.from),
      to: num(v.to),
    })),
    recentSummaries: arr<Record<string, unknown>>(raw.recentSummaries).map((r) => ({
      number: num(r.number),
      summary: str(r.summary),
    })),
  }
}

export async function saveCompass(dir: string, text: string): Promise<{ compassText: string }> {
  const raw = await postJSON<Record<string, unknown>>('/projects/rolling/compass', { text }, { dir })
  return { compassText: str(raw.compassText) }
}

export type RollingPlan = {
  ok: boolean
  from: number
  to: number
  volumeAdded: { volume: number; text: string; model: string } | null
  volumes: Array<Record<string, unknown>>
  outlines: Array<Record<string, unknown>>
  spine: string
  reused: boolean
  model: string
  compassUsed: boolean
}

export async function planRolling(
  dir: string,
  body: { chapters?: number; model?: string; force?: boolean; runId?: string } = {},
): Promise<RollingPlan> {
  const raw = await postJSON<Record<string, unknown>>('/projects/rolling/plan', body, { dir })
  const added = raw.volumeAdded as Record<string, unknown> | null | undefined
  return {
    ok: raw.ok !== false,
    from: num(raw.from),
    to: num(raw.to),
    volumeAdded: added ? {
      volume: num(added.volume),
      text: str(added.text),
      model: str(added.model),
    } : null,
    volumes: arr<Record<string, unknown>>(raw.volumes),
    outlines: arr<Record<string, unknown>>(raw.outlines),
    spine: str(raw.spine),
    reused: Boolean(raw.reused),
    model: str(raw.model),
    compassUsed: Boolean(raw.compassUsed),
  }
}

/* ---------------------------- 审美五项 ---------------------------- */

export type AestheticDim = {
  key: string
  label: string
  score: number
  quote: string
  comment: string
  fix: string
}

export type AestheticRating = {
  chapter: number
  title: string
  dimensions: AestheticDim[]
  average: number
  summary: string
  model: string
  at: string
  stale: boolean
}

function mapAesthetic(raw: Record<string, unknown> | null | undefined): AestheticRating | null {
  if (!raw) return null
  return {
    chapter: num(raw.chapter),
    title: str(raw.title),
    dimensions: arr<Record<string, unknown>>(raw.dimensions).map((d) => ({
      key: str(d.key),
      label: str(d.label),
      score: num(d.score),
      quote: str(d.quote),
      comment: str(d.comment),
      fix: str(d.fix),
    })).filter((d) => d.key),
    average: num(raw.average),
    summary: str(raw.summary),
    model: str(raw.model),
    at: str(raw.at),
    stale: Boolean(raw.stale),
  }
}

export async function fetchAesthetic(
  dir: string,
  chapter: number,
): Promise<{ chapter: number; rating: AestheticRating | null }> {
  const raw = await getJSON<Record<string, unknown>>('/projects/aesthetic', { dir, chapter })
  return { chapter: num(raw.chapter, chapter), rating: mapAesthetic(raw.rating as Record<string, unknown> | null) }
}

export async function runAesthetic(
  dir: string,
  chapter: number,
  body: { model?: string; text?: string } = {},
): Promise<AestheticRating> {
  const raw = await postJSON<Record<string, unknown>>(
    `/projects/chapters/${chapter}/aesthetic`, body, { dir },
  )
  return mapAesthetic(raw) ?? {
    chapter, title: '', dimensions: [], average: 0, summary: '', model: '', at: '', stale: false,
  }
}

/* ---------------------------- 手改回灌 ---------------------------- */

export type SyncItem = {
  number: number
  title: string
  chars: number
  kind: 'edited' | 'untracked' | 'baseline' | 'missing' | 'memory-stale'
  reason: string
  memoryStale?: boolean
}

export type SyncScan = {
  items: SyncItem[]
  counts: {
    edited: number
    untracked: number
    baseline: number
    missing: number
    memoryStale: number
  }
  chapters: number
  indexed: number
}

export async function fetchSyncScan(dir: string): Promise<SyncScan> {
  const raw = await getJSON<Record<string, unknown>>('/projects/sync', { dir })
  return {
    items: arr<Record<string, unknown>>(raw.items).map((x) => ({
      number: num(x.number),
      title: str(x.title),
      chars: num(x.chars),
      kind: str(x.kind) as SyncItem['kind'],
      reason: str(x.reason),
      memoryStale: Boolean(x.memoryStale),
    })),
    counts: {
      edited: num((raw.counts as Record<string, unknown> | undefined)?.edited),
      untracked: num((raw.counts as Record<string, unknown> | undefined)?.untracked),
      baseline: num((raw.counts as Record<string, unknown> | undefined)?.baseline),
      missing: num((raw.counts as Record<string, unknown> | undefined)?.missing),
      memoryStale: num((raw.counts as Record<string, unknown> | undefined)?.memoryStale),
    },
    chapters: num(raw.chapters),
    indexed: num(raw.indexed),
  }
}

export type SyncResultRow = {
  number: number
  title: string
  kind: string
  ok: boolean
  chars?: number
  error?: string
  steps: string[]
}

export type SyncApplyResult = {
  ok: boolean
  results: SyncResultRow[]
  applied: number[]
  failed: SyncResultRow[]
  skipped: number[]
  memoryRegenerated: boolean
}

export async function applySync(
  dir: string,
  body: { numbers?: number[]; regenerateMemory?: boolean; model?: string; runId?: string } = {},
): Promise<SyncApplyResult> {
  const raw = await postJSON<Record<string, unknown>>('/projects/sync/apply', body, { dir })
  const rows = arr<Record<string, unknown>>(raw.results).map((r) => ({
    number: num(r.number),
    title: str(r.title),
    kind: str(r.kind),
    ok: Boolean(r.ok),
    chars: r.chars == null ? undefined : num(r.chars),
    error: str(r.error) || undefined,
    steps: arr<string>(r.steps).map((x) => str(x)).filter(Boolean),
  }))
  return {
    ok: raw.ok !== false,
    results: rows,
    applied: arr<number>(raw.applied).map(Number),
    failed: rows.filter((r) => !r.ok),
    skipped: arr<number>(raw.skipped).map(Number),
    memoryRegenerated: Boolean(raw.memoryRegenerated),
  }
}

/* ------------------------------ 导出 ------------------------------ */

export type ExportResult = {
  ok: boolean
  filename: string
  path: string
  chapters: number
  chars: number
  firstChapter: number
  lastChapter: number
  missing: number[]
  empty: number[]
  gaps: string[]
  note: string
  at: string
}

export async function makeExport(dir: string): Promise<ExportResult> {
  const raw = await postJSON<Record<string, unknown>>('/projects/export', {}, { dir })
  return {
    ok: raw.ok !== false,
    filename: str(raw.filename),
    path: str(raw.path),
    chapters: num(raw.chapters),
    chars: num(raw.chars),
    firstChapter: num(raw.firstChapter),
    lastChapter: num(raw.lastChapter),
    missing: arr<number>(raw.missing).map(Number),
    empty: arr<number>(raw.empty).map(Number),
    gaps: arr<string>(raw.gaps).map((x) => str(x)).filter(Boolean),
    note: str(raw.note),
    at: str(raw.at),
  }
}

/** 浏览器直接下载：和后端「导出一份到 exports/」生成的是同一份内容。 */
export function exportDownloadUrl(dir: string): string {
  return `/api/projects/export/txt?dir=${encodeURIComponent(dir)}`
}

export function downloadExport(dir: string): void {
  const a = document.createElement('a')
  a.href = exportDownloadUrl(dir)
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

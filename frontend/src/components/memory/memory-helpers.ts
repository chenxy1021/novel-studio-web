import type { MemoryChapter, MemoryVolume } from '@/api/studio'

export type ChapterGroup = {
  key: string
  title: string
  from: number
  to: number
  chapters: MemoryChapter[]
}

export const chapterCode = (n: number) => String(n).padStart(3, '0')

/** 后端把地点合成一个字符串；这里再拆成可筛选的标签。 */
export function splitPlaces(place: string): string[] {
  return String(place || '')
    .split(/[、,，/|]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

export const dimsLabels: Array<{ key: string; label: string }> = [
  { key: 'mainline', label: '主线' },
  { key: 'threads', label: '支线' },
  { key: 'relations', label: '关系' },
  { key: 'knowledge', label: '读者已知' },
  { key: 'carryover', label: '带出下一卷' },
  { key: 'drift', label: '与大纲偏差' },
]

function fiftyGroups(chapters: MemoryChapter[]): ChapterGroup[] {
  const buckets = new Map<number, MemoryChapter[]>()
  for (const c of chapters) {
    const start = Math.floor((c.chapter - 1) / 50) * 50 + 1
    const list = buckets.get(start) ?? []
    list.push(c)
    buckets.set(start, list)
  }
  return [...buckets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([start, list]) => ({
      key: `fifty-${start}`,
      title: `第 ${start}–${start + 49} 章`,
      from: start,
      to: start + 49,
      chapters: [...list].sort((a, b) => a.chapter - b.chapter),
    }))
}

/** 卷索引优先；落在卷外的章再按 50 章一组，保证时间线不丢行。 */
export function groupChapters(chapters: MemoryChapter[], volumes: MemoryVolume[]): ChapterGroup[] {
  const sorted = [...chapters].sort((a, b) => a.chapter - b.chapter)
  if (!volumes.length) return fiftyGroups(sorted)

  const ranges = [...volumes].sort((a, b) => a.from - b.from)
  const inVolume = (n: number) => ranges.some((v) => n >= v.from && n <= v.to)
  const groups: ChapterGroup[] = ranges
    .map((v) => ({
      key: `vol-${v.volume}-${v.from}`,
      title: v.title ? `第${v.volume}卷 · ${v.title}` : `第${v.volume}卷`,
      from: v.from,
      to: v.to,
      chapters: sorted.filter((c) => c.chapter >= v.from && c.chapter <= v.to),
    }))
    .filter((g) => g.chapters.length)

  const leftover = sorted.filter((c) => !inVolume(c.chapter))
  return [...groups, ...fiftyGroups(leftover)]
}

export function volumeOfChapter(
  chapter: number,
  volumes: MemoryVolume[],
): MemoryVolume | null {
  return volumes.find((v) => chapter >= v.from && chapter <= v.to) ?? null
}

export type ParsedCharacterState = {
  knows: Array<{ chapter: number; text: string }>
  relations: Array<{ other: string; text: string; chapter: number }>
}

/**
 * 后端 character_state 的输出是确定性文本：
 *   · 第3章知道：…
 *   · 与阿枝：师徒但彼此提防（第3章）
 * 这里解析成三块卡片；解析不到时调用方回退显示原文。
 */
export function parseCharacterState(state: string): ParsedCharacterState {
  const knows: ParsedCharacterState['knows'] = []
  const relations: ParsedCharacterState['relations'] = []
  for (const raw of String(state || '').split('\n')) {
    const line = raw.replace(/^\s*[·\-]\s*/, '').trim()
    if (!line || line.startsWith('·')) continue
    const know = line.match(/^第\s*(\d+)\s*章知道[：:]\s*(.+)$/)
    if (know) {
      knows.push({ chapter: Number(know[1]), text: know[2] })
      continue
    }
    const rel = line.match(/^与(.+?)[：:]\s*(.+?)（第\s*(\d+)\s*章）$/)
    if (rel) {
      relations.push({ other: rel[1], text: rel[2], chapter: Number(rel[3]) })
    }
  }
  return { knows, relations }
}

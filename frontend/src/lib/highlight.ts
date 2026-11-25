export type Segment = { text: string; hit: boolean }

/** 把一段文字按关键词切成片段，命中段交给 <mark> 渲染；大小写不敏感。 */
export function highlightSegments(text: string, kw: string): Segment[] {
  const needle = kw.trim()
  if (!needle) return [{ text, hit: false }]
  const esc = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const out: Segment[] = []
  let last = 0
  for (const m of text.matchAll(new RegExp(esc, 'gi'))) {
    const i = m.index ?? 0
    if (i > last) out.push({ text: text.slice(last, i), hit: false })
    out.push({ text: m[0], hit: true })
    last = i + m[0].length
  }
  if (!out.length) return [{ text, hit: false }]
  if (last < text.length) out.push({ text: text.slice(last), hit: false })
  return out
}

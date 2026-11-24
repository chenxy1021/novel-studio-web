/** 极简 Markdown → HTML：只覆盖模型会写的那几种块（标题/列表/表格/引用/代码），
 *  先转义再排格式，v-html 出去是安全的。不引第三方依赖。 */

const ESC: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }
const escapeHtml = (s: string) => s.replace(/[&<>"]/g, (c) => ESC[c])

function inline(src: string): string {
  let s = escapeHtml(src)
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>')
  s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  s = s.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noreferrer noopener">$1</a>',
  )
  return s
}

function slugOf(text: string, seen: Map<string, number>): string {
  const base =
    text
      .toLowerCase()
      .replace(/\s+/g, '-')
      .replace(/[^\p{L}\p{N}\-_]/gu, '')
      .replace(/-{2,}/g, '-')
      .replace(/^-|-$/g, '') || 'section'
  const n = (seen.get(base) ?? 0) + 1
  seen.set(base, n)
  return n === 1 ? base : `${base}-${n}`
}

/** 去掉行内标记，给目录 / slug 用。 */
function plainInline(src: string): string {
  return src
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/~~([^~]+)~~/g, '$1')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1$2')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .trim()
}

export type MdHeading = { level: number; text: string; id: string }

/** 目录：与 renderMarkdown 用同一套 slug，锚点能对上。 */
export function markdownHeadings(src: string): MdHeading[] {
  const seen = new Map<string, number>()
  const out: MdHeading[] = []
  let fence = false
  for (const raw of String(src || '').replace(/\r\n/g, '\n').split('\n')) {
    if (/^\s*```/.test(raw)) {
      fence = !fence
      continue
    }
    if (fence) continue
    const m = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(raw)
    if (!m) continue
    const level = m[1].length
    const text = plainInline(m[2])
    if (!text) continue
    out.push({ level, text, id: slugOf(text, seen) })
  }
  return out
}

const isTableSep = (line: string) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line)
const splitRow = (line: string): string[] => {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|')) s = s.slice(0, -1)
  return s.split('|').map((c) => c.trim())
}

function renderTable(header: string[], rows: string[][]): string {
  const th = header.map((c) => `<th>${inline(c)}</th>`).join('')
  const body = rows
    .map((r) => `<tr>${header.map((_, i) => `<td>${inline(r[i] ?? '')}</td>`).join('')}</tr>`)
    .join('')
  return `<div class="md-table"><table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table></div>`
}

type LiNode = { text: string; ordered: boolean; children: LiNode[] }

function renderList(items: LiNode[]): string {
  let html = ''
  let i = 0
  while (i < items.length) {
    const ordered = items[i].ordered
    html += ordered ? '<ol>' : '<ul>'
    while (i < items.length && items[i].ordered === ordered) {
      const node = items[i]
      html += `<li>${inline(node.text)}${node.children.length ? renderList(node.children) : ''}</li>`
      i += 1
    }
    html += ordered ? '</ol>' : '</ul>'
  }
  return html
}

function parseList(lines: string[], start: number): { html: string; next: number } {
  const roots: LiNode[] = []
  const stack: Array<{ indent: number; node: LiNode }> = []
  let i = start
  for (; i < lines.length; i += 1) {
    const m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i])
    if (!m) break
    const indent = m[1].replace(/\t/g, '  ').length
    const node: LiNode = { text: m[3].trim(), ordered: /\d/.test(m[2]), children: [] }
    while (stack.length && indent <= stack[stack.length - 1].indent) stack.pop()
    if (stack.length) stack[stack.length - 1].node.children.push(node)
    else roots.push(node)
    stack.push({ indent, node })
  }
  return { html: renderList(roots), next: i }
}

const BLOCK_START = /^\s*(#{1,6}\s|>\s?|```|([-*+]|\d+[.)])\s)/

export function renderMarkdown(src: string): string {
  const lines = String(src || '').replace(/\r\n/g, '\n').split('\n')
  const seen = new Map<string, number>()
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) {
      i += 1
      continue
    }
    // 代码块
    if (/^\s*```/.test(line)) {
      const lang = line.replace(/^\s*```/, '').trim()
      const body: string[] = []
      i += 1
      while (i < lines.length && !/^\s*```/.test(lines[i])) {
        body.push(lines[i])
        i += 1
      }
      i += 1
      out.push(
        `<pre><code${lang ? ` class="lang-${escapeHtml(lang)}"` : ''}>${escapeHtml(body.join('\n'))}</code></pre>`,
      )
      continue
    }
    // 标题
    const h = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line)
    if (h) {
      const level = Math.min(6, h[1].length)
      const text = plainInline(h[2])
      out.push(`<h${level} id="${slugOf(text, seen)}">${inline(h[2])}</h${level}>`)
      i += 1
      continue
    }
    // 分隔线
    if (/^\s*([-*_])\s*(\1\s*){2,}$/.test(line)) {
      out.push('<hr>')
      i += 1
      continue
    }
    // 引用
    if (/^\s*>/.test(line)) {
      const buf: string[] = []
      while (i < lines.length && /^\s*>/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ''))
        i += 1
      }
      out.push(`<blockquote>${buf.map((l) => inline(l)).join('<br>')}</blockquote>`)
      continue
    }
    // 表格
    if (line.includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const header = splitRow(line)
      const rows: string[][] = []
      i += 2
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        rows.push(splitRow(lines[i]))
        i += 1
      }
      out.push(renderTable(header, rows))
      continue
    }
    // 列表
    if (/^(\s*)([-*+]|\d+[.)])\s+/.test(line)) {
      const { html, next } = parseList(lines, i)
      out.push(html)
      i = next
      continue
    }
    // 段落：连续非空行，单换行保留为 <br>
    const buf: string[] = []
    while (i < lines.length && lines[i].trim() && !BLOCK_START.test(lines[i]) && !/^\s*\|/.test(lines[i])) {
      buf.push(lines[i].trim())
      i += 1
    }
    if (buf.length) out.push(`<p>${buf.map((l) => inline(l)).join('<br>')}</p>`)
    else i += 1
  }
  return out.join('\n')
}

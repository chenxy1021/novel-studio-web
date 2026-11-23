export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

export function pct(a: number, b: number): number {
  if (!b) return 0
  return Math.min(100, Math.round((a / b) * 100))
}

export function wan(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1).replace(/\.0$/, '')} 万`
  return String(n)
}

export function chapterLabel(n: number): string {
  return `第 ${n} 章`
}

export function rangeLabel(from: number, to: number): string {
  return `第 ${from}–${to} 章`
}

export function pad3(n: number): string {
  return String(n).padStart(3, '0')
}

export function shortDir(dir: string): string {
  return dir.replace(/^.*\/Desktop\//, '~/Desktop/').replace(/^.*\/mine\//, 'mine/')
}

export function truncate(s: string, n: number): string {
  return s.length > n ? `${s.slice(0, n)}…` : s
}

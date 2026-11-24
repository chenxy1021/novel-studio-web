/** 后端返回值兜底：拿不准类型时统一走这三个，保证视图模型不出现 undefined。 */

export const str = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : v == null ? fallback : String(v))
export const num = (v: unknown, fallback = 0): number => {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}
export const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : [])

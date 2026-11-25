import type { Foreshadow } from '@/mocks'

/** 伏笔页的四个筛选格子。「超期」是「未收」的子集：回收章已经到或过了，正文里还没收。 */
export type ForeshadowFilter = 'open' | 'overdue' | 'paid' | 'abandoned'

export const FORESHADOW_FILTERS: Array<{ id: ForeshadowFilter; label: string }> = [
  { id: 'open', label: '未收' },
  { id: 'overdue', label: '超期' },
  { id: 'paid', label: '已收' },
  { id: 'abandoned', label: '放弃' },
]

export function filterForeshadows(
  list: Foreshadow[],
  filter: ForeshadowFilter,
  kind: 'all' | Foreshadow['kind'] = 'all',
): Foreshadow[] {
  return list.filter((f) => {
    if (kind !== 'all' && f.kind !== kind) return false
    if (filter === 'overdue') return f.status === 'open' && !!f.overdue
    if (filter === 'paid') return f.status === 'paid'
    if (filter === 'abandoned') return f.status === 'abandoned'
    return f.status === 'open'
  })
}

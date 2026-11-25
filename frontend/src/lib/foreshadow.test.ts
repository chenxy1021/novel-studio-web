import { describe, expect, it } from 'vitest'
import type { Foreshadow } from '@/mocks'
import { filterForeshadows } from './foreshadow'

function fs(patch: Partial<Foreshadow> & { name: string }): Foreshadow {
  return {
    id: patch.name,
    kind: 'detail',
    plantedChapter: 1,
    dueChapter: 5,
    status: 'open',
    ...patch,
  }
}

const LIST: Foreshadow[] = [
  fs({ name: '正常的', status: 'open', overdue: false }),
  fs({ name: '到期没收的', status: 'open', overdue: true }),
  fs({ name: '收掉的', status: 'paid', overdue: false, payoffChapter: 4 }),
  fs({ name: '放弃的', status: 'abandoned', overdue: false }),
  fs({ name: '主线超期', status: 'open', overdue: true, kind: 'main' }),
]

const names = (rows: Foreshadow[]) => rows.map((f) => f.name)

describe('filterForeshadows', () => {
  it('四个筛子各取一份，超期只算「未收 + 已到期」', () => {
    expect(names(filterForeshadows(LIST, 'open'))).toEqual(['正常的', '到期没收的', '主线超期'])
    expect(names(filterForeshadows(LIST, 'overdue'))).toEqual(['到期没收的', '主线超期'])
    expect(names(filterForeshadows(LIST, 'paid'))).toEqual(['收掉的'])
    expect(names(filterForeshadows(LIST, 'abandoned'))).toEqual(['放弃的'])
  })

  it('层级筛选和状态筛选取交集', () => {
    expect(names(filterForeshadows(LIST, 'overdue', 'main'))).toEqual(['主线超期'])
    expect(filterForeshadows(LIST, 'paid', 'main')).toEqual([])
  })

  it('已收的线即使过了回收章也不算超期', () => {
    const paid = [fs({ name: '收晚了的', status: 'paid', overdue: false, payoffChapter: 9 })]
    expect(filterForeshadows(paid, 'overdue')).toEqual([])
  })
})

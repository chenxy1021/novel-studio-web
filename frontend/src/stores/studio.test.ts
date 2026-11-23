import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { bookData } from '@/mocks'
import { useStudio } from './studio'

function memoryLS() {
  const store = new Map<string, string>()
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, String(v)),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
    },
  })
  return store
}

const fresh = () => {
  setActivePinia(createPinia())
  return useStudio()
}

describe('studio store', () => {
  let ls: Map<string, string>
  beforeEach(() => {
    ls = memoryLS()
  })

  it('两本书的章节都按章号排序，待确认只来自 mock 种子的 approved:false', () => {
    for (const key of ['signalTower', 'huntingGround'] as const) {
      const studio = fresh()
      studio.key = key
      const numbers = bookData(key).chapters.map((c) => c.number)
      expect(numbers).toEqual([...numbers].sort((a, b) => a - b))
      expect(new Set(numbers).size).toBe(numbers.length)
    }
    const studio = fresh()
    expect(studio.pending.map((c) => c.number)).toEqual([10])
    expect(studio.nextNumber).toBe(11)
  })

  it('autoArchivePending 存档全部待确认章、重复调用不重复弹提示', () => {
    const studio = fresh()
    studio.autoArchivePending()
    expect(studio.pending).toHaveLength(0)
    expect(studio.approved.map((c) => c.number)).toContain(10)
    expect(studio.toasts.map((t) => t.text).join()).toContain('第 10 章已自动存档')
    const before = studio.toasts.length
    studio.autoArchivePending()
    expect(studio.toasts.length).toBe(before)
    expect(JSON.parse(ls.get('ns.archived')!)).toEqual({ signalTower: [10] })
  })

  it('自动存档跨刷新保持：新 pinia 从 localStorage 恢复', () => {
    fresh().autoArchivePending()
    const rebooted = fresh()
    expect(rebooted.pending).toHaveLength(0)
    expect(rebooted.autoArchived).toEqual([10])
  })

  it('rewrite 退回后变待确认、字数清零，再进进度页仍算「已经处理过」不自动重存', () => {
    const studio = fresh()
    studio.autoArchivePending()
    studio.rewrite(9, '，章尾没收住')
    expect(studio.findChapter(9)?.approved).toBe(false)
    expect(studio.findChapter(9)?.chars).toBe(0)
    studio.autoArchivePending()
    expect(studio.findChapter(9)?.approved).toBe(false)
    expect(studio.pending.map((c) => c.number)).toEqual([9])
  })

  it('按批体检在 420ms 后返回当前段，并把每章 findings 铺进 checks', async () => {
    const studio = fresh()
    studio.runBatchCheck()
    expect(studio.batchBusy).toBe(true)
    await new Promise((r) => setTimeout(r, 500))
    expect(studio.batchBusy).toBe(false)
    expect(studio.batch?.from).toBe(11)
    expect(studio.batch?.to).toBe(20)
    for (const row of studio.batch!.chapters) {
      expect(studio.checks[row.number]?.findings).toEqual(row.findings)
      expect(studio.checks[row.number]?.fromBatch).toBe(true)
    }
    expect(studio.batch!.blocking.length).toBeGreaterThan(0)
  })

  it('recentSegment 指向有正文章的那一段，不取空规划段', () => {
    const studio = fresh()
    expect(studio.recentSegment?.from).toBe(1)
    studio.rewrite(1)
    expect(studio.recentSegment?.from).toBe(1)
  })

  it('切换书重建章节与段落，清掉体检结果', async () => {
    const studio = fresh()
    studio.autoArchivePending()
    studio.runBatchCheck()
    studio.key = 'huntingGround'
    await nextTick()
    expect(studio.chapters[0].number).toBe(1)
    expect(studio.chapters).toHaveLength(bookData('huntingGround').chapters.length)
    expect(studio.checks[1]).toBeUndefined()
    expect(studio.batch).toBeNull()
    expect(studio.segList[0].from).toBe(1)
    expect(ls.get('ns.book')).toBe('huntingGround')
  })

  it('localStorage 被禁用时 store 仍可初始化与存档', () => {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('SecurityError: access denied')
      },
    })
    const studio = fresh()
    expect(studio.chapters.length).toBeGreaterThan(0)
    studio.autoArchivePending()
    expect(studio.pending).toHaveLength(0)
  })

  it('localStorage 里是坏 JSON 时不炸，按空处理', () => {
    ls.set('ns.archived', '{oops')
    const studio = fresh()
    expect(studio.autoArchived).toEqual([])
    expect(studio.pending.map((c) => c.number)).toEqual([10])
  })
})

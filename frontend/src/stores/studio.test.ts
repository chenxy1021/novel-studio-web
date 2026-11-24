import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
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

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

/** 生成接口走 SSE：先 delta，再 done（或 error）。 */
const sse = (events: unknown[]) =>
  new Response(events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join(''), {
    status: 200,
    headers: { 'content-type': 'text/event-stream' },
  })

const DIR = '/books/测试书'

function installFetch(opts: { batchOutlineFails?: boolean; savedChecks?: unknown[] } = {}) {
  const calls: Array<{ url: string; method: string; body?: string }> = []
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method || 'GET'
    calls.push({ url, method, body: typeof init?.body === 'string' ? init.body : undefined })
    if (url.endsWith('/api/projects')) {
      return json({ books: [{ dir: DIR, title: '测试书', genre: '测试', targetChapters: 100, currentChapter: 2, chapterCount: 2, updatedAt: '' }] })
    }
    if (url.includes('/projects/overview')) {
      return json({
        dir: DIR, title: '测试书', genre: '测试', platform: '通用', logline: '一句话', synopsis: '', theme: '',
        tone: '', targetChapters: 100, currentChapter: 2, wordsPerChapter: 2000, minChars: 1800,
        updatedAt: '', gate: { phase: 'writing', chapter: 2, reason: '', at: '' }, gates: {},
        spine: 'spine', chapters: [
          { number: 1, title: '第一章', chars: 2000, approved: false, chapterVerdict: 'pass', endHook: { ok: true } },
          { number: 2, title: '第二章', chars: 2100, approved: true, chapterVerdict: 'pass', endHook: { ok: true } },
        ], pending: [1],
      })
    }
    if (url.includes('/projects/chapters?')) {
      return json({ chapters: [
        { number: 1, title: '第一章', chars: 2000, summary: '一', characters: ['甲'], approved: false, dialogueRatio: 0.2, committedAt: '2026-11-24T01:00:00Z' },
        { number: 2, title: '第二章', chars: 2100, summary: '二', characters: ['乙'], approved: true, dialogueRatio: 0.3, committedAt: '2026-11-23T01:00:00Z' },
      ] })
    }
    if (url.includes('/projects/checks')) {
      return json({ rows: opts.savedChecks ?? [] })
    }
    if (url.includes('/projects/check-batch')) {
      // 真实接口每章返回完整 check_chapter 结果，不只是摘要。
      return json({
        from: 1, to: 2, blocking: [], checkedAt: '2026-11-24T03:00:00Z',
        chapters: [
          { number: 1, pass: true, findings: [], canRewrite: true, textHash: 'h1', checkedAt: '2026-11-24T03:00:00Z' },
          {
            number: 2, pass: false, canRewrite: true, textHash: 'h2', checkedAt: '2026-11-24T03:00:00Z',
            findings: [{ severity: 'high', code: 'chars', message: '太短' }],
          },
        ],
      })
    }
    if (url.includes('/projects/chapters/1/archive')) {
      return json({ approved: 1, nextChapter: 2, gate: { phase: 'writing', chapter: 2, reason: 'ok', at: '' } })
    }
    if (url.includes('/projects/chapters/1/reject')) {
      return json({ ok: true, discarded: 1, draftFile: 'drafts/001-x-reject.md' })
    }
    if (url.match(/\/projects\/chapters\/1(\?|$)/)) {
      return json({ text: '第一段正文。\n\n第二段正文。', chars: 16 })
    }
    if (url.includes('/projects/outlines/batch/stream')) {
      if (opts.batchOutlineFails) {
        return sse([{ type: 'error', code: 'LLM_ERROR', message: '整批细纲超时', status: 502 }])
      }
      return sse([
        { type: 'stage', label: '生成本批细纲' },
        { type: 'delta', text: '本批细纲…' },
        {
          type: 'done',
          result: {
            ok: true, from: 3, to: 5, spine: '本批主线',
            outlines: [3, 4, 5].map((n) => ({ chapter: n, title: `第${n}章`, beats: ['拍1'] })),
            styleApplied: { source: 'book', effective: {} }, model: 'mock', reused: false,
          },
        },
      ])
    }
    if (url.includes('/projects/chapters/3/outline/stream')) {
      return sse([
        { type: 'stage', label: '写本章细纲' },
        { type: 'delta', text: '本章细纲…' },
        {
          type: 'done',
          result: {
            ok: true, chapter: 3,
            outline: { chapter: 3, title: '第三章', beats: ['拍1'] },
            styleApplied: { source: 'book', effective: {} }, model: 'mock', reused: false,
          },
        },
      ])
    }
    if (url.includes('/projects/chapters/3/prose/stream')) {
      return sse([
        { type: 'stage', label: '写正文' },
        { type: 'delta', text: '第三章正文。' },
        {
          type: 'done',
          result: {
            ok: true, chapter: { number: 3, title: '第三章', chars: 2300 },
            text: '第三章正文。', chars: 2300,
            styleApplied: { source: 'book', effective: {} }, model: 'mock',
          },
        },
      ])
    }
    if (url.includes('/projects/chapters/4/prose/stream')) {
      return sse([{ type: 'error', code: 'LLM_ERROR', message: '模型超时', status: 502 }])
    }
    if (url.includes('/projects/bible')) {
      return json({ bible: { characters: [{ name: '甲', rolePosition: '主角', want: '赢' }], rules: [], locations: [] } })
    }
    if (url.includes('/projects/ledger/segments')) {
      return json({ rows: [{ from: 1, to: 10, at: '', plan: { from: 1, to: 10, spine: '', stages: [{ chapters: [1, 2], goal: 'g', turn: 't', foreshadow: { plant: [], payoff: [] }, pace: '紧', places: [], cast: [] }] } }] })
    }
    if (url.includes('/projects/nuewen')) return json({ text: '', at: '', model: '' })
    if (url.includes('/projects/ledger/')) return json({ rows: [] })
    if (url.includes('/projects/discarded')) return json({ rows: [] })
    if (url.includes('/projects/volumes')) return json({ volumes: [] })
    return json({ detail: `unhandled ${url}` }, 404)
  })
  globalThis.fetch = fn as unknown as typeof fetch
  return calls
}

const fresh = () => {
  setActivePinia(createPinia())
  return useStudio()
}

describe('studio store (API-backed)', () => {
  let ls: Map<string, string>
  let calls: ReturnType<typeof installFetch>

  beforeEach(() => {
    ls = memoryLS()
    calls = installFetch()
  })

  it('init 从后端书架打开一本书，章节按章号排序', async () => {
    const studio = fresh()
    await studio.init()
    expect(studio.ready).toBe(true)
    expect(studio.book.title).toBe('测试书')
    expect(studio.chapters.map((c) => c.number)).toEqual([1, 2])
    expect(studio.pending.map((c) => c.number)).toEqual([1])
    expect(studio.nextNumber).toBe(3)
    expect(ls.get('ns.dir')).toBe(DIR)
    expect(studio.recentSegment?.from).toBe(1)
  })

  it('archive 走 POST，成功后章节变成已存档', async () => {
    const studio = fresh()
    await studio.init()
    await studio.archive(1)
    const call = calls.find((c) => c.url.includes('/chapters/1/archive'))
    expect(call?.method).toBe('POST')
    expect(studio.findChapter(1)?.approved).toBe(true)
    expect(studio.book.gate.chapter).toBe(2)
  })

  it('reject 走 POST，成功后从正文列表移除', async () => {
    const studio = fresh()
    await studio.init()
    await studio.reject(1, '重写')
    expect(calls.some((c) => c.url.includes('/chapters/1/reject'))).toBe(true)
    expect(studio.findChapter(1)).toBeNull()
    expect(studio.findChapter(2)?.approved).toBe(true)
  })

  it('刷新后恢复上次体检结果，并标出正文改过的章', async () => {
    calls = installFetch({
      savedChecks: [{
        chapter: 2, at: '2026-11-24T02:00:00Z', stale: true,
        result: {
          number: 2, pass: false, textHash: 'old2', checkedAt: '2026-11-24T02:00:00Z',
          findings: [{ severity: 'high', code: 'chars', message: '太短' }],
        },
      }],
    })
    const studio = fresh()
    await studio.init()

    expect(studio.checks[2].pass).toBe(false)
    expect(studio.checkResults[2]?.textHash).toBe('old2')
    expect(studio.checkStale[2]).toBe(true)
    expect(studio.checkStale[1]).toBeUndefined()
  })

  it('按批体检把完整结果写进 checkResults，和单章体检读同一份', async () => {
    const studio = fresh()
    await studio.init()
    await studio.runBatchCheck(1, 2)

    expect(studio.checkResults[1]?.textHash).toBe('h1')
    expect(studio.checkResults[2]?.findings[0].message).toBe('太短')
    expect(studio.checks[2].fromBatch).toBe(true)
    expect(studio.checkStale[2]).toBe(false)
  })

  it('正文按需拉取并缓存', async () => {
    const studio = fresh()
    await studio.init()
    const text = await studio.loadText(1)
    expect(text).toContain('第一段正文')
    const before = calls.length
    await studio.loadText(1)
    expect(calls.length).toBe(before)
  })

  it('书架为空时进入选题状态', async () => {
    globalThis.fetch = vi.fn(async () => json({ books: [] })) as unknown as typeof fetch

    const studio = fresh()
    await studio.init()
    expect(studio.ready).toBe(false)
    expect(studio.emptyShelf).toBe(true)
    expect(studio.error).toBe('')
  })

  it('后端不可用时 init 把错误留在 error，不抛到页面外', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('failed')
    }) as unknown as typeof fetch
    const studio = fresh()
    await studio.init()
    expect(studio.ready).toBe(false)
    expect(studio.error).toContain('连不上后端')
  })

  it('openWritePanel 默认选章跳过已有正文，并规范化显式章号', async () => {
    const studio = fresh()
    await studio.init()

    studio.openWritePanel({ from: 1, to: 5 })
    expect(studio.writePanel.open).toBe(true)
    expect(studio.writePanel.from).toBe(1)
    expect(studio.writePanel.to).toBe(5)
    expect(studio.writePanel.styleConfirmed).toBe(false)
    // 第 1、2 章已有正文，不应默认选中
    expect(studio.writePanel.numbers).toEqual([3, 4, 5])

    studio.openWritePanel({ numbers: [5, 3, 3, 0, 999] })
    expect(studio.writePanel.numbers).toEqual([3, 5])
  })

  it('startWriteBatch 先整批出细纲，某章正文失败后停止，不再请求后续章', async () => {
    const studio = fresh()
    await studio.init()

    studio.openWritePanel({ numbers: [3, 4, 5] })
    studio.writePanel.styleConfirmed = true

    const run = await studio.startWriteBatch()

    expect(run.active).toBe(false)
    expect(run.error).toContain('第 4 章失败')
    expect(run.error).toContain('模型超时')
    expect(run.chapters.map((c) => [c.number, c.stage])).toEqual([
      [3, 'done'],
      [4, 'failed'],
      [5, 'queued'],
    ])
    expect(run.done).toBe(1)
    // 一批只调一次细纲，正文按章写。
    expect(calls.filter((c) => c.url.includes('/outlines/batch'))).toHaveLength(1)
    expect(calls.some((c) => c.url.includes('/outline/stream'))).toBe(false)
    expect(calls.some((c) => c.url.includes('/chapters/5/prose'))).toBe(false)
  })

  it('本批细纲失败时整批停下，一章正文都不写', async () => {
    calls = installFetch({ batchOutlineFails: true })
    const studio = fresh()
    await studio.init()

    studio.openWritePanel({ numbers: [3, 4, 5] })
    studio.writePanel.styleConfirmed = true

    const run = await studio.startWriteBatch()

    expect(run.active).toBe(false)
    expect(run.error).toContain('第 3–5 章细纲失败')
    expect(run.chapters.map((c) => c.stage)).toEqual(['failed', 'failed', 'failed'])
    expect(calls.some((c) => c.url.includes('/prose/stream'))).toBe(false)
  })
})

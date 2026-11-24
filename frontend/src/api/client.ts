/** FastAPI 的最小 fetch 封装：错误统一成 ApiError，调用方不用每次猜 detail 的形状。 */

export type Finding = {
  severity: 'high' | 'mid' | 'info'
  code: string
  message: string
  hint?: string
  chapter?: number
  source?: 'ai' | string
  /** 跨章问题里逐条可处理的明细（目前只有到期伏笔）。 */
  items?: {
    id: string
    name: string
    kind: string
    plantedChapter: number
    dueChapter: number
    overdueBy: number
  }[]
}

export class ApiError extends Error {
  status: number
  findings: Finding[]
  detail: unknown

  constructor(status: number, detail: unknown) {
    const obj = detail as { message?: string; findings?: Finding[] } | string | null
    const message =
      typeof obj === 'string'
        ? obj
        : obj?.message || (status === 0 ? '连不上后端（8010）' : `请求失败（${status}）`)
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.findings = (typeof obj === 'object' && obj?.findings) || []
  }
}

type Params = Record<string, string | number | boolean | undefined | null>

function withQuery(path: string, params?: Params): string {
  if (!params) return path
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  }
  const s = q.toString()
  return s ? `${path}?${s}` : path
}

async function request<T>(method: string, path: string, body?: unknown, params?: Params): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${withQuery(path, params)}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, '连不上后端（8010），先运行 ./scripts/dev.sh')
  }
  const text = await res.text()
  let payload: unknown = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    payload = text
  }
  if (!res.ok) {
    const detail = (payload as { detail?: unknown } | null)?.detail ?? payload
    throw new ApiError(res.status, detail)
  }
  return payload as T
}

export const getJSON = <T>(path: string, params?: Params) => request<T>('GET', path, undefined, params)
export const postJSON = <T>(path: string, body: unknown = {}, params?: Params) =>
  request<T>('POST', path, body, params)
export const putJSON = <T>(path: string, body: unknown, params?: Params) =>
  request<T>('PUT', path, body, params)

/** SSE 生成事件：与后端 `api/streaming.py` 一一对应。 */
export type StreamEvent =
  | { type: 'stage'; label: string }
  | { type: 'delta'; text: string }
  | { type: 'reason'; text: string }
  | { type: 'done'; result: unknown }
  | {
      type: 'error'
      code?: string
      message: string
      status?: number
      retryable?: boolean
      findings?: Finding[]
    }

export type StreamHandlers = {
  onStage?: (label: string) => void
  onDelta?: (text: string) => void
  /** 模型思考过程；只有后端开了 reasoning 流才有。 */
  onReason?: (text: string) => void
  signal?: AbortSignal
}

/**
 * POST 一个生成接口，边读 SSE 边回调。完成的 payload 与同步接口一致。
 * 用 fetch + ReadableStream 而不是 EventSource：EventSource 不能带 body。
 */
export async function streamPost<T>(
  path: string,
  body: unknown,
  handlers: StreamHandlers = {},
  params?: Params,
): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${withQuery(path, params)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body ?? {}),
      signal: handlers.signal,
    })
  } catch (e) {
    if ((e as { name?: string })?.name === 'AbortError') throw e
    throw new ApiError(0, '连不上后端（8010），先运行 ./scripts/dev.sh')
  }

  if (!res.ok) {
    const text = await res.text()
    let payload: unknown = text
    try {
      payload = text ? JSON.parse(text) : null
    } catch {
      /* 保留原文 */
    }
    const detail = (payload as { detail?: unknown } | null)?.detail ?? payload
    throw new ApiError(res.status, detail)
  }
  if (!res.body) throw new ApiError(0, '浏览器不支持流式响应')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let result: T | undefined
  let failure: ApiError | undefined

  const handle = (line: string) => {
    if (!line.startsWith('data:')) return
    let event: StreamEvent
    try {
      event = JSON.parse(line.slice(5).trim())
    } catch {
      return
    }
    if (event.type === 'stage') handlers.onStage?.(event.label)
    else if (event.type === 'delta') handlers.onDelta?.(event.text)
    else if (event.type === 'reason') handlers.onReason?.(event.text)
    else if (event.type === 'done') result = event.result as T
    else if (event.type === 'error') {
      failure = new ApiError(event.status ?? 400, {
        message: event.message,
        code: event.code,
        findings: event.findings,
      })
    }
  }

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let cut = buf.indexOf('\n\n')
    while (cut >= 0) {
      const block = buf.slice(0, cut)
      buf = buf.slice(cut + 2)
      for (const line of block.split('\n')) handle(line)
      cut = buf.indexOf('\n\n')
    }
  }
  // 收尾：最后一块没有空行分隔时也别丢。
  for (const line of buf.split('\n')) handle(line)

  if (failure) throw failure
  if (result === undefined) throw new ApiError(0, '生成中断：没有收到完成事件')
  return result
}

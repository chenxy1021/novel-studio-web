// The two mock books have different depths: the signal-tower book is authored in full here,
// the hunting-ground book reuses the shared world layer until its own bible is written.
import * as signal from './signalTower'
import * as hunting from './huntingGround'
import type { Book } from './types'

const sharedWorld = signal.world.map((w, i) => ({ ...w }))
const sharedRules = signal.rules.map((r) => ({ ...r }))
const sharedFactions = signal.factions.map((f) => ({ ...f }))

export const huntingBundle = {
  ...hunting,
  foreshadows: signal.foreshadows.map((f) => ({ ...f })),
  world: sharedWorld,
  rules: sharedRules,
  factions: sharedFactions,
  outline: signal.outline.map((v) => ({ ...v, done: v.index === 1 ? hunting.chapters.filter((c) => c.number <= 10).length : 0 })),
  timeline: hunting.chapters.map((c) => ({ chapter: c.number, inWorldDay: c.number, summary: c.summary })),
  usage: signal.usage.map((u) => ({ ...u, chapter: ((u.chapter - 1) % 15) + 1 })),
  chapterIssues: {} as Record<number, typeof signal.chapterIssues[number]>,
  spineText: hunting.chapters.reduce<Record<number, string>>((acc, c) => {
    acc[c.number] = `第${c.number}章 · ${c.title}\n\n${c.summary}\n\n（示例正文占位：接上真 API 后从 chapters/${String(c.number).padStart(3, '0')}.md 读取）`
    return acc
  }, {}),
} satisfies Omit<typeof signal, "makeBatchCheck" | "raw">

export const shelf = {
  signalTower: signal,
  huntingGround: huntingBundle,
} as const

// The two demo books have different depths: the night-mail book is authored in full here,
// the night-market book reuses the shared world layer until its own bible is written.
import * as mail from './demoMail'
import * as market from './demoMarket'
import type { Book } from './types'

const sharedWorld = mail.world.map((w) => ({ ...w }))
const sharedRules = mail.rules.map((r) => ({ ...r }))
const sharedFactions = mail.factions.map((f) => ({ ...f }))

export const marketBundle = {
  ...market,
  foreshadows: mail.foreshadows.map((f) => ({ ...f })),
  world: sharedWorld,
  rules: sharedRules,
  factions: sharedFactions,
  outline: mail.outline.map((v) => ({ ...v, done: v.index === 1 ? market.chapters.filter((c) => c.number <= 10).length : 0 })),
  timeline: market.chapters.map((c) => ({ chapter: c.number, inWorldDay: c.number, summary: c.summary })),
  usage: mail.usage.map((u) => ({ ...u, chapter: ((u.chapter - 1) % 15) + 1 })),
  chapterIssues: {} as Record<number, typeof mail.chapterIssues[number]>,
  spineText: market.chapters.reduce<Record<number, string>>((acc, c) => {
    acc[c.number] = `第${c.number}章 · ${c.title}\n\n${c.summary}\n\n（示例正文占位：接上真 API 后从 chapters/${String(c.number).padStart(3, '0')}.md 读取）`
    return acc
  }, {}),
} satisfies Omit<typeof mail, 'makeBatchCheck' | 'raw'>

export const shelf = {
  demoMail: mail,
  demoMarket: marketBundle,
} as const

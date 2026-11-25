/** 本章参考资料包：与生成提示词同源，条数不在前端估算。 */
import { getJSON, postJSON } from './client'

export type ReferenceSection = {
  key: string
  group: string
  label: string
  count: number
  /** 真正展开进提示词的条数；少于 count 时模型只看到名字，没看到细节。 */
  kept: number
  chars: number
  preview: string
  missing: boolean
  optional: boolean
  truncated: boolean
  source: string
  text: string
}

/** 写前解析命中的一个实体：名字 + 命中来源 + 一句为什么。 */
export type EntityHit = { name: string; source: string; why: string }

/** 本章实体清单：写前从细纲 / 台阶 / 上一章记忆 / 近两章出场里解析出来的。 */
export type ChapterEntities = {
  chapter: number
  title: string
  signals: string[]
  characters: EntityHit[]
  places: EntityHit[]
  items: EntityHit[]
  factions: EntityHit[]
  terms: EntityHit[]
  foreshadows: EntityHit[]
  count: number
}

export type ReferencePack = {
  chapter: number
  title: string
  stage?: string
  sections: ReferenceSection[]
  entities?: ChapterEntities
  summary: { sections: number; items: number; chars: number }
  prompt?: string
}

export type FocusRef = { type: string; key: string; label?: string }

export type SkillToggles = Record<string, boolean>

export async function fetchReferences(
  dir: string,
  chapter: number,
  stage: 'outline' | 'prose' = 'prose',
  skills?: SkillToggles,
): Promise<ReferencePack> {
  return getJSON<ReferencePack>(`/projects/chapters/${chapter}/references`, {
    dir,
    stage,
    ...(skills ? { skills: JSON.stringify(skills) } : {}),
  })
}

export async function previewReferences(
  dir: string,
  chapter: number,
  focus: FocusRef[],
  stage: 'outline' | 'prose' = 'prose',
  skills?: SkillToggles,
): Promise<ReferencePack> {
  return postJSON<ReferencePack>(
    `/projects/chapters/${chapter}/references/preview`,
    { focus, stage, ...(skills ? { skills } : {}) },
    { dir },
  )
}

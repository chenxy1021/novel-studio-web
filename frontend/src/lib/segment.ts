import type { Segment, SegmentStage } from '@/mocks/types'

/** 段落纲的台阶；老数据可能没有 stages，统一兜成空数组。 */
export function segmentStages(s: Segment): SegmentStage[] {
  return s.plan?.stages ?? []
}

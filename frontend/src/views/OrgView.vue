<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Button, Card, Tag, EmptyState } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import { useStudio } from '@/stores/studio'
import type { CareerView, OrganizationNode } from '@/api/extras'

const studio = useStudio()
type OrgTab = 'tree' | 'career'
const tab = ref<OrgTab>('tree')

const hierarchy = computed(() => studio.hierarchy)
const orgs = computed(() => hierarchy.value?.organizations ?? [])
const careers = computed(() => hierarchy.value?.careers ?? [])

/** 深度优先摊平成带缩进的行：组织层级最多三层，不需要递归组件。 */
type OrgRow = { node: OrganizationNode; depth: number }
const rows = computed<OrgRow[]>(() => {
  const children = new Map<number | null, OrganizationNode[]>()
  for (const o of orgs.value) {
    const key = o.parentId ?? null
    const list = children.get(key) ?? []
    list.push(o)
    children.set(key, list)
  }
  const out: OrgRow[] = []
  const walk = (parent: number | null, depth: number) => {
    if (depth > 8) return
    for (const node of children.get(parent) ?? []) {
      // 已被环检测断开的节点 parentId 是 null，会从根进来；这里不会再走一遍。
      if (out.some((r) => r.node.id === node.id)) continue
      out.push({ node, depth })
      walk(node.id, depth + 1)
    }
  }
  walk(null, 0)
  // 极端情况下有节点既没有父也不在根上（父级 id 解析失败）：补在最后，别让数据消失。
  for (const o of orgs.value) {
    if (!out.some((r) => r.node.id === o.id)) out.push({ node: o, depth: 0 })
  }
  return out
})

const memberTotal = computed(() => orgs.value.reduce((s, o) => s + o.members.length, 0))
const unknownMembers = computed(
  () => orgs.value.reduce((s, o) => s + o.members.filter((m) => !m.known).length, 0),
)

function reload() {
  void studio.loadHierarchy()
}

onMounted(() => {
  if (!studio.hierarchy) reload()
})

function rankOf(c: CareerView): string {
  return c.levels.map((l) => l.name).filter(Boolean).join(' → ')
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="资料 · 结构"
      title="组织"
      desc="势力内部谁管谁、谁在哪个位置；这本书里升一级靠什么。和「势力」不是一回事：势力回答有哪些阵营，组织回答阵营里面的座位。"
    >
      <Button
        :disabled="studio.hierarchyGenBusy || !studio.ready"
        icon="✦"
        @click="studio.generateHierarchy()"
      >
        {{ studio.hierarchyGenBusy ? '整理中…' : '按已有设定整理' }}
      </Button>
      <Button variant="ghost" :disabled="studio.hierarchyBusy" @click="reload">刷新</Button>
    </PageHeader>

    <div class="orgbar">
      <div class="toggle" role="tablist" aria-label="组织与职业">
        <button :class="{ on: tab === 'tree' }" role="tab" @click="tab = 'tree'">
          组织架构 <span class="num">{{ orgs.length }}</span>
        </button>
        <button :class="{ on: tab === 'career' }" role="tab" @click="tab = 'career'">
          职业等级 <span class="num">{{ careers.length }}</span>
        </button>
      </div>
      <div class="orgbar__meta">
        <span>{{ memberTotal }} 个职位</span>
        <span v-if="unknownMembers">· {{ unknownMembers }} 个名字不在人物列表</span>
      </div>
    </div>

    <Card v-if="hierarchy?.warnings.length" title="需要你确认的地方" tone="warn" class="warncard">
      <ul class="warnlist">
        <li v-for="w in hierarchy.warnings" :key="w">{{ w }}</li>
      </ul>
    </Card>

    <template v-if="tab === 'tree'">
      <EmptyState
        v-if="!orgs.length && !studio.hierarchyBusy"
        icon="网"
        title="还没有组织架构"
        desc="人物和势力已经有了的话，点右上「按已有设定整理」；模型只整理已有内容，不会凭空造人。"
      >
        <Button variant="primary" :disabled="studio.hierarchyGenBusy" @click="studio.generateHierarchy()">
          整理组织架构
        </Button>
      </EmptyState>

      <div v-else class="tree">
        <div
          v-for="row in rows"
          :key="row.node.id"
          class="org"
          :class="[`org--d${Math.min(row.depth, 2)}`, { 'org--unknown': row.node.members.some((m) => !m.known) }]"
          :style="{ '--depth': row.depth }"
        >
          <div class="org__head">
            <span class="org__branch" aria-hidden="true">{{ row.depth ? '└' : '◆' }}</span>
            <b class="org__name">{{ row.node.name }}</b>
            <Tag v-if="row.node.kind" size="sm" tone="info">{{ row.node.kind }}</Tag>
            <Tag v-if="row.node.leader" size="sm" tone="gold">首领 {{ row.node.leader }}</Tag>
            <span v-if="row.node.parent" class="org__parent">上级：{{ row.node.parent }}</span>
          </div>
          <p v-if="row.node.summary" class="org__summary">{{ row.node.summary }}</p>
          <div v-if="row.node.members.length" class="org__members">
            <span
              v-for="m in row.node.members"
              :key="`${row.node.id}-${m.name}-${m.role}`"
              class="seat"
              :class="{ 'seat--unknown': !m.known }"
              :title="m.known ? '' : '这个名字不在人物卡里，可能是模型写错了'"
            >
              <b>{{ m.name }}</b>
              <span v-if="m.role || m.rank">{{ m.role || m.rank }}<template v-if="m.role && m.rank"> · {{ m.rank }}</template></span>
            </span>
          </div>
          <p v-else class="org__empty">还没写成员。组织架构只整理已有设定，缺的人等正文写到了再补。</p>
        </div>
      </div>
    </template>

    <template v-else>
      <EmptyState
        v-if="!careers.length && !studio.hierarchyBusy"
        icon="阶"
        title="还没有职业等级体系"
        desc="现代题材可以写职级/军衔，玄幻可以写门派位阶；没有明确等级也可以不建，不要为了有体系硬造台阶。"
      >
        <Button variant="primary" :disabled="studio.hierarchyGenBusy" @click="studio.generateHierarchy()">
          整理职业等级
        </Button>
      </EmptyState>

      <div v-else class="careers">
        <Card v-for="c in careers" :key="c.name" :title="c.name" :desc="c.summary" tone="paper">
          <template #actions>
            <Tag v-if="c.levels.length" size="sm" tone="neutral">{{ c.levels.length }} 级</Tag>
          </template>
          <div v-if="c.appliesTo.length" class="career__applies">
            <span>适用：</span>
            <Tag v-for="a in c.appliesTo" :key="a" size="sm" tone="neutral">{{ a }}</Tag>
          </div>
          <ol v-if="c.levels.length" class="ladder">
            <li v-for="(l, i) in c.levels" :key="`${c.name}-${l.name}`" class="ladder__step">
              <span class="ladder__no">{{ i + 1 }}</span>
              <div class="ladder__body">
                <b>{{ l.name }}</b>
                <Tag v-if="l.rank" size="sm" tone="info">{{ l.rank }}</Tag>
                <p v-if="l.trait">{{ l.trait }}</p>
                <p v-if="l.gap" class="ladder__gap">差在哪：{{ l.gap }}</p>
              </div>
            </li>
          </ol>
          <p v-else class="org__empty">还没写台阶。</p>
          <p v-if="c.advancement" class="career__advance">晋升条件：{{ c.advancement }}</p>
          <p v-if="!c.advancement && rankOf(c)" class="career__advance">台阶：{{ rankOf(c) }}</p>
        </Card>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.orgbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ns-s3);
  flex-wrap: wrap;
  margin-bottom: var(--ns-s4);
}
.orgbar__meta {
  display: flex;
  gap: 8px;
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
}
.toggle {
  display: inline-flex;
  padding: 2px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.toggle button {
  border: 0;
  background: transparent;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 12px;
  padding: 5px 14px;
  border-radius: 4px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.toggle button.on {
  background: var(--ns-card);
  color: var(--ns-ink);
  font-weight: 600;
  box-shadow: var(--ns-shadow-1);
}
.toggle .num {
  font-size: 10.5px;
  color: var(--ns-ink-3);
  font-variant-numeric: tabular-nums;
}
.warncard {
  margin-bottom: var(--ns-s4);
}
.warnlist {
  margin: 0;
  padding-left: 18px;
  font-size: var(--ns-fs-12);
  line-height: 1.8;
  color: var(--ns-ink-2);
}
.tree {
  display: grid;
  gap: 10px;
}
.org {
  border: 1px solid var(--ns-line);
  border-left: 3px solid var(--ns-pink);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  padding: 14px 16px;
  margin-left: calc(var(--depth) * 22px);
}
.org--d0 {
  border-left-color: var(--ns-pink);
}
.org--d1 {
  border-left-color: var(--ns-line-2);
}
.org--d2 {
  border-left-color: var(--ns-line-2);
  opacity: 0.96;
}
.org__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.org__branch {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.org__name {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
}
.org__parent {
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
  margin-left: auto;
}
.org__summary {
  margin: 6px 0 10px;
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-2);
  line-height: 1.65;
}
.org__members {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.seat {
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-xs);
  background: var(--ns-card-2);
  padding: 2px 8px;
  font-size: var(--ns-fs-11);
}
.seat b {
  font-weight: 600;
}
.seat span {
  color: var(--ns-ink-3);
}
.seat--unknown {
  border-color: color-mix(in srgb, var(--ns-warn) 45%, transparent);
  background: var(--ns-warn-soft);
}
.org__empty {
  margin: 6px 0 0;
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
}
.careers {
  display: grid;
  gap: var(--ns-s4);
}
.career__applies {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
  margin-bottom: 10px;
}
.ladder {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.ladder__step {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.ladder__no {
  flex: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--ns-pink-soft);
  color: var(--ns-pink);
  font-size: 10.5px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.ladder__body {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.ladder__body p {
  flex-basis: 100%;
  margin: 0;
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-2);
  line-height: 1.55;
}
.ladder__gap {
  color: var(--ns-ink-3) !important;
}
.career__advance {
  margin: 12px 0 0;
  padding-top: 10px;
  border-top: 1px dashed var(--ns-line);
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-2);
}
</style>

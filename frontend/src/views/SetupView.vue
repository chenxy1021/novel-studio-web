<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Card, Tag, Table, type Column } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import GenStream from '@/components/GenStream.vue'
import { useStudio } from '@/stores/studio'
import type { CharacterRelation, GlossaryTerm, HistoryEvent, PowerLevel, SocietyProfile } from '@/mocks'

const studio = useStudio()
const router = useRouter()
const route = useRoute()
type SetupTab = 'rules' | 'world' | 'factions' | 'locations' | 'items' | 'relations' | 'gaps' | 'threads'
const tab = ref<SetupTab>(routeTab())

function routeTab(): SetupTab {
  const q = String(route.query.tab || '')
  const known: SetupTab[] = ['world', 'factions', 'locations', 'items', 'relations', 'gaps', 'threads']
  return known.includes(q as SetupTab) ? (q as SetupTab) : 'rules'
}

const rules = computed(() => studio.data.rules)
const factions = computed(() => studio.data.factions)
const locations = computed(() => studio.data.locations)
const items = computed(() => studio.data.items)
const powerSystem = computed(() => studio.data.powerSystem)
const society = computed(() => studio.data.society)
const history = computed(() => studio.data.history)
const glossary = computed(() => studio.data.glossary)
const relations = computed(() => studio.relations)
const infoGaps = computed(() => studio.infoGaps)

const powerFilled = computed(() => {
  const p = powerSystem.value
  return Boolean(
    p.name || p.summary || p.advancement || p.costs || p.limits || p.balance || p.levels.length,
  )
})
const SOCIETY_LABELS: Array<[keyof SocietyProfile, string]> = [
  ['politics', '政治'],
  ['economy', '经济'],
  ['currency', '货币'],
  ['law', '律法'],
  ['taboo', '禁忌'],
  ['customs', '风俗'],
  ['religion', '宗教'],
  ['language', '语言'],
  ['technology', '技术'],
]
const societyRows = computed(() =>
  SOCIETY_LABELS.map(([key, label]) => ({ key, label, text: society.value[key] })).filter((r) => r.text),
)
const worldCount = computed(
  () => (powerFilled.value ? 1 : 0) + (societyRows.value.length ? 1 : 0) + history.value.length + glossary.value.length,
)

const powerCols: Column<PowerLevel>[] = [
  { key: 'name', label: '台阶', width: '18%' },
  { key: 'rank', label: '位阶', width: '16%' },
  { key: 'trait', label: '这一级的特征' },
  { key: 'gap', label: '和上一级的差距', width: '28%' },
]
const historyCols: Column<HistoryEvent>[] = [
  { key: 'era', label: '时代', width: '16%' },
  { key: 'year', label: '年份', width: '12%' },
  { key: 'event', label: '事件', width: '34%' },
  { key: 'impact', label: '对现在的影响' },
]
const glossaryCols: Column<GlossaryTerm>[] = [
  { key: 'term', label: '术语', width: '22%' },
  { key: 'meaning', label: '含义' },
  { key: 'usage', label: '正文里怎么用', width: '30%' },
]

/** 规则按可违反程度分组：铁律 / 契约 / 惯例 / 谣言。 */
const ENFORCE_ORDER = ['铁律', '契约', '惯例', '谣言'] as const
const ENFORCE_DESC: Record<(typeof ENFORCE_ORDER)[number], string> = {
  铁律: '破不了。人物/世界会因此不成立，只能绕开。',
  契约: '能破，但必须当场付代价：反噬、折寿、失忆、违约反扑。',
  惯例: '能破，代价是社会性的：被逐出、失信、得罪势力。',
  谣言: '人物以为是规则，其实不成立；打破它时要揭示真相。',
}
const ruleFilter = ref<'all' | (typeof ENFORCE_ORDER)[number]>('all')
const ruleGroups = computed(() =>
  ENFORCE_ORDER.map((k) => ({ key: k, desc: ENFORCE_DESC[k], rows: rules.value.filter((r) => r.enforce === k) })).filter(
    (g) => g.rows.length && (ruleFilter.value === 'all' || ruleFilter.value === g.key),
  ),
)
const enforceTone: Record<(typeof ENFORCE_ORDER)[number], 'bad' | 'gold' | 'neutral' | 'ink'> = {
  铁律: 'bad',
  契约: 'gold',
  惯例: 'neutral',
  谣言: 'ink',
}
/** 筛选按钮左侧的小色点，和规则组标题的颜色对应。 */
const enforceColor: Record<(typeof ENFORCE_ORDER)[number], string> = {
  铁律: 'var(--ns-bad)',
  契约: 'var(--ns-gold)',
  惯例: 'var(--ns-ink-3)',
  谣言: 'var(--ns-ink-2)',
}
function enforceCount(k: (typeof ENFORCE_ORDER)[number]): number {
  return rules.value.filter((r) => r.enforce === k).length
}
const ruleFilterOptions = computed(() => [
  { key: 'all' as const, label: '全部', count: rules.value.length, color: '' },
  ...ENFORCE_ORDER.map((k) => ({ key: k, label: k, count: enforceCount(k), color: enforceColor[k] })),
])

const relationQ = ref('')
const relationRows = computed(() => {
  const needle = relationQ.value.trim()
  return [...relations.value]
    .filter((r) =>
      !needle ||
      [r.a, r.b, r.state, r.note].join(' ').includes(needle),
    )
    .sort((x, y) => (y.chapter || 0) - (x.chapter || 0) || x.a.localeCompare(y.a, 'zh'))
})

/* 关系矩阵：行、列都是人物，序号在两侧；单元格是两人当前关系。 */
const relView = ref<'matrix' | 'list'>('matrix')

const canonicalName = computed(() => {
  const map = new Map<string, string>()
  for (const c of studio.characters) {
    map.set(c.name, c.name)
    for (const a of c.aliases) map.set(a, c.name)
  }
  return map
})
const canonOf = (raw: string) => canonicalName.value.get(raw) || raw

const matrixAxis = computed(() => {
  const involved = new Set<string>()
  for (const r of relations.value) {
    involved.add(canonOf(r.a))
    involved.add(canonOf(r.b))
  }
  const names: string[] = []
  const push = (name: string) => {
    if (name && !names.includes(name)) names.push(name)
  }
  // 先按人物卡顺序（核心在前），再补只出现在关系里的名字。
  for (const c of studio.characters) if (involved.has(c.name)) push(c.name)
  for (const r of relations.value) {
    push(canonOf(r.a))
    push(canonOf(r.b))
  }
  return names.map((name, i) => ({ name, index: i + 1 }))
})

const relationIndex = computed(() => {
  const map = new Map<string, CharacterRelation>()
  for (const r of relations.value) {
    const a = canonOf(r.a)
    const b = canonOf(r.b)
    if (!a || !b || a === b) continue
    map.set(`${a}\u0000${b}`, { ...r, a, b })
  }
  return map
})

type MatrixEdge = { state: string; note: string; chapter: number; dir: '→' | '←' | '↔' }

function cellEdges(row: string, col: string): MatrixEdge[] {
  if (row === col) return []
  const direct = relationIndex.value.get(`${row}\u0000${col}`)
  const reverse = relationIndex.value.get(`${col}\u0000${row}`)
  if (direct && reverse && direct.state === reverse.state) {
    return [{
      state: direct.state,
      note: [direct.note, reverse.note].filter(Boolean).join('；'),
      chapter: Math.max(direct.chapter, reverse.chapter),
      dir: '↔',
    }]
  }
  const out: MatrixEdge[] = []
  if (direct) out.push({ state: direct.state, note: direct.note, chapter: direct.chapter, dir: '→' })
  if (reverse) out.push({ state: reverse.state, note: reverse.note, chapter: reverse.chapter, dir: '←' })
  return out
}

function cellTitle(row: string, col: string): string {
  const edges = cellEdges(row, col)
  if (!edges.length) return `${row} ↔ ${col}：设定里还没有这组关系`
  return edges.map((e) => {
    const head = e.dir === '↔' ? `${row} ↔ ${col}` : e.dir === '→' ? `${row} → ${col}` : `${col} → ${row}`
    const note = e.note ? `（${e.note}）` : ''
    const chapter = e.chapter ? ` · 截至第 ${e.chapter} 章` : ''
    return `${head}：${e.state || '有往来'}${note}${chapter}`
  }).join('\n')
}

const relationCols: Column<CharacterRelation>[] = [
  { key: 'a', label: '甲', width: '15%' },
  { key: 'b', label: '乙', width: '15%' },
  { key: 'state', label: '当前关系', width: '24%' },
  { key: 'note', label: '备注 / 怎么变成这样' },
  {
    key: 'chapter',
    label: '截至章',
    align: 'right',
    width: '84px',
    render: (r: CharacterRelation) => (r.chapter ? `第 ${r.chapter} 章` : '—'),
  },
]

type ThreadRow = { id: string; name: string; due: number | string; known: string; change: string }
const threadRows = computed<ThreadRow[]>(() =>
  studio.foreshadows
    .filter((f) => f.status === 'open')
    .map((f) => ({
      id: f.id,
      name: f.name,
      due: f.dueChapter ?? '—',
      known: f.revealWho || '—',
      change: f.revealChange || f.hint || '—',
    })),
)
const threadCols: Column<ThreadRow>[] = [
  { key: 'name', label: '悬而未决的事', width: '32%' },
  { key: 'due', label: '计划交代章', numeric: true, width: '110px' },
  { key: 'known', label: '谁先知道', width: '120px' },
  { key: 'change', label: '交代后改变什么' },
]

const liveSettings = computed(
  () => studio.liveGen.active && (studio.liveGen.kind === 'settings' || studio.liveGen.kind === 'supplement'),
)

const counts = computed(() => ({
  rules: rules.value.length,
  world: worldCount.value,
  factions: factions.value.length,
  locations: locations.value.length,
  items: items.value.length,
  relations: relations.value.length,
  gaps: infoGaps.value.length,
  threads: threadRows.value.length,
}))

/** 补设定会抛错（toast 已提示），这里吞掉避免模板里的 unhandled rejection。 */
async function supplement() {
  try {
    await studio.supplementSettings(8)
  } catch {
    /* 已 toast */
  }
}

/** 重拆设定同理：store 已 toast，模板里不再留未处理 rejection。 */
async function runSettings() {
  try {
    await studio.generateSettings()
  } catch {
    /* 已 toast */
  }
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="写正文的参考资料"
      title="设定"
      desc="规则按「能不能破、破了付什么」分四类；世界纵深写力量台阶、社会常识、大事记与术语；物品写清谁拿着、什么状态；关系和信息差写清谁瞒着谁。这些都会进正文的参考资料包。"
    >
      <Button icon="✎" variant="ghost" @click="router.push({ name: 'style' })">文风设置 →</Button>
      <Button
        v-if="studio.chapters.length"
        icon="↻"
        variant="ghost"
        :disabled="studio.settingsBusy"
        title="只看最近 8 章正文，已有条目一律跳过"
        @click="supplement"
      >从正文补（不重复）</Button>
      <Button
        variant="pink"
        icon="⚙"
        :disabled="studio.settingsBusy || !studio.book.outlineText"
        @click="runSettings"
      >
        {{ studio.settingsBusy ? '正在拆人物和设定…' : counts.rules || studio.characters.length || counts.world ? '重新拆设定（不覆盖）' : '生成设定' }}
      </Button>
    </PageHeader>

    <GenStream
      v-if="liveSettings"
      :active="studio.liveGen.active"
      :text="studio.liveGen.text"
      :title="studio.liveGen.title"
      :stage="studio.liveGen.stage"
      :kind="studio.liveGen.kind"
      :started-at="studio.liveGen.startedAt"
      label="设定生成实况"
      class="livegen"
    />

    <div class="tabs" role="tablist">
      <button
        v-for="t in [
          { k: 'rules', t: '规则', n: counts.rules },
          { k: 'world', t: '世界纵深', n: counts.world },
          { k: 'factions', t: '势力与恩怨', n: counts.factions },
          { k: 'locations', t: '地点', n: counts.locations },
          { k: 'items', t: '物品', n: counts.items },
          { k: 'relations', t: '人物关系', n: counts.relations },
          { k: 'gaps', t: '信息差', n: counts.gaps },
          { k: 'threads', t: '悬而未决的事', n: counts.threads },
        ]"
        :key="t.k"
        role="tab"
        type="button"
        :aria-selected="tab === t.k"
        :class="{ on: tab === t.k }"
        @click="tab = t.k as typeof tab"
      >
        {{ t.t }} <span class="ns-num">{{ t.n }}</span>
      </button>
    </div>

    <p class="tabhint">
      时间线只在「记忆」页维护——那里是逐章记忆的原始账本，这里再放一份会两处对不上。
      <button type="button" class="tabhint__link" @click="router.push({ name: 'memory', query: { tab: 'timeline' } })">
        去记忆页看时间线 →
      </button>
    </p>

    <div v-if="tab === 'rules'" class="rules">
      <div class="ruletool">
        <div class="rfilters" role="group" aria-label="按可违反程度筛选规则">
          <button
            v-for="o in ruleFilterOptions"
            :key="o.key"
            type="button"
            class="rfilter"
            :class="{ on: ruleFilter === o.key }"
            :style="o.color ? { '--rf': o.color } : undefined"
            :aria-pressed="ruleFilter === o.key"
            @click="ruleFilter = o.key"
          >
            <i v-if="o.color" class="rfilter__dot" aria-hidden="true" />
            {{ o.label }}
            <span class="ns-num">{{ o.count }}</span>
          </button>
        </div>
        <span class="ruletool__hint">按可违反程度分组；点一个类别只看这一类</span>
      </div>

      <section v-for="g in ruleGroups" :key="g.key" class="rulegroup">
        <header class="rulegroup__head">
          <Tag size="sm" :tone="enforceTone[g.key]">{{ g.key }}</Tag>
          <p>{{ g.desc }}</p>
          <span class="ns-num">{{ g.rows.length }} 条</span>
        </header>
        <Card v-for="r in g.rows" :key="r.id" flush class="rule">
          <div class="rule__head">
            <Tag size="sm" :tone="enforceTone[g.key]">{{ r.enforce }}</Tag>
            <b>{{ r.text }}</b>
            <span v-if="r.enforcer" class="rule__state">执行：{{ r.enforcer }}</span>
            <span v-if="r.tested" class="rule__state">{{ r.tested.includes('未') ? '未实测' : '已实测' }}</span>
          </div>
          <div class="rule__grid">
            <div>
              <span class="ns-eyebrow">违反代价</span>
              <p>{{ r.cost || '—' }}</p>
            </div>
            <div>
              <span class="ns-eyebrow">边界 / 漏洞</span>
              <p>{{ r.boundary || r.loophole || '—' }}</p>
            </div>
            <div v-if="r.tested">
              <span class="ns-eyebrow">实测</span>
              <p>{{ r.tested }}</p>
            </div>
            <div v-if="r.forbidden.length">
              <span class="ns-eyebrow">禁止出现</span>
              <p class="rule__ban">
                <Tag v-for="b in r.forbidden" :key="b" size="sm" tone="bad">{{ b }}</Tag>
              </p>
            </div>
          </div>
        </Card>
      </section>

      <Card
        v-if="!rules.length"
        title="还没有规则"
        desc="规则由「生成设定 / 补充设定」从大纲和世界观里拆出来；铁律、契约、惯例、谣言四类都要有。"
      />
      <Card
        v-else-if="!ruleGroups.length"
        title="这一类还没有规则"
        desc="换一个类别，或让「补充设定」按世界观补上这一类。"
      />
    </div>

    <div v-else-if="tab === 'world'" class="worldlore">
      <Card
        v-if="powerFilled"
        :title="powerSystem.name || '力量体系'"
        :desc="powerSystem.summary || '修行、异能、魔法或科技分级的台阶：每一级能做什么、拿什么换、为什么打不过上一级。'"
      >
        <div class="kv">
          <div v-if="powerSystem.advancement">
            <span class="ns-eyebrow">怎么晋升</span>
            <p>{{ powerSystem.advancement }}</p>
          </div>
          <div v-if="powerSystem.costs">
            <span class="ns-eyebrow">用什么换</span>
            <p>{{ powerSystem.costs }}</p>
          </div>
          <div v-if="powerSystem.limits">
            <span class="ns-eyebrow">上限 / 做不到</span>
            <p>{{ powerSystem.limits }}</p>
          </div>
          <div v-if="powerSystem.balance">
            <span class="ns-eyebrow">平衡点</span>
            <p>{{ powerSystem.balance }}</p>
          </div>
        </div>
        <Table
          v-if="powerSystem.levels.length"
          class="loretable"
          :columns="powerCols"
          :rows="powerSystem.levels"
          dense
          striped
          row-key="name"
        />
      </Card>
      <Card
        v-else
        title="力量体系"
        desc="这本书的世界观里没有修行、异能、魔法或等级分档，所以这一栏为空是正常的；有的话，「补充设定」会把它拆成台阶。"
      />

      <Card
        v-if="societyRows.length"
        title="社会常识"
        desc="政治、经济、货币、律法、禁忌、风俗、宗教、语言、技术——正文里用来区分阶层、地域和冲突的那一层。"
      >
        <div class="kv">
          <div v-for="row in societyRows" :key="row.key">
            <span class="ns-eyebrow">{{ row.label }}</span>
            <p>{{ row.text }}</p>
          </div>
        </div>
      </Card>

      <Card v-if="history.length" title="世界大事记" flush>
        <Table :columns="historyCols" :rows="history" dense striped row-key="event" />
      </Card>

      <Card v-if="glossary.length" title="术语表" flush>
        <Table :columns="glossaryCols" :rows="glossary" dense striped row-key="term" />
      </Card>

      <Card
        v-if="!worldCount"
        title="还没有世界纵深"
        desc="「生成设定 / 补充设定」会从大纲和世界观里拆出力量体系、社会常识、大事记和术语；它们和规则一起进正文的参考资料包。"
      />
    </div>

    <div v-else-if="tab === 'factions'" class="factions">
      <Card
        v-for="f in factions"
        :key="f.name"
        :title="f.name"
        :desc="[f.nature, f.state].filter(Boolean).join(' · ') || f.state"
      >
        <div class="faction">
          <div v-if="f.state">
            <span class="ns-eyebrow">当前状态</span>
            <p>
              {{ f.state }}
              <template v-if="f.stateAt">（截至第 {{ f.stateAt }} 章）</template>
            </p>
          </div>
          <div v-if="f.attitude">
            <span class="ns-eyebrow">对主角的态度</span>
            <p>{{ f.attitude }}</p>
          </div>
          <div>
            <span class="ns-eyebrow">明规则</span>
            <p>{{ f.openRule }}</p>
          </div>
          <div class="faction__hidden">
            <span class="ns-eyebrow">潜规则</span>
            <p>{{ f.hiddenRule }}</p>
          </div>
          <div>
            <span class="ns-eyebrow">欠下的账</span>
            <p>{{ f.debt }}</p>
          </div>
        </div>
      </Card>
    </div>

    <div v-else-if="tab === 'locations'" class="cardgrid">
      <Card
        v-for="l in locations"
        :key="l.id"
        :title="l.name"
        :desc="[l.owner && `归属：${l.owner}`, l.state].filter(Boolean).join(' · ') || l.text"
      >
        <div class="kv">
          <div v-if="l.geo">
            <span class="ns-eyebrow">地理</span>
            <p>{{ l.geo }}</p>
          </div>
          <div v-if="l.structure">
            <span class="ns-eyebrow">结构</span>
            <p>{{ l.structure }}</p>
          </div>
          <div v-if="l.senses">
            <span class="ns-eyebrow">感官</span>
            <p>{{ l.senses }}</p>
          </div>
          <div v-if="l.accessRules">
            <span class="ns-eyebrow">进出规矩</span>
            <p>{{ l.accessRules }}</p>
          </div>
          <div v-if="l.state">
            <span class="ns-eyebrow">当前状态</span>
            <p>
              {{ l.state }}
              <template v-if="l.stateAt">（截至第 {{ l.stateAt }} 章）</template>
            </p>
          </div>
          <div v-if="l.occupied">
            <span class="ns-eyebrow">现在被谁占着</span>
            <p>{{ l.occupied }}</p>
          </div>
          <div v-if="l.events">
            <span class="ns-eyebrow">发生的事</span>
            <p>{{ l.events }}</p>
          </div>
        </div>
      </Card>
      <Card
        v-if="!locations.length"
        title="还没有地点"
        desc="地点由「生成设定 / 补充设定」从大纲和世界观里拆出来；世界观页的地图也用它。"
      />
    </div>

    <div v-else-if="tab === 'items'" class="cardgrid">
      <Card
        v-for="it in items"
        :key="it.id"
        :title="it.name"
        :desc="[it.type, it.holder && `在${it.holder}手里`, it.state].filter(Boolean).join(' · ') || it.text"
      >
        <div class="kv">
          <div class="kv--wide">
            <span class="ns-eyebrow">此刻在哪</span>
            <p>
              <template v-if="it.holder">
                在 <b>{{ it.holder }}</b> 手里<template v-if="it.holderAt">（截至第 {{ it.holderAt }} 章）</template>
              </template>
              <template v-else-if="it.location">在 {{ it.location }}</template>
              <template v-else>未记录持有人</template>
            </p>
          </div>
          <div>
            <span class="ns-eyebrow">状态</span>
            <p>
              {{ it.state || '—' }}
              <template v-if="it.stateAt">（第 {{ it.stateAt }} 章）</template>
            </p>
          </div>
          <div v-if="it.appearance">
            <span class="ns-eyebrow">外观</span>
            <p>{{ it.appearance }}</p>
          </div>
          <div v-if="it.origin">
            <span class="ns-eyebrow">来历</span>
            <p>{{ it.origin }}</p>
          </div>
          <div v-if="it.function">
            <span class="ns-eyebrow">作用</span>
            <p>{{ it.function }}</p>
          </div>
          <div v-if="it.limit">
            <span class="ns-eyebrow">限制</span>
            <p>{{ it.limit }}</p>
          </div>
          <div v-if="it.cost">
            <span class="ns-eyebrow">代价</span>
            <p>{{ it.cost }}</p>
          </div>
          <div v-if="it.whoKnows">
            <span class="ns-eyebrow">谁知道</span>
            <p>{{ it.whoKnows }}</p>
          </div>
        </div>
        <div v-if="it.transferLog.length" class="transfer">
          <span class="ns-eyebrow">转手记录</span>
          <ol>
            <li v-for="(t, i) in it.transferLog" :key="`${t.chapter}-${i}`">
              <b class="ns-num">{{ t.chapter ? `第${t.chapter}章` : '—' }}</b>
              <span>{{ t.from ? `${t.from} → ` : '' }}{{ t.to }}</span>
              <em v-if="t.note">{{ t.note }}</em>
            </li>
          </ol>
        </div>
      </Card>
      <Card
        v-if="!items.length"
        title="还没有物品"
        desc="只会收后面还会被提到、使用、追查的东西；一次性道具不进设定。"
      />
    </div>

    <Card v-else-if="tab === 'relations'" flush>
      <div class="relbar">
        <div class="relviews" role="group" aria-label="人物关系的两种看法">
          <button
            type="button"
            :class="{ on: relView === 'matrix' }"
            :aria-pressed="relView === 'matrix'"
            @click="relView = 'matrix'"
          >关系矩阵</button>
          <button
            type="button"
            :class="{ on: relView === 'list' }"
            :aria-pressed="relView === 'list'"
            @click="relView = 'list'"
          >明细列表</button>
        </div>
        <span class="relbar__meta">{{ matrixAxis.length }} 人 · {{ relations.length }} 组关系</span>
      </div>

      <div v-if="!relations.length" class="empty">
        <b>还没有人物关系</b>
        <p>生成设定时会从大纲里拆出关系矩阵；写正文时关系变化会按章汇总到这里。</p>
      </div>

      <div v-else-if="relView === 'matrix'" class="matrixwrap">
        <table class="relmatrix">
          <caption class="ns-sr-only">人物关系矩阵：行和列都是人物，单元格是两人当前关系</caption>
          <thead>
            <tr>
              <th class="corner" scope="col">#</th>
              <th v-for="c in matrixAxis" :key="c.name" scope="col">
                <span class="rn">{{ c.index }}</span><span class="nm">{{ c.name }}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in matrixAxis" :key="row.name">
              <th scope="row">
                <span class="rn">{{ row.index }}</span><span class="nm">{{ row.name }}</span>
              </th>
              <td
                v-for="col in matrixAxis"
                :key="col.name"
                :class="{
                  'is-diag': row.name === col.name,
                  'has-rel': row.name !== col.name && cellEdges(row.name, col.name).length,
                }"
                :title="cellTitle(row.name, col.name)"
              >
                <template v-if="row.name === col.name">—</template>
                <template v-else-if="cellEdges(row.name, col.name).length">
                  <span v-for="(e, i) in cellEdges(row.name, col.name)" :key="i" class="rmrel">
                    <i>{{ e.dir }}</i>{{ e.state || e.note || '有往来' }}
                  </span>
                </template>
                <span v-else class="rmempty">·</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="matrixhint">
          行 → 列。单元格是两人当前关系；→ / ← 表示设定里只记了一个方向，↔ 表示两边说法一致。
          悬停看备注与截至章；备注多的时候切「明细列表」。
        </p>
      </div>

      <template v-else>
        <div class="tablebar">
          <input
            v-model="relationQ"
            class="tablebar__search"
            placeholder="搜人物、关系状态或备注…"
            aria-label="搜索人物关系"
          />
          <span class="tablebar__meta">{{ relationRows.length }} 条 · 按截至章从新到旧</span>
        </div>
        <Table
          v-if="relationRows.length"
          class="reltable"
          :columns="relationCols"
          :rows="relationRows"
          dense
          striped
        />
        <div v-else class="empty">
          <b>没有匹配的关系</b>
          <p>换个名字或关键词试试。</p>
        </div>
      </template>
    </Card>

    <Card v-else-if="tab === 'gaps'" flush>
      <ul v-if="infoGaps.length" class="gaplist">
        <li v-for="g in infoGaps" :key="g.secret">
          <b>{{ g.secret }}</b>
          <div class="gaplist__row">
            <span v-if="g.knows"><i>知道</i>{{ g.knows }}</span>
            <span v-if="g.doesntKnow"><i>不知道</i>{{ g.doesntKnow }}</span>
            <span v-if="g.thinksKnows"><i>以为知道</i>{{ g.thinksKnows }}</span>
            <span v-if="g.revealChapter"><i>揭晓</i>第 {{ g.revealChapter }} 章</span>
          </div>
        </li>
      </ul>
      <div v-else class="empty">
        <b>还没有信息差</b>
        <p>「谁瞒着谁、谁知道、谁不知道」是制造张力最直接的材料；人物页也会按人物汇总。</p>
      </div>
    </Card>

    <Card v-else flush>
      <Table :columns="threadCols" :rows="threadRows" dense striped row-key="id" />
    </Card>
  </div>
</template>

<style scoped>
.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.livegen {
  margin-bottom: var(--ns-s4);
}
.tabhint {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
  margin: 7px 0 14px;
  font-size: 11px;
  color: var(--ns-ink-4);
}
.tabhint__link {
  border: 0;
  background: transparent;
  padding: 0;
  font: inherit;
  font-size: 11px;
  color: var(--ns-pink);
  cursor: pointer;
}
.tabs {
  display: flex;
  gap: 2px;
  border-bottom: 1px solid var(--ns-line);
  margin-bottom: 16px;
  overflow-x: auto;
}
.tabs button {
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 13px;
  padding: 9px 14px 10px;
  cursor: pointer;
  white-space: nowrap;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-bottom: -1px;
}
.tabs button:hover {
  color: var(--ns-ink);
}
.tabs button.on {
  color: var(--ns-ink);
  border-bottom-color: var(--ns-pink);
  font-weight: 600;
}
.tabs button span {
  font-size: 10.5px;
  background: var(--ns-card-2);
  border-radius: var(--ns-r-pill);
  padding: 0 6px;
  color: var(--ns-ink-3);
}
.rules {
  display: grid;
  gap: 14px;
}
.worldlore {
  display: grid;
  gap: 14px;
}
.loretable {
  margin-top: 10px;
  border: 0;
  border-radius: 0;
}
.ruletool {
  display: flex;
  align-items: center;
  gap: 10px 16px;
  flex-wrap: wrap;
}
.rfilters {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.rfilter {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-pill);
  background: var(--ns-card);
  color: var(--ns-ink-2);
  font: inherit;
  font-size: 11.5px;
  line-height: 1.6;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
}
.rfilter__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--rf, var(--ns-ink-4));
}
.rfilter .ns-num {
  color: var(--ns-ink-4);
  font-size: 10px;
}
.rfilter:hover {
  border-color: var(--ns-line-2);
  background: var(--ns-card-2);
}
.rfilter.on {
  border-color: var(--rf, var(--ns-pink));
  background: color-mix(in srgb, var(--rf, var(--ns-pink)) 9%, var(--ns-card));
  color: var(--ns-ink);
}
.rfilter.on .ns-num {
  color: var(--ns-ink-2);
}
.rfilter:focus-visible {
  outline: none;
  box-shadow: var(--ns-focus);
}
.ruletool__hint {
  font-size: 11px;
  color: var(--ns-ink-4);
}
.tablebar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border-bottom: 1px solid var(--ns-line);
}
.tablebar__search {
  flex: 0 1 300px;
  height: 30px;
  padding: 0 10px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: 12px;
}
.tablebar__search:focus {
  outline: none;
  border-color: var(--ns-pink-line);
  box-shadow: var(--ns-focus);
}
.tablebar__meta {
  margin-left: auto;
  font-size: 11px;
  color: var(--ns-ink-4);
}
.reltable {
  border: 0;
  border-radius: 0;
}
.relbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 12px;
  border-bottom: 1px solid var(--ns-line);
}
.relviews {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-pill);
  background: var(--ns-card-2);
}
.relviews button {
  border: 0;
  border-radius: var(--ns-r-pill);
  background: transparent;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 11.5px;
  line-height: 1.6;
  padding: 3px 10px;
  cursor: pointer;
}
.relviews button:hover {
  color: var(--ns-ink);
}
.relviews button.on {
  background: var(--ns-card);
  color: var(--ns-ink);
  box-shadow: 0 1px 2px rgb(0 0 0 / 8%);
}
.relviews button:focus-visible {
  outline: none;
  box-shadow: var(--ns-focus);
}
.relbar__meta {
  margin-left: auto;
  font-size: 11px;
  color: var(--ns-ink-4);
}
.matrixwrap {
  overflow: auto;
  max-height: 66vh;
}
.relmatrix {
  border-collapse: separate;
  border-spacing: 0;
  min-width: 100%;
  font-size: 11.5px;
}
.relmatrix th,
.relmatrix td {
  padding: 7px 8px;
  border-right: 1px solid var(--ns-line);
  border-bottom: 1px solid var(--ns-line);
  text-align: left;
  vertical-align: top;
}
.relmatrix thead th {
  position: sticky;
  top: 0;
  z-index: 2;
  background: var(--ns-card);
  color: var(--ns-ink-2);
  font-weight: 600;
  white-space: nowrap;
}
.relmatrix tbody th {
  position: sticky;
  left: 0;
  z-index: 1;
  min-width: 108px;
  background: var(--ns-card);
  color: var(--ns-ink-2);
  font-weight: 600;
  white-space: nowrap;
}
.relmatrix .corner {
  left: 0;
  z-index: 3;
  min-width: 54px;
  color: var(--ns-ink-4);
}
.relmatrix .rn {
  display: inline-block;
  min-width: 16px;
  margin-right: 5px;
  font-family: var(--ns-mono);
  font-size: 9.5px;
  font-weight: 500;
  color: var(--ns-ink-4);
}
.relmatrix td {
  min-width: 124px;
  max-width: 190px;
  background: var(--ns-card);
  color: var(--ns-ink-2);
  line-height: 1.55;
}
.relmatrix td.is-diag {
  background: var(--ns-card-2);
  color: var(--ns-ink-4);
  text-align: center;
}
.relmatrix td.has-rel {
  background: color-mix(in srgb, var(--ns-pink) 7%, var(--ns-card));
}
.rmrel {
  display: block;
  word-break: break-word;
}
.rmrel + .rmrel {
  margin-top: 3px;
  padding-top: 3px;
  border-top: 1px dashed var(--ns-line);
}
.rmrel i {
  display: inline-block;
  margin-right: 3px;
  font-style: normal;
  font-size: 10px;
  color: var(--ns-pink);
}
.rmempty {
  color: var(--ns-ink-4);
}
.matrixhint {
  margin: 0;
  padding: 8px 12px;
  border-top: 1px solid var(--ns-line);
  background: var(--ns-card-2);
  color: var(--ns-ink-4);
  font-size: 10.5px;
  line-height: 1.7;
}
.rulegroup {
  display: grid;
  gap: 8px;
}
.rulegroup__head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: var(--ns-ink-3);
}
.rulegroup__head p {
  margin: 0;
  flex: 1;
  line-height: 1.5;
}
.transfer {
  margin-top: 10px;
  padding-top: 9px;
  border-top: 1px dashed var(--ns-line);
}
.transfer ol {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.transfer li {
  display: flex;
  gap: 8px;
  align-items: baseline;
  font-size: 11.5px;
  color: var(--ns-ink-2);
}
.transfer b {
  flex: none;
  min-width: 52px;
  font-size: 10.5px;
  color: var(--ns-ink-3);
}
.transfer em {
  flex: 1;
  font-style: normal;
  color: var(--ns-ink-3);
}
.kv--wide {
  grid-column: 1 / -1;
}
.gaplist {
  list-style: none;
  margin: 0;
  padding: 6px 8px;
  display: grid;
  gap: 2px;
}
.gaplist li {
  padding: 9px 11px;
  border-radius: var(--ns-r-sm);
}
.gaplist li:nth-child(odd) {
  background: var(--ns-card-2);
}
.gaplist b {
  font-family: var(--ns-serif);
  font-size: 13px;
}
.gaplist__row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--ns-ink-2);
}
.gaplist__row i {
  font-style: normal;
  color: var(--ns-ink-3);
  margin-right: 4px;
}
.empty {
  padding: 18px 20px;
}
.empty b {
  font-family: var(--ns-serif);
  font-size: 14px;
}
.empty p {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ns-ink-3);
}
.rule__head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 13px 18px;
  cursor: pointer;
}
.rule__head b {
  flex: 1;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  line-height: 1.5;
  font-weight: 600;
}
.rule__state {
  font-size: 11px;
  color: var(--ns-ink-3);
  white-space: nowrap;
}
.rule__caret {
  color: var(--ns-ink-4);
  font-size: 12px;
}
.rule__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  border-top: 1px dashed var(--ns-line);
}
.rule__grid > div {
  padding: 12px 18px;
  border-bottom: 1px dashed var(--ns-line);
}
.rule__grid > div:nth-child(2n) {
  border-left: 1px dashed var(--ns-line);
}
.rule__grid p {
  margin: 3px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.rule__ban {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.rule__more {
  display: flex;
  gap: 14px;
  align-items: flex-end;
  justify-content: space-between;
  padding: 12px 18px;
  background: var(--ns-card-2);
}
.rule__editor p {
  margin: 3px 0 0;
  font-size: 13px;
  line-height: 1.8;
  color: var(--ns-ink-2);
  max-width: 70ch;
}
.factions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.faction {
  display: grid;
  gap: 12px;
}
.faction > div {
  padding: 9px 11px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.faction__hidden {
  background: var(--ns-warn-soft) !important;
}
.faction p {
  margin: 3px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.cardgrid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.kv {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.kv > div {
  padding: 9px 11px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.kv p {
  margin: 3px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
@media (max-width: 900px) {
  .cardgrid,
  .kv {
    grid-template-columns: 1fr;
  }
}
.rule-enter-active,
.rule-leave-active {
  transition: opacity 0.15s ease;
}
.rule-enter-from,
.rule-leave-to {
  opacity: 0;
}
@media (max-width: 900px) {
  .factions,
  .rule__grid {
    grid-template-columns: 1fr;
  }
  .rule__grid > div:nth-child(2n) {
    border-left: 0;
  }
}
@media (max-width: 620px) {
  .page {
    padding: 20px 16px 64px;
  }
}
</style>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Card, Tag, EmptyState } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import RelationsPanel from '@/components/RelationsPanel.vue'
import { useStudio } from '@/stores/studio'
import type { BibleCharacter } from '@/mocks'

const studio = useStudio()
const route = useRoute()
const router = useRouter()
type CharacterView = 'cards' | 'relations'
const view = ref<CharacterView>(route.query.view === 'relations' ? 'relations' : 'cards')

/** 人物关系原来挂在设定页；现在并进人物页，旧链接 ?view=relations 也能直接进来。 */
function setView(next: CharacterView) {
  view.value = next
  void router.replace({ name: 'characters', query: next === 'relations' ? { view: 'relations' } : {} })
}

watch(
  () => route.query.view,
  (v) => { view.value = v === 'relations' ? 'relations' : 'cards' },
)
const q = ref('')
const status = ref<'all' | 'active' | 'missing' | 'dead' | 'exited'>('all')
const tier = ref<'all' | '核心' | '主要' | '次要' | '龙套'>('all')
const selected = ref<string | null>(null)

// 命令面板搜到某个人时带 ?name= 进来，直接选中
onMounted(() => {
  const name = String(route.query.name ?? '')
  if (name) selected.value = name
})

const list = computed(() =>
  studio.data.characters.filter((c) => {
    if (status.value !== 'all' && c.status !== status.value) return false
    if (tier.value !== 'all' && importanceOf(c) !== tier.value) return false
    if (!q.value.trim()) return true
    return [c.name, c.aliases.join(' '), c.role, c.identity, c.personality, c.location, c.want, c.fear]
      .join(' ')
      .includes(q.value.trim())
  }),
)
const current = computed<BibleCharacter | null>(() => list.value.find((c) => c.name === selected.value) ?? list.value[0] ?? null)

const statusLabel: Record<BibleCharacter['status'], string> = {
  active: '在场',
  missing: '失踪',
  dead: '死亡',
  exited: '已退场',
}
const statusTone: Record<BibleCharacter['status'], 'ok' | 'warn' | 'bad' | 'neutral'> = {
  active: 'ok',
  missing: 'warn',
  dead: 'bad',
  exited: 'neutral',
}

function importanceOf(c: BibleCharacter): string {
  if (c.importance) return c.importance
  if (/主角|女主/.test(c.tier)) return '核心'
  if (/反派|常驻/.test(c.tier)) return '主要'
  if (/单卷|配角/.test(c.tier)) return '次要'
  return ''
}

const writtenCount = computed(() => studio.sortedChapters.filter((c) => c.chars > 0).length)
/** 位置/状态回写落后于正文时提示；不是错误，只是提醒作者核对。 */
const lag = computed(() => {
  const c = current.value
  if (!c || !c.locationAt) return 0
  return Math.max(0, writtenCount.value - c.locationAt)
})

const basics = computed(() => {
  const c = current.value
  if (!c) return []
  return [
    { k: '身份', v: c.identity || c.role },
    { k: '重要程度', v: [importanceOf(c), c.tier].filter(Boolean).join(' · ') },
    { k: '性别', v: c.gender },
    { k: '年龄', v: c.age },
    { k: '种族', v: c.race },
    { k: '首次登场', v: c.firstChapter ? `第 ${c.firstChapter} 章` : '' },
    { k: '退场', v: c.exitChapter ? `第 ${c.exitChapter} 章` : '' },
    { k: '出场状态', v: statusLabel[c.status] },
  ].filter((x) => x.v)
})
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="写正文前先翻这一页"
      title="人物"
      desc="人物卡不是简介，是写正文时要对照的事实：他此刻在哪、是什么状态、知道什么、和谁什么关系。位置和持有物写完一章会自动回写。"
    />

    <div class="segmented viewtabs" role="tablist" aria-label="人物的两种看法">
      <button
        type="button"
        role="tab"
        :aria-selected="view === 'cards'"
        :class="{ on: view === 'cards' }"
        @click="setView('cards')"
      >人物卡 {{ studio.data.characters.length }}</button>
      <button
        type="button"
        role="tab"
        :aria-selected="view === 'relations'"
        :class="{ on: view === 'relations' }"
        @click="setView('relations')"
      >人物关系 {{ studio.relations.length }}</button>
    </div>

    <template v-if="view === 'cards'">
    <div class="filters">
      <input v-model="q" class="search" placeholder="搜名字、别名、身份、性格、所在地…" aria-label="搜索人物" />
      <div class="segmented">
        <button
          v-for="s in [
            { k: 'all', t: `全部 ${studio.data.characters.length}` },
            { k: 'active', t: '在场' },
            { k: 'missing', t: '失踪' },
            { k: 'dead', t: '死亡' },
            { k: 'exited', t: '已退场' },
          ]"
          :key="s.k"
          type="button"
          :class="{ on: status === s.k }"
          @click="status = s.k as typeof status"
        >
          {{ s.t }}
        </button>
      </div>
      <div class="segmented">
        <button
          v-for="t in ['all', '核心', '主要', '次要', '龙套'] as const"
          :key="t"
          type="button"
          :class="{ on: tier === t }"
          @click="tier = t"
        >
          {{ t === 'all' ? '全部重要度' : t }}
        </button>
      </div>
      <span class="filters__meta">收录 {{ studio.data.characters.length }} 人 · 正文已出场 {{ studio.data.characters.filter((c) => c.appears.length).length }} 人</span>
    </div>

    <div v-if="current" class="grid">
      <Card flush class="roster">
        <button
          v-for="c in list"
          :key="c.name"
          type="button"
          class="person"
          :class="{ on: current.name === c.name }"
          @click="selected = c.name"
        >
          <span class="person__avatar" :style="{ background: c.color }">{{ c.name.slice(0, 1) }}</span>
          <span class="person__text">
            <b>{{ c.name }}</b>
            <small>{{ [c.tier, c.location].filter(Boolean).join(' · ') || c.role }}</small>
          </span>
          <span class="person__side">
            <Tag size="sm" :tone="statusTone[c.status]">{{ statusLabel[c.status] }}</Tag>
            <small class="ns-num">出场 {{ c.appears.length }}</small>
          </span>
        </button>
      </Card>

      <div class="ns-stack">
        <Card flush>
          <div class="profile">
            <div class="profile__avatar" :style="{ background: current.color }">{{ current.name.slice(0, 1) }}</div>
            <div class="profile__head">
              <div class="profile__name">
                <h2>{{ current.name }}</h2>
                <Tag size="sm" :tone="statusTone[current.status]">{{ statusLabel[current.status] }}</Tag>
                <Tag v-if="importanceOf(current)" size="sm" tone="ink">{{ importanceOf(current) }}</Tag>
                <Tag size="sm">出场 {{ current.appears.length }} 章</Tag>
              </div>
              <p>
                {{ [current.tier, current.identity, current.role].filter(Boolean).join(' · ') || '还没有身份' }}
                <template v-if="current.aliases.length"> · 又叫 {{ current.aliases.join('、') }}</template>
              </p>
            </div>
            <div class="profile__acts">
              <Tag size="sm" tone="neutral">只读 · 人物卡来自设定</Tag>
            </div>
          </div>

          <dl class="basics">
            <div v-for="b in basics" :key="b.k">
              <dt>{{ b.k }}</dt>
              <dd>{{ b.v }}</dd>
            </div>
          </dl>

          <div class="here" :class="{ 'here--stale': lag > 0 }">
            <div>
              <span class="ns-eyebrow">此刻所在地</span>
              <p>
                <b>{{ current.location || '未记录' }}</b>
                <template v-if="current.locationAt">（截至第 {{ current.locationAt }} 章）</template>
              </p>
              <p v-if="lag" class="here__warn">
                正文已写到第 {{ writtenCount }} 章，位置还停在第 {{ current.locationAt }} 章。
                允许他在别处，但正文要交代怎么到的。
              </p>
              <p v-else-if="!current.location" class="here__warn">没有位置就写不出「他此刻在哪」，容易人物漂移。</p>
            </div>
            <div class="here__goal">
              <span class="ns-eyebrow">当前目标</span>
              <p>{{ current.currentGoal || '—' }}</p>
            </div>
          </div>

          <div class="xlinks">
            <span class="xlinks__label">这份人物的关系看页顶「人物关系」；信息差和出场时间线在各自的主页：</span>
            <RouterLink :to="{ name: 'characters', query: { view: 'relations' } }">人物关系 →</RouterLink>
            <RouterLink :to="{ name: 'setup', query: { tab: 'gaps' } }">信息差 →</RouterLink>
            <RouterLink :to="{ name: 'memory', query: { tab: 'timeline' } }">出场时间线 →</RouterLink>
          </div>
        </Card>

        <div class="duo">
          <Card title="性格与动机" desc="写对话和选择时对照：他为什么这样做。">
            <div class="quad">
              <div class="quad__cell">
                <span class="ns-eyebrow">性格</span>
                <p>{{ current.personality || '—' }}</p>
              </div>
              <div class="quad__cell">
                <span class="ns-eyebrow">想要</span>
                <p>{{ current.want || '—' }}</p>
              </div>
              <div class="quad__cell">
                <span class="ns-eyebrow">害怕</span>
                <p>{{ current.fear || '—' }}</p>
              </div>
              <div class="quad__cell">
                <span class="ns-eyebrow">弱点</span>
                <p>{{ current.flaw || '—' }}</p>
              </div>
              <div class="quad__cell">
                <span class="ns-eyebrow">底线</span>
                <p>{{ current.bottomLine || '—' }}</p>
              </div>
              <div class="quad__cell quad__cell--secret">
                <span class="ns-eyebrow">瞒着</span>
                <p>{{ current.secret || '—' }}</p>
              </div>
            </div>
            <div class="voice">
              <span class="ns-eyebrow">怎么说话</span>
              <p class="ns-serif">{{ current.voice || '—' }}</p>
            </div>
            <div v-if="current.appearance" class="voice">
              <span class="ns-eyebrow">外形</span>
              <p>{{ current.appearance }}</p>
            </div>
            <div v-if="current.ability" class="voice">
              <span class="ns-eyebrow">本事</span>
              <p>
                {{ current.ability }}
                <template v-if="current.abilityLimit">（限制：{{ current.abilityLimit }}）</template>
                <template v-if="current.abilityCost">（代价：{{ current.abilityCost }}）</template>
              </p>
            </div>
          </Card>

          <Card title="人物轨迹" desc="每章写完后，正文里交代过的移动会记在这里。没有记录不代表没动，只是还没回写。">
            <ol v-if="current.locationHistory.length" class="moves">
              <li v-for="(m, i) in current.locationHistory" :key="`${m.chapter}-${i}`">
                <b class="ns-num">{{ m.chapter ? `第${m.chapter}章` : '—' }}</b>
                <span>{{ m.place }}</span>
                <em v-if="m.note">{{ m.note }}</em>
              </li>
            </ol>
            <p v-else class="ns-muted tiny">还没有移动记录。写正文时交代「从 A 到 B」，下一章会出现在这里。</p>
            <div v-if="current.changeLog" class="change">
              <span class="ns-eyebrow">人物变化</span>
              <p>{{ current.changeLog }}</p>
            </div>
          </Card>
        </div>
      </div>
    </div>
    <EmptyState v-else icon="人" title="没搜到这个人" desc="换个关键词，或者清掉状态 / 重要度筛选。" />
    </template>

    <RelationsPanel v-else />
  </div>
</template>

<style scoped>
.page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.filters {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.search {
  flex: 0 1 280px;
  height: 32px;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  padding: 0 12px;
  font: inherit;
  font-size: 12.5px;
  color: var(--ns-ink);
  outline: none;
}
.search:focus {
  border-color: var(--ns-pink);
  box-shadow: var(--ns-focus);
}
.viewtabs {
  margin-bottom: 14px;
}
.segmented {
  display: inline-flex;
  padding: 2px;
  gap: 1px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.segmented button {
  border: 0;
  background: transparent;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 11.5px;
  padding: 4px 11px;
  border-radius: 4px;
  cursor: pointer;
}
.segmented button.on {
  background: var(--ns-card);
  color: var(--ns-ink);
  font-weight: 600;
  box-shadow: var(--ns-shadow-1);
}
.filters__meta {
  margin-left: auto;
  font-size: 11px;
  color: var(--ns-ink-3);
}
.grid {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.roster {
  padding: 6px;
}
.person {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border: 0;
  background: transparent;
  border-radius: var(--ns-r-sm);
  font: inherit;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.person:hover {
  background: var(--ns-card-2);
}
.person.on {
  background: var(--ns-pink-soft);
}
.person__avatar {
  width: 30px;
  height: 30px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--ns-r-sm);
  color: #fff;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  font-weight: 700;
  opacity: 0.92;
}
.person__text {
  flex: 1;
  min-width: 0;
  display: grid;
  line-height: 1.35;
}
.person__text b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-13);
}
.person__text small {
  color: var(--ns-ink-3);
  font-size: 10.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.person__side {
  display: grid;
  justify-items: end;
  gap: 2px;
}
.person__side small {
  font-size: 10px;
  color: var(--ns-ink-3);
}
.profile {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px 16px;
  flex-wrap: wrap;
}
.profile__avatar {
  width: 56px;
  height: 56px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--ns-r-lg);
  color: #fff;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-22);
  font-weight: 700;
}
.profile__head {
  flex: 1;
  min-width: 0;
}
.profile__name {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.profile__name h2 {
  margin: 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-22);
  font-weight: 700;
}
.profile__head p {
  margin: 4px 0 0;
  color: var(--ns-ink-3);
  font-size: 12.5px;
}
.profile__acts {
  display: flex;
  gap: 6px;
}
.basics {
  margin: 0;
  padding: 0 20px 14px;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  background: var(--ns-line);
  border-top: 1px solid var(--ns-line);
}
.basics > div {
  background: var(--ns-card);
  padding: 10px 12px;
}
.basics dt {
  font-size: 10.5px;
  color: var(--ns-ink-3);
}
.basics dd {
  margin: 3px 0 0;
  font-size: 12.5px;
  color: var(--ns-ink);
}
.here {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
  gap: 12px;
  padding: 14px 20px 16px;
  border-top: 1px dashed var(--ns-line);
}
.here p {
  margin: 3px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.here__warn {
  color: var(--ns-warn) !important;
  font-size: 11.5px !important;
}
.duo {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.quad {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--ns-line);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  overflow: hidden;
}
.quad__cell {
  padding: 10px 12px;
  background: var(--ns-card);
}
.quad__cell--secret {
  background: var(--ns-gold-soft);
}
.quad__cell p {
  margin: 3px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.voice,
.change {
  margin-top: 12px;
  padding: 9px 11px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.voice p,
.change p {
  margin: 3px 0 0;
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.voice p.ns-serif {
  font-size: var(--ns-fs-14);
}
.moves {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.moves li {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 7px 9px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  font-size: 12px;
}
.moves b {
  font-size: 10.5px;
  color: var(--ns-ink-3);
  flex: none;
  min-width: 52px;
}
.moves span {
  font-family: var(--ns-serif);
  font-size: 13px;
}
.moves em {
  flex: 1;
  font-style: normal;
  color: var(--ns-ink-3);
  font-size: 11.5px;
}
.ns-muted {
  color: var(--ns-ink-3);
}
.tiny {
  font-size: 11.5px;
  line-height: 1.7;
}
.xlinks {
  display: flex;
  align-items: baseline;
  gap: 6px 14px;
  flex-wrap: wrap;
  margin: 10px 20px 16px;
  padding: 9px 11px;
  border-top: 1px dashed var(--ns-line);
  font-size: 11px;
  color: var(--ns-ink-4);
}
.xlinks__label {
  flex: 1 1 260px;
  min-width: 0;
  line-height: 1.6;
}
.xlinks a {
  color: var(--ns-pink);
  text-decoration: none;
  white-space: nowrap;
}
.xlinks a:hover {
  text-decoration: underline;
}
@media (max-width: 1040px) {
  .duo {
    grid-template-columns: 1fr;
  }
  .basics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 960px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .here {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 620px) {
  .page {
    padding: 20px 16px 64px;
  }
}
</style>

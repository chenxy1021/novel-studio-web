<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Card, Tag } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import GenStream from '@/components/GenStream.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import { useStudio } from '@/stores/studio'
import { rangeLabel } from '@/lib/format'

const studio = useStudio()
const router = useRouter()

const hasSynopsis = computed(() => Boolean(studio.book.synopsis.trim() || studio.book.logline.trim()))
const hasOutline = computed(() => Boolean(studio.book.outlineText?.trim()))
const hasWorld = computed(() => Boolean(studio.book.worldText?.trim()))
const loreCount = computed(() => {
  const p = studio.data.powerSystem
  return (
    (p.name || p.levels.length ? 1 : 0) +
    (Object.values(studio.data.society).some(Boolean) ? 1 : 0) +
    studio.data.history.length +
    studio.data.glossary.length
  )
})
const settingsCount = computed(
  () =>
    studio.characters.length +
    studio.data.factions.length +
    studio.data.rules.length +
    studio.data.locations.length +
    studio.data.items.length +
    studio.data.world.length +
    loreCount.value,
)
const openFs = computed(() => studio.foreshadows.filter((f) => f.status === 'open').length)
const written = computed(() => studio.chapters.length)

/** 02 步的设定盘点：和别的步骤一样用「条目 + 数值 + 样例」的排法，而不是一撮标签。 */
const settingGroups = computed(() => [
  {
    key: 'characters',
    label: '人物',
    unit: '人',
    count: studio.characters.length,
    sample: studio.characters.slice(0, 4).map((c) => c.name).join('、'),
    link: { name: 'characters' },
  },
  {
    key: 'factions',
    label: '势力',
    unit: '个',
    count: studio.data.factions.length,
    sample: studio.data.factions.slice(0, 3).map((f) => f.name).join('、'),
    link: { name: 'setup', query: { tab: 'factions' } },
  },
  {
    key: 'rules',
    label: '规则',
    unit: '条',
    count: studio.data.rules.length,
    sample: studio.data.rules.slice(0, 3).map((r) => `${r.name}（${r.enforce}）`).join('、'),
    link: { name: 'setup', query: { tab: 'rules' } },
  },
  {
    key: 'locations',
    label: '地点',
    unit: '处',
    count: studio.data.locations.length,
    sample: studio.data.locations.slice(0, 3).map((l) => l.name).join('、'),
    link: { name: 'setup', query: { tab: 'locations' } },
  },
  {
    key: 'items',
    label: '物品',
    unit: '件',
    count: studio.data.items.length,
    sample: studio.data.items.slice(0, 3).map((i) => i.name).join('、'),
    link: { name: 'setup', query: { tab: 'items' } },
  },
  {
    key: 'world',
    label: '世界纵深',
    unit: '项',
    count: loreCount.value,
    sample: [
      studio.data.powerSystem.name,
      ...studio.data.powerSystem.levels.slice(0, 2).map((l) => l.name),
      ...studio.data.history.slice(0, 1).map((h) => h.event),
      ...studio.data.glossary.slice(0, 1).map((g) => g.term),
    ].filter(Boolean).join('、'),
    link: { name: 'setup', query: { tab: 'world' } },
  },
])
const relationCount = computed(() => studio.relations.length)
const infoGapCount = computed(() => studio.infoGaps.length)

const nextStart = computed(() => (studio.chapters.length ? studio.nextNumber : 1))
const writeFrom = computed(() => nextStart.value)
const batchSize = computed(() => Math.max(3, studio.book.segmentSize || 10))
/** 与今日 / 细纲 / 写作面板对齐：已排段落纲时写到这一段末尾。 */
const writeTo = computed(() => {
  const seg = studio.currentSegment
  if (seg && seg.to >= writeFrom.value) return seg.to
  return Math.min(studio.book.targetChapters || writeFrom.value + batchSize.value - 1, writeFrom.value + batchSize.value - 1)
})
const pendingCount = computed(() =>
  studio.book.targetChapters ? Math.max(0, studio.book.targetChapters - written.value) : null,
)

const steps = computed(() => [
  {
    n: '01',
    key: 'blueprint',
    title: '大纲 + 世界观',
    desc: '只吃故事梗概和体量：先把全书层、卷层和这个世界的运行方式一次定下来。',
    done: hasOutline.value && hasWorld.value,
    state: hasOutline.value ? (hasWorld.value ? '已就位' : '缺世界观') : '未生成',
  },
  {
    n: '02',
    key: 'settings',
    title: '人物 · 规则 · 物品 · 地点',
    desc: '从大纲和世界观里拆出能查询、能对照的设定，只补不覆盖。',
    done: settingsCount.value > 0,
    state: settingsCount.value ? `${settingsCount.value} 条` : '未生成',
  },
  {
    n: '03',
    key: 'foreshadow',
    title: '伏笔 · 草蛇灰线',
    desc: '按卷分配核心 / 卷级 / 情节伏笔：先埋、中途再露一次、才揭晓。',
    done: openFs.value > 0,
    state: openFs.value ? `${openFs.value} 条未收` : '未设计',
  },
  {
    n: '04',
    key: 'write',
    title: '细纲 + 正文',
    desc: '每章先出可照写的节拍，再按节拍写足正文；一章一章推进，写完待你确认。',
    done: written.value > 0,
    state: written.value ? `已写 ${written.value} 章` : '还没开写',
  },
])

const outlinePreview = computed(() => (studio.book.outlineText || '').slice(0, 2200))
const worldPreview = computed(() => (studio.book.worldText || '').slice(0, 1800))

const volumes = computed(() => studio.data.outline)

function openWrite() {
  studio.openWritePanel({ source: 'workflow', from: writeFrom.value, to: writeTo.value })
}

/** store 已经 toast 过错误；这里吞掉 rejection，避免控制台里多一条未处理异常。 */
function generateBlueprint() {
  void studio.generateBlueprint(Boolean(studio.book.nuewen)).catch(() => {})
}
function generateSettings() {
  void studio.generateSettings().catch(() => {})
}
function generateForeshadows() {
  void studio.generateForeshadows().catch(() => {})
}

const liveBlueprint = computed(
  () => studio.liveGen.active && studio.liveGen.kind === 'blueprint',
)
const liveSettings = computed(
  () => studio.liveGen.active && (studio.liveGen.kind === 'settings' || studio.liveGen.kind === 'supplement'),
)
const liveForeshadow = computed(
  () => studio.liveGen.active && studio.liveGen.kind === 'foreshadow',
)
const liveWrite = computed(
  () => studio.liveGen.active && (studio.liveGen.kind === 'outline' || studio.liveGen.kind === 'prose'),
)
</script>

<template>
  <div class="page flow">
    <PageHeader
      eyebrow="开书流程"
      title="先立骨架，再落设定，最后开写。"
      :desc="`《${studio.book.title}》· ${studio.book.genre || '未定题材'} · ${studio.book.platform} · 目标 ${studio.book.targetChapters} 章`"
    >
      <Tag v-if="studio.book.nuewen" size="sm" tone="pink">虐文模式</Tag>
      <Tag size="sm" :tone="hasOutline ? 'ok' : 'neutral'">{{ hasOutline ? '骨架已立' : '筹备中' }}</Tag>
      <Button variant="ghost" @click="router.push({ name: 'overview' })">回今日</Button>
    </PageHeader>

    <Card v-if="!hasSynopsis" title="先有故事梗概" desc="大纲和世界观是从选题的梗概长出来的，没有梗概就无从下手。">
      <p class="ns-muted">这本书还没有简介 / 一句话。回到书架新建一本，或在选题里选一个带梗概的候选。</p>
    </Card>

    <ol class="steps">
      <li v-for="s in steps" :key="s.key" class="step" :class="{ 'step--done': s.done }">
        <div class="step__no">{{ s.n }}</div>
        <div class="step__body">
          <header class="step__head">
            <h2>{{ s.title }}</h2>
            <Tag size="sm" :tone="s.done ? 'ok' : 'neutral'">{{ s.state }}</Tag>
          </header>
          <p class="step__desc">{{ s.desc }}</p>

          <!-- 01 大纲 + 世界观 -->
          <div v-if="s.key === 'blueprint'" class="step__act">
            <div class="actrow">
              <Button
                variant="pink"
                icon="✎"
                :disabled="studio.blueprintBusy || !hasSynopsis"
                @click="generateBlueprint"
              >
                {{ studio.blueprintBusy ? '正在生成大纲+世界观…' : hasOutline ? '换一版大纲+世界观' : '生成大纲 + 世界观' }}
              </Button>
              <span v-if="volumes.length" class="actrow__hint">
                {{ volumes.length }} 卷 · {{ rangeLabel(volumes[0].range[0], volumes[volumes.length - 1].range[1]) }}
              </span>
              <Button v-if="hasOutline" size="sm" variant="ghost" @click="router.push({ name: 'outline' })">看完整大纲 →</Button>
              <Button v-if="hasWorld" size="sm" variant="ghost" @click="router.push({ name: 'outline', query: { tab: 'world' } })">看世界观 →</Button>
            </div>
            <GenStream
              v-if="liveBlueprint"
              :active="studio.liveGen.active"
              :text="studio.liveGen.text"
              :title="studio.liveGen.title"
              :stage="studio.liveGen.stage"
              :kind="studio.liveGen.kind"
              :started-at="studio.liveGen.startedAt"
              label="大纲 + 世界观"
            />
            <div v-if="hasOutline || hasWorld" class="preview">
              <div class="preview__col">
                <span class="ns-eyebrow">大纲 · 前 2200 字</span>
                <MarkdownView
                  class="preview__text"
                  :source="outlinePreview"
                  empty="（还没有大纲）"
                  max-height="320px"
                />
              </div>
              <div class="preview__col">
                <span class="ns-eyebrow">世界观 · 前 1800 字</span>
                <MarkdownView
                  class="preview__text"
                  :source="worldPreview"
                  empty="（模型没有输出世界观部分，建议换一版）"
                  max-height="320px"
                />
              </div>
            </div>
            <p class="step__note">
              素材只来自故事梗概、章节数和平台{{ studio.book.nuewen ? '，并自动带入「最 X → 最非 X」的虐文公式' : '' }}；人物和规则留给下一步，不会提前写进骨架。
            </p>
          </div>

          <!-- 02 设定 -->
          <div v-else-if="s.key === 'settings'" class="step__act">
            <div class="actrow">
              <Button
                variant="pink"
                icon="⚙"
                :disabled="studio.settingsBusy || !hasOutline"
                @click="generateSettings"
              >
                {{ studio.settingsBusy ? '正在拆人物和设定…' : settingsCount ? '重新拆设定（不覆盖）' : '生成设定' }}
              </Button>
              <span class="actrow__hint">
                人物 {{ studio.characters.length }} · 势力 {{ studio.data.factions.length }} · 规则 {{ studio.data.rules.length }} · 地点 {{ studio.data.locations.length }} · 物品 {{ studio.data.items.length }}
              </span>
              <Button v-if="settingsCount" size="sm" variant="ghost" @click="router.push({ name: 'setup' })">去设定页 →</Button>
            </div>
            <GenStream
              v-if="liveSettings"
              :active="studio.liveGen.active"
              :text="studio.liveGen.text"
              :title="studio.liveGen.title"
              :stage="studio.liveGen.stage"
              :kind="studio.liveGen.kind"
              :started-at="studio.liveGen.startedAt"
              label="设定生成实况"
            />
            <div v-if="settingsCount" class="setgrid">
              <RouterLink v-for="g in settingGroups" :key="g.key" class="setcard" :to="g.link">
                <span class="ns-eyebrow">{{ g.label }}</span>
                <b class="setcard__n">{{ g.count }}<small>{{ g.unit }}</small></b>
                <p class="setcard__sample">{{ g.sample || '还没有' }}</p>
              </RouterLink>
            </div>
            <p v-else class="step__note">还没有人物卡。设定生成会同时补齐关系矩阵与信息差，写正文时才有「谁知道什么」。</p>
            <p v-if="settingsCount" class="step__note">
              关系 {{ relationCount }} 条 · 信息差 {{ infoGapCount }} 条。点上面的条目进对应资料页；写正文时人物位置、物品持有、
              规则分类和知识盲区会一起进上下文。
            </p>
          </div>

          <!-- 03 伏笔 -->
          <div v-else-if="s.key === 'foreshadow'" class="step__act">
            <div class="actrow">
              <Button
                variant="pink"
                icon="◇"
                :disabled="studio.foreshadowBusy || !hasWorld"
                @click="generateForeshadows"
              >
                {{ studio.foreshadowBusy ? '正在铺伏笔网…' : studio.foreshadows.length ? '补充伏笔' : '设计伏笔 · 草蛇灰线' }}
              </Button>
              <span class="actrow__hint">
                {{ openFs }} 条未收{{ studio.foreshadows.length ? ` / 共 ${studio.foreshadows.length} 条` : '' }}
              </span>
              <Button v-if="studio.foreshadows.length" size="sm" variant="ghost" @click="router.push({ name: 'foreshadow' })">去伏笔页 →</Button>
            </div>
            <GenStream
              v-if="liveForeshadow"
              :active="studio.liveGen.active"
              :text="studio.liveGen.text"
              :title="studio.liveGen.title"
              :stage="studio.liveGen.stage"
              :kind="studio.liveGen.kind"
              :started-at="studio.liveGen.startedAt"
              label="伏笔设计实况"
            />
            <ul v-if="studio.foreshadows.length" class="fslist">
              <li v-for="f in studio.foreshadows.slice(0, 6)" :key="f.id">
                <b>{{ f.name }}</b>
                <span>第 {{ f.plantedChapter }} 章埋 · 第 {{ f.dueChapter ?? '—' }} 章收</span>
                <Tag size="sm" :tone="f.kind === 'main' ? 'pink' : f.kind === 'volume' ? 'gold' : 'neutral'">
                  {{ f.kind === 'main' ? '主线' : f.kind === 'volume' ? '卷内' : '细节' }}
                </Tag>
              </li>
            </ul>
            <p v-else class="step__note">
              伏笔必须来自世界观里已有的规则 / 人物 / 地点 / 势力 / 物品；设计完会直接写进伏笔账本，写正文时自动带进上下文。
            </p>
          </div>

          <!-- 04 写作 -->
          <div v-else class="step__act">
            <div class="actrow">
              <Button variant="pink" icon="✒" :disabled="!hasOutline || !studio.foreshadows.length" @click="openWrite">
                开写第 {{ writeFrom }}–{{ writeTo }} 章
              </Button>
              <span class="actrow__hint">
                已写 {{ written }} 章{{ pendingCount != null ? ` · 待写 ${pendingCount} 章` : '' }}
              </span>
              <Button v-if="!studio.foreshadows.length" size="sm" variant="ghost" @click="router.push({ name: 'foreshadow' })">
                先设计伏笔 →
              </Button>
              <Button v-else-if="written" size="sm" variant="ghost" @click="router.push({ name: 'progress' })">
                去进度页确认 →
              </Button>
            </div>
            <GenStream
              v-if="liveWrite"
              :active="studio.liveGen.active"
              :text="studio.liveGen.text"
              :title="studio.liveGen.title"
              :stage="studio.liveGen.stage"
              :kind="studio.liveGen.kind"
              :started-at="studio.liveGen.startedAt"
              label="细纲 + 正文实况"
            />
            <p v-if="!studio.foreshadows.length" class="step__note step__note--warn">
              还不能写正文：一条伏笔都没有，正文会一路丢线。先在「伏笔」里设计至少一条，再回来开写。
            </p>
            <p v-else class="step__note">
              点按钮打开「开写」面板：选本批章节、确认文风和写作技能，再逐章生成细纲和正文。
              默认从第 {{ nextStart }} 章开始，本批写到第 {{ writeTo }} 章（与今日页、细纲页一致）；已有正文的章默认跳过，运行进度在右下角的小条里看。
            </p>
          </div>
        </div>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.page {
  max-width: 1120px;
  margin: 0 auto;
  padding: 28px 32px 80px;
}
.steps {
  display: grid;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.step {
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  gap: 0;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  overflow: hidden;
}
.step--done {
  border-color: color-mix(in srgb, var(--ns-ok) 30%, var(--ns-line));
}
.step__no {
  padding: 18px 0 0;
  text-align: center;
  font-family: var(--ns-mono);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ns-ink-4);
  background: var(--ns-card-2);
  border-right: 1px solid var(--ns-line);
}
.step--done .step__no {
  color: var(--ns-pink);
}
.step__body {
  padding: 16px 20px 18px;
  min-width: 0;
}
.step__head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.step__head h2 {
  margin: 0;
  font-family: var(--ns-serif);
  font-size: 18px;
  font-weight: 700;
}
.step__desc {
  margin: 5px 0 12px;
  color: var(--ns-ink-3);
  font-size: 12.5px;
  line-height: 1.7;
}
.step__act {
  display: grid;
  gap: 12px;
}
.actrow {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.actrow__hint {
  font-size: 11.5px;
  color: var(--ns-ink-3);
}
.step__note {
  margin: 0;
  padding: 9px 11px;
  border-left: 2px solid var(--ns-pink-line);
  background: var(--ns-card-2);
  color: var(--ns-ink-3);
  font-size: 11.5px;
  line-height: 1.7;
}
.step__note--warn {
  border-left-color: var(--ns-bad);
  color: var(--ns-ink-2);
}
.preview {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.preview__col {
  min-width: 0;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  padding: 10px 12px;
}
.preview__text {
  margin-top: 6px;
  font-size: 12.5px;
  line-height: 1.8;
}
.setgrid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
}
.setcard {
  display: grid;
  gap: 2px;
  padding: 10px 12px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  color: inherit;
  text-decoration: none;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.setcard:hover {
  border-color: var(--ns-pink-line);
  background: var(--ns-card);
}
.setcard__n {
  font-family: var(--ns-serif);
  font-size: 22px;
  line-height: 1.15;
}
.setcard__n small {
  margin-left: 3px;
  font-family: var(--ns-sans);
  font-size: 10.5px;
  font-weight: 400;
  color: var(--ns-ink-3);
}
.setcard__sample {
  margin: 2px 0 0;
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--ns-ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fslist {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.fslist li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px dashed var(--ns-line);
  font-size: 12px;
}
.fslist li:last-child {
  border-bottom: 0;
}
.fslist b {
  font-family: var(--ns-serif);
  font-size: 13px;
}
.fslist span {
  flex: 1;
  color: var(--ns-ink-3);
  font-size: 11px;
}
.writer {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}
.writer :deep(.ns-field) {
  width: 118px;
}
.check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  font-size: 12px;
  color: var(--ns-ink-2);
  cursor: pointer;
}
.check input {
  accent-color: var(--ns-pink);
}
.run {
  display: grid;
  gap: 7px;
  padding: 11px 12px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.run__bar {
  height: 4px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-chart-track);
  overflow: hidden;
}
.run__bar i {
  display: block;
  height: 100%;
  background: var(--ns-pink);
  transition: width 0.25s ease;
}
.run__meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 11px;
  color: var(--ns-ink-3);
}
.run__err {
  color: var(--ns-warn);
}
.run__log {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 3px;
  max-height: 220px;
  overflow: auto;
}
.run__log li {
  display: flex;
  gap: 9px;
  align-items: baseline;
  padding: 3px 4px;
  font-size: 11.5px;
  color: var(--ns-ink-2);
}
.run__log b {
  font-family: var(--ns-mono);
  font-size: 10.5px;
  color: var(--ns-ink-3);
}
.run__log span {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.run__log em {
  font-style: normal;
  color: var(--ns-ink-3);
  font-size: 10.5px;
}
.run__row--ok span {
  color: var(--ns-ok);
}
.run__row--fail span {
  color: var(--ns-warn);
}
.run__row--skip span {
  color: var(--ns-ink-4);
}
@media (max-width: 820px) {
  .page {
    padding: 20px 16px 64px;
  }
  .step {
    grid-template-columns: 40px minmax(0, 1fr);
  }
  .preview {
    grid-template-columns: 1fr;
  }
  .setgrid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

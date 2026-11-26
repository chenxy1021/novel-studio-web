<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, Card, Tag, Table, EmptyState, Modal, type Column } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import GenStream from '@/components/GenStream.vue'
import { useStudio } from '@/stores/studio'
import { FORESHADOW_FILTERS, filterForeshadows, type ForeshadowFilter } from '@/lib/foreshadow'
import type { Foreshadow } from '@/mocks'

const studio = useStudio()
const view = ref<'net' | 'table'>('net')
const kindFilter = ref<'all' | Foreshadow['kind']>('all')
const statusFilter = ref<ForeshadowFilter>('open')
const showForm = ref(false)
const form = ref({ name: '', kind: 'detail' as Foreshadow['kind'], plantedChapter: '', dueChapter: '', revealWho: '', hint: '' })

/** 「现在」= 已写到的最新章（正文最大章号），不是下一章。 */
const current = computed(() => studio.maxNumber)
/** 层级筛完的那一份：四个状态格子和「5 章内到期」都在它上面数，点进去看到的就是这个数。 */
const byKind = computed(() =>
  studio.foreshadows.filter((f) => kindFilter.value === 'all' || f.kind === kindFilter.value),
)
const statusCounts = computed<Record<ForeshadowFilter, number>>(() => ({
  open: byKind.value.filter((f) => f.status === 'open').length,
  overdue: byKind.value.filter((f) => f.status === 'open' && f.overdue).length,
  paid: byKind.value.filter((f) => f.status === 'paid').length,
  abandoned: byKind.value.filter((f) => f.status === 'abandoned').length,
}))
/** 当前筛选 + 层级下的条目；未收/超期走网图或表格，已收/放弃走列表。 */
const filtered = computed(() => filterForeshadows(studio.foreshadows, statusFilter.value, kindFilter.value))
const openish = computed(() => statusFilter.value === 'open' || statusFilter.value === 'overdue')
const emptyCopy = computed(() => {
  if (statusFilter.value === 'overdue') return { title: '没有超期的伏笔', desc: '到期的都收掉了。想提前看，切回「未收」。' }
  if (statusFilter.value === 'paid') return { title: '还没有收回的伏笔', desc: '第一次收线时，这里会出现它在第几章被读回来。' }
  if (statusFilter.value === 'abandoned') return { title: '没有放弃的伏笔', desc: '放弃不删除：事件历史留在账本里，只是不再提醒。' }
  return { title: '这个筛选下没有未收伏笔', desc: '换一个层级看看，或者点右上「埋一条」。' }
})
const kindLabel: Record<Foreshadow['kind'], string> = { main: '主线', volume: '卷内', detail: '细节' }
const kindTone: Record<Foreshadow['kind'], 'pink' | 'info' | 'neutral'> = { main: 'pink', volume: 'info', detail: 'neutral' }

const pos = (n: number) => ((n - 1) / Math.max(1, studio.book.targetChapters - 1)) * 100
const left = (f: Foreshadow) => (f.dueChapter ? f.dueChapter - current.value : null)
const toneOf = (f: Foreshadow) => {
  const l = left(f)
  if (l === null) return 'neutral' as const
  if (l < 0) return 'bad' as const
  if (l <= 5) return 'warn' as const
  return 'neutral' as const
}
const urgent = computed(() =>
  byKind.value.filter((f) => f.status === 'open' && (left(f) ?? 99) <= 5).length,
)
const liveForeshadow = computed(
  () => studio.liveGen.active && studio.liveGen.kind === 'foreshadow',
)

type Row = Foreshadow & { kindText: string; remaining: number | null }
const rows = computed<Row[]>(() => filtered.value.map((f) => ({ ...f, kindText: kindLabel[f.kind], remaining: left(f) })))
const cols: Column<Row>[] = [
  { key: 'name', label: '伏笔', width: '26%' },
  { key: 'kindText', label: '层级', width: '72px' },
  { key: 'plantedChapter', label: '埋', numeric: true, width: '56px' },
  { key: 'dueChapter', label: '收', numeric: true, width: '56px' },
  { key: 'remaining', label: '距收', numeric: true, width: '64px' },
  { key: 'hint', label: '中途提示' },
]

/** store 已 toast 错误；吞掉 rejection，避免未处理异常。 */
function runForeshadow() {
  void studio.generateForeshadows().catch(() => {})
}

async function submit() {
  const { name, plantedChapter, dueChapter } = form.value
  if (!name.trim() || !plantedChapter || !dueChapter) return studio.toast('名字、埋设章、回收章都要填', 'warn')
  if (Number(dueChapter) <= Number(plantedChapter)) return studio.toast('回收章必须晚于埋设章', 'warn')
  try {
    await studio.addForeshadow({
      name: name.trim(),
      kind: form.value.kind,
      plantedChapter: Number(plantedChapter),
      dueChapter: Number(dueChapter),
      revealWho: form.value.revealWho,
      hint: form.value.hint,
    })
    showForm.value = false
    form.value = { name: '', kind: 'detail', plantedChapter: '', dueChapter: '', revealWho: '', hint: '' }
  } catch (e) {
    studio.toast(`埋设失败：${e instanceof Error ? e.message : String(e)}`, 'warn')
  }
}

async function payoff(f: Foreshadow) {
  try {
    await studio.payoffForeshadow(f.id, current.value)
  } catch (e) {
    studio.toast(`回收失败：${e instanceof Error ? e.message : String(e)}`, 'warn')
  }
}

/** 按批体检自动记收偶尔会判错：改回未收，体检继续追这条线。 */
async function reopen(f: Foreshadow) {
  try {
    await studio.reopenForeshadow(f.id)
  } catch (e) {
    studio.toast(`重新打开失败：${e instanceof Error ? e.message : String(e)}`, 'warn')
  }
}

/* ---------- 明确放弃一条线 ---------- */

const abandonTarget = ref<Foreshadow | null>(null)
const abandonNote = ref('')
const abandonBusy = ref(false)

function askAbandon(f: Foreshadow) {
  abandonTarget.value = f
  abandonNote.value = f.abandon || ''
}

/** 放弃不删账，只追加一条 abandon 事件；体检不再追这条线。 */
async function confirmAbandon() {
  const f = abandonTarget.value
  if (!f || abandonBusy.value) return
  abandonBusy.value = true
  try {
    await studio.abandonForeshadow(f.id, abandonNote.value.trim())
    abandonTarget.value = null
  } catch (e) {
    studio.toast(`放弃失败：${e instanceof Error ? e.message : String(e)}`, 'warn')
  } finally {
    abandonBusy.value = false
  }
}

function remind(f: Foreshadow) {
  const l = left(f)
  if (l === null) studio.toast(`「${f.name}」没定回收章，建议现在补一个`, 'warn')
  else if (l <= 5) studio.toast(`「${f.name}」还差 ${l} 章到期，记得在段落纲里点名`, 'warn')
  else studio.toast(`「${f.name}」还有 ${l} 章，不用急`, 'info')
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="埋了什么，什么时候收"
      title="伏笔"
      desc="账本是唯一真相：只追加，不手改。按批体检会对照正文核对到期伏笔，正文里已经写了就自动记收；没写的挂进跨章问题，补写或放弃。收错了点「重新打开」。"
    >
      <Button
        variant="pink"
        icon="◇"
        :disabled="studio.foreshadowBusy || !studio.book.worldText"
        @click="runForeshadow"
      >
        {{ studio.foreshadowBusy ? '正在铺伏笔网…' : studio.foreshadows.length ? '补充伏笔' : 'AI 设计伏笔' }}
      </Button>
      <div v-if="openish" class="toggle">
        <button type="button" :class="{ on: view === 'net' }" @click="view = 'net'">网</button>
        <button type="button" :class="{ on: view === 'table' }" @click="view = 'table'">表</button>
      </div>
      <Button variant="pink" icon="＋" @click="showForm = true">埋一条</Button>
    </PageHeader>

    <GenStream
      v-if="liveForeshadow"
      :active="studio.liveGen.active"
      :text="studio.liveGen.text"
      :title="studio.liveGen.title"
      :stage="studio.liveGen.stage"
      :kind="studio.liveGen.kind"
      :started-at="studio.liveGen.startedAt"
      label="伏笔设计实况"
      class="livegen"
    />

    <div class="summary">
      <button
        v-for="s in FORESHADOW_FILTERS"
        :key="s.id"
        type="button"
        class="summary__item"
        :class="{
          on: statusFilter === s.id,
          'summary__item--urgent': s.id === 'overdue' && statusCounts.overdue > 0,
        }"
        :aria-pressed="statusFilter === s.id"
        @click="statusFilter = s.id"
      >
        <b class="ns-num">{{ statusCounts[s.id] }}</b>
        <span>{{ s.label }}</span>
      </button>
      <span v-if="urgent" class="summary__soon">5 章内到期 {{ urgent }}</span>
      <div class="summary__spacer" />
      <div class="kinds">
        <button
          v-for="k in [{ k: 'all', t: '全部' }, { k: 'main', t: '主线' }, { k: 'volume', t: '卷内' }, { k: 'detail', t: '细节' }]"
          :key="k.k"
          type="button"
          :class="{ on: kindFilter === k.k }"
          @click="kindFilter = k.k as typeof kindFilter"
        >
          {{ k.t }}
        </button>
      </div>
    </div>

    <template v-if="openish && view === 'net' && filtered.length">
      <div class="axis">
        <span>第 1 章</span>
        <span class="axis__now">现在 · 第 {{ current }} 章</span>
        <span>第 {{ studio.book.targetChapters }} 章</span>
      </div>
      <Card flush class="net">
        <i class="net__nowline" :style="{ left: `calc(300px + (100% - 320px) * ${pos(current) / 100})` }" />
        <div v-for="f in filtered" :key="f.id" class="thread">
          <div class="thread__info">
            <div class="thread__name">
              <b>{{ f.name }}</b>
              <Tag size="sm" :tone="kindTone[f.kind]">{{ kindLabel[f.kind] }}</Tag>
              <Tag v-if="(left(f) ?? 99) < 0" size="sm" tone="bad" dot>超期 {{ -(left(f) ?? 0) }} 章</Tag>
              <Tag v-else-if="left(f) === 0" size="sm" tone="warn" dot>本章该收</Tag>
              <Tag v-else-if="left(f) !== null" size="sm" :tone="toneOf(f)">{{ left(f) }} 章后收</Tag>
            </div>
            <p v-if="f.hint" class="thread__hint">{{ f.hint }}</p>
            <div class="thread__acts">
              <Button size="sm" variant="ghost" @click="payoff(f)">本章收</Button>
              <Button size="sm" variant="ghost" @click="remind(f)">提醒</Button>
              <Button size="sm" variant="ghost" class="thread__drop" @click="askAbandon(f)">放弃</Button>
            </div>
          </div>
          <div class="thread__track">
            <i
              class="thread__line"
              :class="{ 'thread__line--late': (left(f) ?? 99) < 0 }"
              :style="{ left: `${pos(f.plantedChapter)}%`, width: `${pos(f.dueChapter ?? f.plantedChapter) - pos(f.plantedChapter)}%` }"
            />
            <span class="thread__dot thread__dot--plant" :style="{ left: `${pos(f.plantedChapter)}%` }" :title="`埋于第 ${f.plantedChapter} 章`" />
            <span v-if="f.dueChapter" class="thread__dot thread__dot--due" :style="{ left: `${pos(f.dueChapter)}%` }" :title="`计划第 ${f.dueChapter} 章收`" />
          </div>
        </div>
      </Card>
      <div class="legend">
        <span><i class="lg lg--plant" />埋</span>
        <span><i class="lg lg--due" />计划收</span>
        <span><i class="lg lg--late" />已超期</span>
      </div>
    </template>

    <Card v-else-if="openish && view === 'table' && filtered.length" flush>
      <Table :columns="cols" :rows="rows" dense striped row-key="id" />
    </Card>
    <EmptyState
      v-else-if="openish"
      icon="◇"
      :title="emptyCopy.title"
      :desc="emptyCopy.desc"
    />

    <Card
      v-else-if="statusFilter === 'paid'"
      eyebrow="已收"
      :title="`${filtered.length} 条伏笔已经收线`"
      desc="收线后正文里要能读到「读者之前见过它」。找不到出处，体检会报断层。"
      class="paidcard"
    >
      <div v-if="filtered.length" class="paid">
        <div v-for="f in filtered" :key="f.id" class="paid__item">
          <div>
            <b>{{ f.name }}</b>
            <span>埋 {{ f.plantedChapter }} · 收 {{ f.payoffChapter }}</span>
            <span v-if="f.note" class="paid__note">{{ f.note }}</span>
          </div>
          <div class="paid__acts">
            <Tag size="sm" tone="ok">已收</Tag>
            <Button size="sm" variant="ghost" @click="reopen(f)">重新打开</Button>
          </div>
        </div>
      </div>
      <EmptyState v-else compact icon="✓" :title="emptyCopy.title" :desc="emptyCopy.desc" />
    </Card>

    <Card
      v-else
      eyebrow="放弃"
      :title="`${filtered.length} 条不再交代`"
      desc="放弃不删除：事件历史留在账本里，只是不再提醒。"
    >
      <div v-if="filtered.length" class="paid">
        <div v-for="f in filtered" :key="f.id" class="paid__item">
          <div>
            <b>{{ f.name }}</b>
            <span>埋 {{ f.plantedChapter }} · 不打算交代</span>
          </div>
          <Tag size="sm" tone="neutral">已放弃</Tag>
        </div>
      </div>
      <EmptyState v-else compact icon="—" :title="emptyCopy.title" :desc="emptyCopy.desc" />
    </Card>

    <Modal
      :open="!!abandonTarget"
        :title="`放弃：${abandonTarget?.name ?? ''}`"
        desc="这条线不打算交代了。账本只追加一条放弃事件，正文不用改，体检也不再追。"
        width="480px"
        @close="abandonTarget = null"
      >
        <label class="field">
          <span>放弃理由 / 改成什么（选填）</span>
          <textarea
            v-model="abandonNote"
            rows="3"
            placeholder="例如：并进韩序的旧账一起交代；或者这版不写这条线了"
          />
        </label>
        <template #footer>
          <Button variant="ghost" :disabled="abandonBusy" @click="abandonTarget = null">取消</Button>
          <Button variant="primary" :disabled="abandonBusy" @click="confirmAbandon">
            {{ abandonBusy ? '处理中…' : '放弃这条线' }}
          </Button>
        </template>
    </Modal>

    <Transition name="slide">
      <aside v-if="showForm" class="drawer" role="dialog" aria-label="新伏笔">
        <header class="drawer__head">
          <div>
            <span class="ns-eyebrow">新伏笔</span>
            <h3>写清埋在哪、在哪收、谁来揭</h3>
          </div>
          <button type="button" class="drawer__x" aria-label="关闭" @click="showForm = false">✕</button>
        </header>
        <div class="drawer__body">
          <label class="field"><span>名称</span><input v-model="form.name" placeholder="一句能记住的话，例如「名单上少掉的名字」" /></label>
          <label class="field">
            <span>层级</span>
            <select v-model="form.kind">
              <option value="main">主线（贯穿全书）</option>
              <option value="volume">卷内（一卷内收）</option>
              <option value="detail">细节（章内）</option>
            </select>
          </label>
          <div class="fieldrow">
            <label class="field"><span>埋设章</span><input v-model="form.plantedChapter" type="number" min="1" /></label>
            <label class="field"><span>回收章</span><input v-model="form.dueChapter" type="number" min="2" /></label>
          </div>
          <label class="field"><span>谁来揭</span><input v-model="form.revealWho" placeholder="人物名，或者「没有人知道」" /></label>
          <label class="field"><span>中途提示</span><textarea v-model="form.hint" rows="3" placeholder="第几章出现什么细节，让读者先闻到味" /></label>
          <p class="drawer__note">回收章必须晚于埋设章。落账只追加一条事件，不会改已有记录。</p>
        </div>
        <footer class="drawer__foot">
          <Button variant="ghost" @click="showForm = false">取消</Button>
          <Button variant="primary" @click="submit">落账</Button>
        </footer>
      </aside>
    </Transition>
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
  font-size: 11.5px;
  padding: 4px 12px;
  border-radius: 4px;
  cursor: pointer;
}
.toggle button.on {
  background: var(--ns-card);
  color: var(--ns-ink);
  font-weight: 600;
  box-shadow: var(--ns-shadow-1);
}
.summary {
  display: flex;
  align-items: center;
  gap: 22px;
  flex-wrap: wrap;
  padding: 10px 16px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  margin-bottom: 14px;
}
.summary__item {
  display: flex;
  align-items: baseline;
  gap: 6px;
  border: 0;
  background: transparent;
  font: inherit;
  padding: 2px 8px;
  margin: 0 -4px;
  border-radius: var(--ns-r-sm);
  cursor: pointer;
  color: inherit;
}
.summary__item:hover {
  background: var(--ns-card-2);
}
.summary__item.on {
  background: var(--ns-card-2);
  box-shadow: inset 0 0 0 1px var(--ns-line-2);
}
.summary__item.on b {
  color: var(--ns-pink);
}
.summary__item b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-22);
}
.summary__item span {
  font-size: 11.5px;
  color: var(--ns-ink-3);
}
.summary__item--urgent b {
  color: var(--ns-warn);
}
.summary__item--urgent.on b {
  color: var(--ns-warn);
}
.summary__soon {
  font-size: 11.5px;
  color: var(--ns-ink-3);
}
.summary__spacer {
  flex: 1;
}
.kinds {
  display: flex;
  gap: 2px;
}
.kinds button {
  border: 0;
  background: transparent;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 11.5px;
  padding: 3px 9px;
  border-radius: var(--ns-r-xs);
  cursor: pointer;
}
.kinds button.on {
  background: var(--ns-ink);
  color: var(--ns-card);
  font-weight: 600;
}
.axis {
  display: flex;
  justify-content: space-between;
  padding: 0 18px 8px 316px;
  font-size: 10px;
  color: var(--ns-ink-3);
  font-variant-numeric: tabular-nums;
}
.axis__now {
  color: var(--ns-pink-2);
  font-weight: 600;
}
.net {
  position: relative;
}
.net__nowline {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: repeating-linear-gradient(to bottom, var(--ns-pink) 0 3px, transparent 3px 6px);
  pointer-events: none;
}
.thread {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  align-items: center;
  padding: 11px 18px 11px 16px;
  border-bottom: 1px dashed var(--ns-line);
}
.thread:last-child {
  border-bottom: 0;
}
.thread__name {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.thread__name b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-13);
}
.thread__hint {
  margin: 3px 0 0;
  font-size: 10.5px;
  color: var(--ns-ink-3);
  line-height: 1.55;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread__acts {
  display: flex;
  gap: 2px;
  margin: 3px 0 0 -4px;
  opacity: 0;
  transition: opacity 0.12s ease;
}
.thread:hover .thread__acts,
.thread:focus-within .thread__acts {
  opacity: 1;
}
.thread__drop {
  color: var(--ns-ink-3);
}
.thread__drop:hover {
  color: var(--ns-bad);
}
.thread__track {
  position: relative;
  height: 24px;
  margin: 0 6px;
}
.thread__track::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  top: 11px;
  border-top: 1px dashed var(--ns-line);
}
.thread__line {
  position: absolute;
  top: 10px;
  height: 3px;
  border-radius: 2px;
  background: linear-gradient(90deg, var(--ns-gold), var(--ns-pink-line));
}
.thread__line--late {
  background: repeating-linear-gradient(90deg, var(--ns-bad) 0 5px, transparent 5px 9px);
}
.thread__dot {
  position: absolute;
  top: 6px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  transform: translateX(-50%);
}
.thread__dot--plant {
  background: var(--ns-gold);
  border: 2px solid var(--ns-card);
}
.thread__dot--due {
  background: var(--ns-card);
  border: 2px solid var(--ns-pink);
}
.legend {
  display: flex;
  gap: 14px;
  padding: 8px 4px 0;
  font-size: 10.5px;
  color: var(--ns-ink-3);
}
.lg {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}
.lg--plant {
  background: var(--ns-gold);
}
.lg--due {
  border: 2px solid var(--ns-pink);
}
.lg--late {
  width: 12px;
  height: 3px;
  border-radius: 0;
  background: var(--ns-bad);
  vertical-align: 2px;
}
.paidcard {
  margin-top: 16px;
}
.paid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 2px;
}
.paid__item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.paid__item div {
  display: grid;
  line-height: 1.4;
}
.paid__item b {
  font-family: var(--ns-serif);
  font-size: 12.5px;
}
.paid__item span {
  font-size: 10.5px;
  color: var(--ns-ink-3);
}
/* 记收来源（按批体检核对出来的会写第几章哪一句）：一行灰字，太长就截断。 */
.paid__note {
  max-width: 560px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.paid__item .paid__acts {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.drawer {
  position: fixed;
  right: 0;
  top: 0;
  bottom: 0;
  width: 420px;
  max-width: 100vw;
  z-index: 40;
  display: flex;
  flex-direction: column;
  background: var(--ns-card);
  border-left: 1px solid var(--ns-line);
  box-shadow: var(--ns-shadow-3);
}
.drawer__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 18px 20px 12px;
  border-bottom: 1px solid var(--ns-line);
}
.drawer__head h3 {
  margin: 3px 0 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
}
.drawer__x {
  border: 0;
  background: transparent;
  color: var(--ns-ink-3);
  cursor: pointer;
  font-size: 14px;
}
.drawer__body {
  flex: 1;
  overflow: auto;
  padding: 16px 20px;
  display: grid;
  gap: 12px;
  align-content: start;
}
.field {
  display: grid;
  gap: 5px;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ns-ink-2);
}
.field input,
.field select,
.field textarea {
  width: 100%;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-weight: 400;
  font-size: 12.5px;
  padding: 7px 10px;
  outline: none;
  resize: vertical;
}
.field input:focus,
.field select:focus,
.field textarea:focus {
  border-color: var(--ns-pink);
  box-shadow: var(--ns-focus);
}
.fieldrow {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.drawer__note {
  margin: 2px 0 0;
  font-size: 11px;
  color: var(--ns-ink-3);
  line-height: 1.65;
}
.drawer__foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 20px;
  border-top: 1px solid var(--ns-line);
  background: var(--ns-card-2);
}
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.2s ease;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}
@media (max-width: 760px) {
  .thread {
    grid-template-columns: 1fr;
    gap: 6px;
  }
  .axis {
    padding-left: 16px;
  }
  .net__nowline {
    display: none;
  }
  .paid {
    grid-template-columns: 1fr;
  }
}
</style>

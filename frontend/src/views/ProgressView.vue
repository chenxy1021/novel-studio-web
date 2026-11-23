<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Button, Card, Tag, Modal, EmptyState, Input } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import RuleChip from '@/components/RuleChip.vue'
import { useStudio } from '@/stores/studio'
import { pct } from '@/lib/format'
import type { Finding } from '@/mocks'

const studio = useStudio()

const filter = ref<'all' | 'pending' | 'approved' | 'issues'>('all')
const expanded = ref<number | null>(null)
const search = reactive<Record<number, string>>({})

const showCopy = ref(false)
const copyTarget = ref(0)
const reviewer = reactive({ name: '陈工', note: '我核过没有' })
const rewriteTarget = ref<number | null>(null)
const rewriteNote = ref('')

onMounted(() => {
  studio.autoArchivePending()
})

const seg = computed(() => studio.recentSegment)
const segRange = computed(() => (seg.value ? `${seg.value.from}–${seg.value.to}` : '—'))
const inBatch = computed(() =>
  seg.value ? studio.sortedChapters.filter((c) => c.number >= seg.value!.from && c.number <= seg.value!.to) : [],
)
const rows = computed(() =>
  inBatch.value.filter((c) => {
    if (filter.value === 'pending') return !c.approved
    if (filter.value === 'approved') return c.approved
    if (filter.value === 'issues') return Boolean(studio.checks[c.number]?.findings.length)
    return true
  }),
)
const batchDone = computed(() => studio.approved.filter((c) => c.number >= (seg.value?.from ?? 0) && c.number <= (seg.value?.to ?? 0)).length)
const batchProgress = computed(() => pct(batchDone.value, seg.value ? seg.value.to - seg.value.from + 1 : 1))
const todoRewrite = computed(() => (studio.batch?.chapters ?? []).filter((c) => !c.pass).map((c) => c.number))

const sevTone = (s: Finding['severity']) => (s === 'high' ? 'bad' : s === 'mid' ? 'warn' : 'neutral')
const sevLabel = (s: Finding['severity']) => (s === 'high' ? '硬伤' : s === 'mid' ? '需改' : '提醒')

function tally(n: number) {
  const list = studio.checks[n]?.findings ?? []
  return {
    high: list.filter((f) => f.severity === 'high').length,
    mid: list.filter((f) => f.severity === 'mid').length,
    total: list.length,
  }
}

function highlight(text: string, kw: string) {
  if (!kw.trim()) return text
  const esc = kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return text.replace(new RegExp(esc, 'g'), (m) => `⟨${m}⟩`)
}

function openCopy(n: number) {
  copyTarget.value = n
  showCopy.value = true
}

async function doCopy() {
  const c = studio.findChapter(copyTarget.value)
  const text = `${c?.title}\n\n${studio.data.spineText[copyTarget.value] ?? c?.summary ?? ''}`
  try {
    await navigator.clipboard.writeText(text)
    studio.toast(`已复制第 ${copyTarget.value} 章正文`, 'ok')
  } catch {
    studio.toast('复制失败：浏览器不允许写剪贴板，请手动选中', 'warn')
  }
  showCopy.value = false
}

function startRewrite(n: number) {
  rewriteTarget.value = n
  const issues = studio.checks[n]?.findings ?? []
  rewriteNote.value = issues.map((f) => `· ${f.message}${f.hint ? `（${f.hint}）` : ''}`).join('\n')
}

function confirmRewrite() {
  const n = rewriteTarget.value!
  studio.rewrite(n, rewriteNote.value.trim() ? `，${rewriteNote.value.trim().split('\n').length} 条问题已附进重写要求` : '')
  rewriteTarget.value = null
}

function reviewed(n: number) {
  studio.toast(`第 ${n} 章审查已交给 Agent「${reviewer.name}」：要求挑最狠的一刀，不改就直接说结论`, 'info')
}

function syncSetting(n: number) {
  studio.toast(`第 ${n} 章的设定已补齐（只补空白字段，不覆盖已有值）`, 'ok')
}

function checkOne(n: number) {
  const c = studio.findChapter(n)
  if (!c) return
  studio.checks[n] = {
    pass: c.chapterVerdict === 'pass',
    findings: c.chapterVerdict === 'pass' ? [{ severity: 'info', code: 'ok', message: '没有发现连续性硬问题' }] : [{ severity: 'high', code: 'short', message: `正文低于 ${studio.book.minChars} 字硬下限` }],
    fromBatch: false,
  }
  studio.toast(`第 ${n} 章体检完成`, 'ok')
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="写 · 审 · 存"
      title="进度"
      :desc="`本批 ${segRange} 章。待确认章进页面自动存档；体检问题直接铺在那一章下面，跨章问题单列。`"
    >
      <Button :disabled="studio.batchBusy" icon="⚗" @click="studio.runBatchCheck()">
        {{ studio.batchBusy ? '按批体检中…' : `按批体检 第 ${segRange} 章` }}
      </Button>
      <Button variant="ghost" icon="☰" @click="$router.push({ name: 'detail' })">段落纲</Button>
    </PageHeader>

    <div class="batchbar">
      <div class="batchbar__left">
        <span class="batchbar__range ns-mono">{{ segRange }}</span>
        <div class="batchbar__meta">
          <b>{{ batchDone }}/{{ inBatch.length }} 章已存档</b>
          <span>{{ studio.book.targetChapters }} 章全书 · 第 {{ studio.nextNumber }} 章下一章 · 每章硬下限 {{ studio.book.minChars }} 字</span>
        </div>
      </div>
      <div class="batchbar__track"><i :style="{ width: `${batchProgress}%` }" /></div>
      <div class="batchbar__filters">
        <button v-for="f in [
          { k: 'all', t: '全部' },
          { k: 'pending', t: `待确认 ${studio.pending.length}` },
          { k: 'approved', t: '已存档' },
          { k: 'issues', t: '有体检问题' },
        ]" :key="f.k" type="button" class="batchbar__filter" :class="{ on: filter === f.k }" @click="filter = f.k as typeof filter">
          {{ f.t }}
        </button>
      </div>
    </div>

    <Card v-if="studio.batch" class="batchcard" eyebrow="整批视角" :title="`按批体检 第 ${studio.batch.from}–${studio.batch.to} 章`">
      <template #actions>
        <Button size="sm" variant="ghost" @click="studio.batch = null">关闭</Button>
      </template>
      <div class="batchcard__summary">
        <template v-if="todoRewrite.length">
          要重写：第 {{ todoRewrite.join('、') }} 章。
        </template>
        <template v-else>没有要重写的章。</template>
        {{ studio.batch.blocking.length ? `整批问题 ${studio.batch.blocking.length} 条。` : '' }}
        单章问题已铺在下面每一章，要改就点那一章的「重写本章」。
      </div>
      <div v-if="studio.batch.blocking.length" class="blocking">
        <div class="blocking__title">跨章问题（不属于某一章，批尾通过会被拦）</div>
        <div v-for="(f, i) in studio.batch.blocking" :key="i" class="blocking__item">
          <Tag size="sm" :tone="sevTone(f.severity)">{{ sevLabel(f.severity) }}</Tag>
          <div>
            <b>{{ f.message }}</b>
            <p v-if="f.hint">{{ f.hint }}</p>
          </div>
        </div>
      </div>
    </Card>

    <div class="list">
      <div v-for="c in rows" :key="c.number" class="row" :class="{ 'row--pending': !c.approved, 'row--open': expanded === c.number }">
        <div class="row__main" @click="expanded = expanded === c.number ? null : c.number">
          <span class="row__num ns-mono">{{ String(c.number).padStart(3, '0') }}</span>
          <div class="row__title">
            <b>{{ c.title }}</b>
            <span class="row__summary">{{ c.summary }}</span>
          </div>
          <div class="row__chars" :class="{ 'row__chars--short': c.chars < studio.book.minChars }">
            {{ c.chars }} 字
            <small v-if="c.chars < studio.book.minChars && c.chars > 0">低于下限</small>
          </div>
          <div class="row__tags">
            <Tag v-if="studio.checks[c.number]?.fromBatch" size="sm" tone="info" dot>按批体检</Tag>
            <Tag v-if="!c.endHook.ok" size="sm" tone="warn">章尾弱</Tag>
            <Tag v-if="!c.approved" size="sm" tone="pink" dot>待确认</Tag>
            <Tag v-else-if="c.chapterVerdict === 'needs_fix'" size="sm" tone="bad">待修</Tag>
            <Tag v-else size="sm" tone="ok">已存档</Tag>
          </div>
          <span class="row__caret">{{ expanded === c.number ? '⌃' : '⌄' }}</span>
        </div>

        <div v-if="!c.approved" class="row__acts row__acts--pending">
          <Button size="sm" variant="ghost" class="row__discard" @click="startRewrite(c.number)">退回重写</Button>
          <Button size="sm" @click="reviewed(c.number)">审查</Button>
          <Button size="sm" @click="syncSetting(c.number)">补设定</Button>
          <Button size="sm" @click="openCopy(c.number)">复制</Button>
          <div class="row__pending-tail">
            <span class="row__pending-label">待确认</span>
            <Button size="sm" variant="pink" @click="studio.archive(c.number)">存档</Button>
          </div>
        </div>
        <div v-else class="row__acts">
          <Button v-if="tally(c.number).high || c.chapterVerdict === 'needs_fix'" size="sm" variant="primary" @click="startRewrite(c.number)">重写本章</Button>
          <Button size="sm" @click="checkOne(c.number)">体检</Button>
          <Button size="sm" @click="reviewed(c.number)">审查</Button>
          <Button size="sm" @click="syncSetting(c.number)">补设定</Button>
          <Button size="sm" variant="ghost" @click="openCopy(c.number)">复制</Button>
          <Button size="sm" variant="ghost" class="row__discard" @click="studio.rewrite(c.number)">退回</Button>
        </div>

        <div v-if="studio.checks[c.number]" class="findings">
          <div class="findings__head">
            <span class="ns-eyebrow">第 {{ c.number }} 章体检</span>
            <Tag size="sm" :tone="tally(c.number).high ? 'bad' : tally(c.number).mid ? 'warn' : 'ok'">
              {{ tally(c.number).high }} 硬伤 · {{ tally(c.number).mid }} 需改 · {{ tally(c.number).total }} 条
            </Tag>
            <span v-if="!tally(c.number).total" class="findings__ok">没发现连续性问题</span>
            <Button size="sm" variant="ghost" class="findings__rw" @click="startRewrite(c.number)">重写本章</Button>
          </div>
          <ul v-if="tally(c.number).total" class="findings__list">
            <li v-for="(f, i) in studio.checks[c.number].findings" :key="i" :class="`findings__item findings__item--${f.severity}`">
              <Tag size="sm" :tone="sevTone(f.severity)">{{ sevLabel(f.severity) }}</Tag>
              <div>
                <b>{{ f.message }}</b>
                <p v-if="f.hint">{{ f.hint }}</p>
              </div>
            </li>
          </ul>
        </div>

        <Transition name="expand">
          <div v-if="expanded === c.number" class="row__body">
            <div class="row__search">
              <Input v-model="search[c.number]" size="sm" type="search" placeholder="在正文里搜（断层位置、某句原话都可以）">
                <template #prefix>⌕</template>
              </Input>
              <span v-if="search[c.number]" class="row__hits">命中高亮显示</span>
            </div>
            <div class="ns-prose row__prose">
              <template v-for="(para, i) in (studio.data.spineText[c.number] ?? c.summary).split('\n\n')" :key="i">
                <p>{{ highlight(para, search[c.number] ?? '') }}</p>
              </template>
            </div>
            <div class="row__bodyfoot">
              <RuleChip :ok="c.endHook.ok" :label="c.endHook.ok ? '章尾有钩子' : `章尾没钩子：${c.endHook.reason ?? ''}`" />
              <RuleChip :ok="c.dialogueRatio >= 0.2" :label="`对话比 ${Math.round(c.dialogueRatio * 100)}%`" />
              <RuleChip :ok="c.chars >= studio.book.minChars || studio.book.targetChapters <= 50" :label="`${c.chars} 字`" />
            </div>
          </div>
        </Transition>
      </div>
      <EmptyState v-if="!rows.length" icon="▦" title="这个筛选下没有章节" desc="换一个筛选，或者去概览页开下一批。" />
    </div>

    <Modal :open="showCopy" :title="`第 ${copyTarget} 章正文`" desc="整章复制，不改任何文件。粘贴到你的编辑器里改。" width="680px" @close="showCopy = false">
      <div class="ns-prose copybox">
        <pre>{{ studio.data.spineText[copyTarget] ?? studio.findChapter(copyTarget)?.summary }}</pre>
      </div>
      <template #footer>
        <Button variant="ghost" @click="showCopy = false">关闭</Button>
        <Button variant="primary" @click="doCopy">复制全文</Button>
      </template>
    </Modal>

    <Modal :open="rewriteTarget !== null" :title="`退回第 ${rewriteTarget} 章重写`" desc="旧稿会进「废章」可以恢复；下面的问题会一起交给 Agent。" width="640px" @close="rewriteTarget = null">
      <Input v-model="rewriteNote" label="重写要求（已按体检结果预填）" multiline :rows="8" />
      <template #footer>
        <Button variant="ghost" @click="rewriteTarget = null">取消</Button>
        <Button variant="primary" @click="confirmRewrite">退回并开写</Button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.page {
  max-width: 1120px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.batchbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.batchbar__left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.batchbar__range {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-18);
  font-weight: 700;
  padding-right: 12px;
  border-right: 1px solid var(--ns-line);
}
.batchbar__meta {
  display: grid;
  line-height: 1.4;
}
.batchbar__meta b {
  font-size: 12.5px;
}
.batchbar__meta span {
  font-size: 11px;
  color: var(--ns-ink-3);
}
.batchbar__track {
  flex: 1 1 120px;
  min-width: 80px;
  height: 5px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-card-2);
  overflow: hidden;
}
.batchbar__track i {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--ns-pink), #f27ab1);
  border-radius: inherit;
  transition: width 0.4s ease;
}
.batchbar__filters {
  display: inline-flex;
  padding: 2px;
  gap: 1px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.batchbar__filter {
  border: 0;
  background: transparent;
  color: var(--ns-ink-3);
  font: inherit;
  font-size: 11.5px;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
}
.batchbar__filter:hover {
  color: var(--ns-ink);
}
.batchbar__filter.on {
  background: var(--ns-card);
  color: var(--ns-ink);
  font-weight: 600;
  box-shadow: var(--ns-shadow-1);
}
.batchcard {
  margin-bottom: 14px;
}
.batchcard__summary {
  font-size: 12.5px;
  color: var(--ns-ink-2);
  margin-bottom: 12px;
}
.blocking {
  border: 1px solid color-mix(in srgb, var(--ns-warn) 28%, transparent);
  background: var(--ns-warn-soft);
  border-radius: var(--ns-r-sm);
  padding: 11px 13px;
  display: grid;
  gap: 8px;
}
.blocking__title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.03em;
  color: var(--ns-warn);
  text-transform: uppercase;
}
.blocking__item {
  display: flex;
  gap: 9px;
  align-items: flex-start;
}
.blocking__item b {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ns-ink);
}
.blocking__item p {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--ns-ink-2);
}
.list {
  display: grid;
  gap: 8px;
}
.row {
  background: var(--ns-card);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  padding: 0 16px;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.row:hover {
  border-color: var(--ns-line-2);
}
.row--pending {
  border-color: var(--ns-pink-line);
  background: linear-gradient(0deg, var(--ns-card), var(--ns-card)) padding-box, linear-gradient(90deg, var(--ns-pink-line), transparent) border-box;
}
.row--open {
  box-shadow: var(--ns-shadow-1);
}
.row__main {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 13px 0 10px;
  cursor: pointer;
}
.row__num {
  flex: none;
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-4);
  padding-top: 2px;
  letter-spacing: 0.02em;
}
.row__title {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 3px;
}
.row__title b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  line-height: 1.4;
}
.row__summary {
  font-size: 11.5px;
  color: var(--ns-ink-3);
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.row__chars {
  flex: none;
  font-size: 11.5px;
  color: var(--ns-ink-3);
  text-align: right;
  font-variant-numeric: tabular-nums;
  padding-top: 2px;
  display: grid;
  justify-items: end;
}
.row__chars small {
  font-size: 10px;
  color: var(--ns-bad);
}
.row__chars--short {
  color: var(--ns-bad);
}
.row__tags {
  flex: none;
  display: flex;
  gap: 4px;
  align-items: center;
  padding-top: 1px;
}
.row__caret {
  flex: none;
  color: var(--ns-ink-4);
  font-size: 12px;
  width: 14px;
  text-align: center;
  padding-top: 2px;
}
.row__acts {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  padding: 0 0 12px 40px;
}
.row__acts--pending {
  align-items: center;
  padding-left: 0;
}
.row__pending-tail {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  padding-left: 10px;
  border-left: 1px dashed var(--ns-line-2);
}
.row__pending-label {
  font-size: 11px;
  color: var(--ns-pink-ink, var(--ns-pink));
  letter-spacing: 0.04em;
}
.row__discard {
  color: var(--ns-bad);
}
.findings {
  margin: 0 0 12px 40px;
  padding: 10px 12px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  border: 1px solid var(--ns-line);
}
.findings__head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.findings__ok {
  font-size: 11.5px;
  color: var(--ns-ok);
}
.findings__rw {
  margin-left: auto;
}
.findings__list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.findings__item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding-left: 8px;
  border-left: 2px solid var(--ns-line-2);
}
.findings__item--high {
  border-left-color: var(--ns-bad);
}
.findings__item--mid {
  border-left-color: var(--ns-warn);
}
.findings__item b {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--ns-ink);
}
.findings__item p {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--ns-ink-3);
  line-height: 1.55;
}
.row__body {
  border-top: 1px dashed var(--ns-line);
  padding: 12px 0 14px 40px;
}
.row__search {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.row__hits {
  font-size: 11px;
  color: var(--ns-ink-3);
  white-space: nowrap;
}
.row__prose {
  max-height: 380px;
  overflow: auto;
  padding: 4px 14px 4px 0;
  background: var(--ns-paper);
  border-radius: var(--ns-r-sm);
  padding-left: 16px;
}
.row__prose :deep(p) {
  text-indent: 0;
  margin-bottom: 0.75em;
}
.row__bodyfoot {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.copybox pre {
  margin: 0;
  white-space: pre-wrap;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  line-height: 1.95;
  max-height: 380px;
  overflow: auto;
}
.expand-enter-active,
.expand-leave-active {
  transition: opacity 0.15s ease;
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
}
@media (max-width: 760px) {
  .page {
    padding: 20px 16px 64px;
  }
  .row__summary,
  .row__chars {
    display: none;
  }
  .row__acts,
  .findings,
  .row__body {
    padding-left: 0;
    margin-left: 0;
  }
}
</style>

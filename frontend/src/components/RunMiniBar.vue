<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from '@/design'
import { useStudio } from '@/stores/studio'

const studio = useStudio()
const router = useRouter()
const dismissedRunId = ref('')

const run = computed(() => studio.writeRun)
const failedRow = computed(() => run.value.chapters.find((c) => c.stage === 'failed') ?? null)
const doneCount = computed(() => run.value.chapters.filter((c) => c.stage === 'done').length)
const finished = computed(
  () =>
    !run.value.active &&
    !run.value.error &&
    run.value.chapters.some((c) => c.stage === 'done' || c.stage === 'skipped'),
)
const progress = computed(() =>
  run.value.total ? Math.round((run.value.done / run.value.total) * 100) : 0,
)

const visible = computed(() => {
  if (!run.value.chapters.length) return false
  if (studio.writePanel.open) return false
  if (run.value.runId && run.value.runId === dismissedRunId.value) return false
  return run.value.active || Boolean(run.value.error) || finished.value
})

const state = computed<'running' | 'failed' | 'done' | 'idle'>(() => {
  if (run.value.active) return 'running'
  if (run.value.error || failedRow.value) return 'failed'
  if (finished.value) return 'done'
  return 'idle'
})

const headline = computed(() => {
  if (state.value === 'running') return `正在写第 ${run.value.current || run.value.from} 章 · ${run.value.done}/${run.value.total}`
  if (state.value === 'failed') {
    if (failedRow.value) return `第 ${failedRow.value.number} 章失败`
    return '上次写作中断'
  }
  return `本批完成 · ${doneCount.value} 章待确认`
})

const detail = computed(() => {
  if (state.value === 'failed') {
    if (failedRow.value?.error) return failedRow.value.error
    return run.value.error || '第 N 章可能已落盘，检查后再重试。'
  }
  return ''
})

function view() {
  studio.openWritePanel({ source: 'today' })
}
async function retry() {
  if (!failedRow.value) return
  await studio.retryChapter(failedRow.value.number)
}
function dismiss() {
  dismissedRunId.value = run.value.runId || '__'
}
function review() {
  void router.push({
    path: '/progress',
    query: { from: String(run.value.from), to: String(run.value.to), filter: 'pending' },
  })
}
</script>

<template>
  <aside
    v-if="visible"
    class="rmb"
    :class="`rmb--${state}`"
    role="status"
    aria-live="polite"
  >
    <div class="rmb__main">
      <span class="rmb__icon" aria-hidden="true">
        {{ state === 'running' ? '◐' : state === 'failed' ? '!' : '✓' }}
      </span>
      <span class="rmb__text">
        <b class="rmb__headline">{{ headline }}</b>
        <span v-if="detail" class="rmb__detail" :title="detail">{{ detail }}</span>
      </span>
      <button type="button" class="rmb__x" aria-label="关闭写作状态条" @click="dismiss">✕</button>
    </div>

    <div v-if="state === 'running'" class="rmb__bar" aria-hidden="true">
      <span :style="{ width: `${progress}%` }" />
    </div>

    <div class="rmb__acts">
      <Button size="sm" variant="ghost" @click="view">查看</Button>
      <Button
        v-if="state === 'failed' && failedRow"
        size="sm"
        variant="secondary"
        @click="retry"
      >重试</Button>
      <Button
        v-if="state === 'done'"
        size="sm"
        variant="pink"
        @click="review"
      >去审阅</Button>
    </div>
  </aside>
</template>

<style scoped>
.rmb {
  position: fixed;
  right: var(--ns-s6);
  bottom: var(--ns-s6);
  z-index: 40;
  width: 340px;
  max-width: calc(100vw - 32px);
  display: grid;
  gap: var(--ns-s2);
  padding: var(--ns-s3) var(--ns-s4);
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  box-shadow: var(--ns-shadow-3);
  animation: rmb-in 0.16s ease;
}
.rmb--failed {
  border-color: color-mix(in srgb, var(--ns-warn) 35%, transparent);
  background: var(--ns-warn-soft);
}
.rmb--done {
  border-color: color-mix(in srgb, var(--ns-ok) 30%, transparent);
}
.rmb__main {
  display: flex;
  align-items: flex-start;
  gap: var(--ns-s2);
}
.rmb__icon {
  flex: none;
  width: 18px;
  color: var(--ns-pink);
  font-size: var(--ns-fs-13);
  line-height: 1.4;
}
.rmb--failed .rmb__icon {
  color: var(--ns-warn);
  font-weight: 700;
}
.rmb--done .rmb__icon {
  color: var(--ns-ok);
}
.rmb__text {
  display: grid;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.rmb__headline {
  color: var(--ns-ink);
  font-size: var(--ns-fs-12);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.rmb__detail {
  overflow: hidden;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rmb__x {
  flex: none;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: var(--ns-r-xs);
  background: transparent;
  color: var(--ns-ink-3);
  cursor: pointer;
}
.rmb__x:hover {
  background: var(--ns-card-2);
  color: var(--ns-ink);
}
.rmb__bar {
  height: 3px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-line);
  overflow: hidden;
}
.rmb__bar span {
  display: block;
  height: 100%;
  background: var(--ns-pink);
  transition: width 0.2s ease;
}
.rmb__acts {
  display: flex;
  justify-content: flex-end;
  gap: var(--ns-s1);
}
@keyframes rmb-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@media (prefers-reduced-motion: reduce) {
  .rmb {
    animation: none;
  }
  .rmb__bar span {
    transition: none;
  }
}
</style>

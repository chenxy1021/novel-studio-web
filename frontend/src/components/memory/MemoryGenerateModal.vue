<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Modal } from '@/design'
import { useStudio } from '@/stores/studio'
import type { MemoryOverview } from '@/api/studio'
import { volumeOfChapter } from './memory-helpers'

type Scope = 'missing' | 'range' | 'volume'
type Confirm = '' | 'chapters' | 'volume'

const props = withDefaults(
  defineProps<{
    open: boolean
    memory: MemoryOverview | null
    selected?: number | null
  }>(),
  { selected: null },
)
const emit = defineEmits<{ close: [] }>()

const studio = useStudio()

const scope = ref<Scope>('missing')
const from = ref(1)
const to = ref(1)
const alsoVolumes = ref(true)
const confirmMode = ref<Confirm>('')
const started = ref(false)
const finished = ref(false)
const volumeRunning = ref(false)
const volumeOk = ref(false)

const written = computed(() => (props.memory?.chapters ?? []).map((c) => c.chapter).sort((a, b) => a - b))
const missing = computed(() => props.memory?.coverage.missing ?? [])
const volumes = computed(() => props.memory?.volumes ?? [])
const gateChapter = computed(() => studio.nextNumber)

const currentVolume = computed(() => {
  const n = props.selected ?? gateChapter.value
  return volumeOfChapter(n, volumes.value) ?? volumes.value[0] ?? null
})

const rangeChapters = computed(() => {
  const a = Number(from.value)
  const b = Number(to.value)
  if (!Number.isFinite(a) || !Number.isFinite(b) || b < a) return []
  return written.value.filter((n) => n >= a && n <= b)
})

const overwriteCount = computed(() => {
  const byChapter = new Map((props.memory?.chapters ?? []).map((c) => [c.chapter, c.summary]))
  return rangeChapters.value.filter((n) => Boolean(byChapter.get(n))).length
})

const targetCount = computed(() => {
  if (scope.value === 'missing') return missing.value.length
  if (scope.value === 'range') return rangeChapters.value.length
  return currentVolume.value ? 1 : 0
})

const estimateText = computed(() => {
  const n = scope.value === 'volume' ? 1 : targetCount.value
  if (!n) return '还没有可生成的目标。'
  if (scope.value === 'volume') return '每卷一次模型调用，大约 1–2 分钟。'
  const x = Math.max(1, Math.round(n * 0.55))
  const y = Math.max(x + 1, Math.round(n * 1.1))
  return `每章一次模型调用，${n} 章大约 ${x}–${y} 分钟。`
})

const running = computed(() => studio.memoryGen.running)
const busy = computed(() => running.value || volumeRunning.value)
const gen = computed(() => studio.memoryGen)

function resetForm() {
  scope.value = missing.value.length ? 'missing' : 'range'
  from.value = missing.value[0] ?? written.value[0] ?? 1
  to.value = written.value[written.value.length - 1] ?? gateChapter.value
  alsoVolumes.value = true
  confirmMode.value = ''
  started.value = false
  finished.value = false
  volumeOk.value = false
  if (!studio.memoryGen.running) studio.resetMemoryGen()
}

watch(
  () => props.open,
  (open) => {
    if (open) resetForm()
  },
  { immediate: true },
)

watch(
  () => studio.memoryGen.running,
  (now, was) => {
    if (now) {
      started.value = true
      finished.value = false
      confirmMode.value = ''
    } else if (was && started.value) {
      finished.value = true
    }
  },
  { immediate: true },
)

function start() {
  if (!targetCount.value) return
  if (scope.value === 'volume') {
    if (!currentVolume.value) return
    if (currentVolume.value.summary) {
      confirmMode.value = 'volume'
      return
    }
    void runVolume()
    return
  }
  if (scope.value === 'range' && overwriteCount.value > 0) {
    confirmMode.value = 'chapters'
    return
  }
  void runChapters()
}

async function runChapters() {
  confirmMode.value = ''
  started.value = true
  finished.value = false
  await studio.generateMissingMemory({
    from: scope.value === 'range' ? Number(from.value) : undefined,
    to: scope.value === 'range' ? Number(to.value) : undefined,
    force: scope.value === 'range' && overwriteCount.value > 0,
    alsoVolumes: alsoVolumes.value,
  })
  finished.value = true
}

async function runVolume() {
  const v = currentVolume.value
  if (!v) return
  confirmMode.value = ''
  volumeRunning.value = true
  const res = await studio.generateVolumeMemory(v.volume, { force: true })
  volumeRunning.value = false
  volumeOk.value = Boolean(res)
  started.value = true
  finished.value = true
}

function confirmRun() {
  if (confirmMode.value === 'volume') void runVolume()
  else void runChapters()
}

function close() {
  if (busy.value) return
  emit('close')
}

const failLine = computed(() => {
  const failed = gen.value.failed
  const done = gen.value.done
  if (!failed.length) return ''
  if (!done) return `这一轮没有生成成功：${failed[0].error}`
  return `已生成 ${done} 章；第 ${failed[0].chapter} 章失败：${failed[0].error}`
})
</script>

<template>
  <Modal
    :open="open"
    title="生成叙事记忆"
    desc="从已写章节里提炼时间线、事件、人物状态、关系、伏笔埋收。"
    width="620px"
    @close="close"
  >
    <!-- 逐章生成中 -->
    <div v-if="running" class="gm__run">
      <p class="gm__runline">
        正在生成第 {{ gen.current }} 章 · {{ gen.done }}/{{ gen.total }}
      </p>
      <div class="gm__bar"><i :style="{ width: `${gen.total ? (gen.done / gen.total) * 100 : 0}%` }" /></div>
      <p v-if="gen.failed.length" class="gm__warn">{{ failLine }}</p>
      <Button v-if="!gen.paused" size="sm" variant="ghost" @click="studio.pauseMemoryGen()">
        暂停（本章完成后）
      </Button>
      <p v-else class="gm__muted">暂停中：当前这一章完成后停止。</p>
    </div>

    <!-- 卷摘要生成中 -->
    <div v-else-if="volumeRunning" class="gm__run">
      <p class="gm__runline">正在生成卷摘要…</p>
      <div class="gm__bar"><i class="gm__bar--wait" /></div>
    </div>

    <!-- 完成 -->
    <div v-else-if="finished" class="gm__done">
      <template v-if="volumeOk || volumeRunning === false && scope === 'volume' && started">
        <p class="gm__ok">
          {{ volumeOk ? '卷摘要已生成。' : '卷摘要生成失败。' }}
        </p>
      </template>
      <template v-else>
        <p v-if="!gen.failed.length" class="gm__ok">已生成 {{ gen.done }} 章记忆。</p>
        <p v-else class="gm__warn">{{ failLine }}</p>
        <p v-if="gen.failed.length > 1" class="gm__muted">
          共 {{ gen.failed.length }} 章失败：第 {{ gen.failed.map((f) => f.chapter).join('、') }} 章。
        </p>
        <Button
          v-if="gen.failed.length"
          size="sm"
          variant="ghost"
          :disabled="!missing.length"
          @click="start"
        >
          重试缺的章
        </Button>
      </template>
    </div>

    <!-- 覆盖二次确认 -->
    <div v-else-if="confirmMode" class="gm__confirm">
      <template v-if="confirmMode === 'volume'">
        <p class="gm__confirmq">重新生成「{{ currentVolume?.title || '这一卷' }}」的卷摘要？</p>
      </template>
      <template v-else>
        <p class="gm__confirmq">重新生成 {{ overwriteCount }} 章记忆？</p>
      </template>
      <p class="gm__muted">
        新结果会覆盖当前显示；旧记录仍保留在 ledger/memory.jsonl，但不再展示。
      </p>
    </div>

    <!-- 选项 -->
    <div v-else class="gm__form">
      <div class="gm__field">
        <div class="ns-eyebrow">范围</div>
        <label class="gm__radio">
          <input v-model="scope" type="radio" value="missing" />
          <span>只补缺失（{{ missing.length }} 章）</span>
        </label>
        <label class="gm__radio">
          <input v-model="scope" type="radio" value="range" />
          <span>
            第
            <input v-model.number="from" class="gm__num" type="number" min="1" aria-label="起始章" />
            –
            <input v-model.number="to" class="gm__num" type="number" min="1" aria-label="结束章" />
            章
          </span>
        </label>
        <label class="gm__radio" :class="{ 'gm__radio--off': !currentVolume }">
          <input v-model="scope" type="radio" value="volume" :disabled="!currentVolume" />
          <span>
            只生成卷摘要
            <span v-if="currentVolume" class="gm__muted">
              · {{ currentVolume.title || `第${currentVolume.volume}卷` }}（第 {{ currentVolume.from }}–{{ currentVolume.to }} 章）
            </span>
          </span>
        </label>
      </div>

      <label v-if="scope !== 'volume'" class="gm__check">
        <input v-model="alsoVolumes" type="checkbox" />
        <span>生成完顺带更新卷摘要</span>
      </label>

      <p class="gm__est">{{ estimateText }}</p>
    </div>

    <template #footer>
      <template v-if="running">
        <Button variant="ghost" :disabled="gen.paused" @click="studio.pauseMemoryGen()">
          暂停（本章完成后）
        </Button>
      </template>
      <template v-else-if="finished">
        <Button variant="primary" @click="emit('close')">关闭</Button>
      </template>
      <template v-else-if="confirmMode">
        <Button variant="ghost" @click="confirmMode = ''">取消</Button>
        <Button variant="danger" @click="confirmRun">继续</Button>
      </template>
      <template v-else>
        <Button variant="ghost" @click="emit('close')">取消</Button>
        <Button variant="primary" :disabled="!targetCount || busy" @click="start">
          {{ scope === 'volume' ? '开始生成卷摘要' : `开始生成 ${targetCount} 章` }}
        </Button>
      </template>
    </template>
  </Modal>
</template>

<style scoped>
.gm__form {
  display: grid;
  gap: var(--ns-s3);
}
.gm__field {
  display: grid;
  gap: 6px;
}
.gm__radio,
.gm__check {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-2);
  cursor: pointer;
}
.gm__radio--off {
  color: var(--ns-ink-4);
}
.gm__radio input[type='radio'],
.gm__check input[type='checkbox'] {
  accent-color: var(--ns-pink);
}
.gm__num {
  width: 58px;
  padding: 2px 5px;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-xs);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: var(--ns-fs-12);
  text-align: center;
}
.gm__est {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.gm__run {
  display: grid;
  gap: var(--ns-s2);
}
.gm__runline {
  margin: 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
}
.gm__bar {
  height: 6px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-card-2);
  overflow: hidden;
}
.gm__bar i {
  display: block;
  height: 100%;
  background: var(--ns-pink);
  transition: width 0.2s ease;
}
.gm__bar i.gm__bar--wait {
  width: 35%;
  animation: gm-wait 1.2s ease-in-out infinite;
}
@keyframes gm-wait {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(300%); }
}
.gm__warn {
  margin: 0;
  padding: 6px 8px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-warn-soft);
  color: var(--ns-warn);
  font-size: var(--ns-fs-11);
}
.gm__ok {
  margin: 0;
  color: var(--ns-ok);
  font-size: var(--ns-fs-13);
}
.gm__muted {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.gm__confirm {
  display: grid;
  gap: var(--ns-s2);
}
.gm__confirmq {
  margin: 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
}
</style>

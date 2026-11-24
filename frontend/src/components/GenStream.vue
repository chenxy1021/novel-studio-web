<script setup lang="ts">
/** 生成实况：模型正在写的内容边收边显示，阶段、字数、耗时一起给。 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    active: boolean
    text: string
    title?: string
    stage?: string
    kind?: string
    startedAt?: number
    /** 模型思考过程（复检这类需要让作者看见思路的生成）。 */
    reason?: string
    /** 没有标题时显示的默认标签。 */
    label?: string
  }>(),
  { title: '', stage: '', kind: '', startedAt: 0, reason: '', label: '生成实况' },
)

const scroller = ref<HTMLElement | null>(null)
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined

function tick() {
  now.value = Date.now()
}

watch(
  () => props.active,
  (on) => {
    if (timer) {
      clearInterval(timer)
      timer = undefined
    }
    if (on) {
      tick()
      timer = setInterval(tick, 1000)
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})

/** 细纲的机器块不给作者看：截到 JSON 标记前，等收尾再切走。 */
const organizing = computed(() => props.kind === 'outline' && props.text.includes('<<<OUTLINE_JSON'))
const visible = computed(() => {
  if (organizing.value) return props.text.slice(0, props.text.indexOf('<<<OUTLINE_JSON'))
  return props.text
})
const charCount = computed(() => {
  const cjk = visible.value.match(/[㐀-鿿]/g)
  return cjk ? cjk.length : visible.value.replace(/\s/g, '').length
})
const reasonChars = computed(() => {
  const cjk = props.reason.match(/[㐀-鿿]/g)
  return cjk ? cjk.length : props.reason.replace(/\s/g, '').length
})
const elapsed = computed(() => {
  if (!props.startedAt) return 0
  return Math.max(0, Math.round((now.value - props.startedAt) / 1000))
})
const show = computed(() => props.active || Boolean(props.text) || Boolean(props.reason))

watch(
  [visible, () => props.reason, () => props.active],
  async () => {
    await nextTick()
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  },
)
</script>

<template>
  <section v-if="show" class="gs" :class="{ 'gs--idle': !active }" aria-label="AI 生成实况">
    <header class="gs__head">
      <span class="gs__dot" :class="{ on: active }" aria-hidden="true" />
      <b class="gs__title">{{ title || label }}</b>
      <span v-if="stage" class="gs__stage">{{ stage }}</span>
      <span class="gs__meta ns-num">
        <template v-if="reasonChars">{{ reasonChars }} 字思考 · </template>{{ charCount }} 字 · {{ elapsed }}s
      </span>
    </header>
    <div ref="scroller" class="gs__body">
      <div v-if="reason" class="gs__reason">
        <span class="gs__reasonlabel">思考过程</span>
        <pre class="gs__reasontext">{{ reason }}</pre>
      </div>
      <p v-if="!visible && !reason && active" class="gs__wait">等待模型落笔…</p>
      <pre v-else-if="visible" class="gs__text" :class="{ 'is-live': active }">{{ visible }}</pre>
      <p v-if="organizing" class="gs__wait">正文写完，正在整理节拍…</p>
      <p v-else-if="!visible && !reason && !active" class="gs__wait">这一轮没有收到内容。</p>
    </div>
  </section>
</template>

<style scoped>
.gs {
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  overflow: hidden;
}
.gs--idle {
  opacity: 0.78;
}
.gs__head {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  padding: 7px 12px;
  border-bottom: 1px solid var(--ns-line);
  background: var(--ns-card-2);
  font-size: var(--ns-fs-12);
}
.gs__dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ns-ink-4);
  flex: none;
}
.gs__dot.on {
  background: var(--ns-pink);
  animation: gs-pulse 1.2s ease-in-out infinite;
}
@keyframes gs-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.35;
  }
}
.gs__title {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-13);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.gs__stage {
  flex: none;
  padding: 0 7px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-pink-soft);
  color: var(--ns-pink-2);
  font-size: var(--ns-fs-11);
  line-height: 1.7;
}
.gs__meta {
  margin-left: auto;
  flex: none;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.gs__body {
  max-height: 240px;
  overflow: auto;
  padding: 10px 14px;
  scroll-behavior: smooth;
}
.gs__reason {
  margin: 0 0 10px;
  padding: 8px 10px;
  border-left: 2px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-hover);
}
.gs__reasonlabel {
  display: block;
  margin-bottom: 4px;
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: var(--ns-ink-3);
}
.gs__reasontext {
  margin: 0;
  max-height: 160px;
  overflow: auto;
  font-family: var(--ns-mono);
  font-size: 11px;
  line-height: 1.65;
  color: var(--ns-ink-2);
  opacity: 0.82;
  white-space: pre-wrap;
  word-break: break-word;
}
.gs__text {
  margin: 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-13);
  line-height: 1.85;
  color: var(--ns-ink-2);
  white-space: pre-wrap;
  word-break: break-word;
}
.gs__text.is-live::after {
  content: '▍';
  color: var(--ns-pink);
  animation: gs-caret 1s step-end infinite;
}
@keyframes gs-caret {
  50% {
    opacity: 0;
  }
}
.gs__wait {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
}
@media (prefers-reduced-motion: reduce) {
  .gs__dot.on,
  .gs__text.is-live::after {
    animation: none;
  }
}
</style>

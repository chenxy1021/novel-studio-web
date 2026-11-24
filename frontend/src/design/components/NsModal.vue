<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    desc?: string
    width?: string
  }>(),
  { title: '', desc: '', width: '560px' },
)
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
const titleId = `ns-modal-title-${useId()}`

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

let previousFocus: HTMLElement | null = null

function focusables(): HTMLElement[] {
  const root = panel.value
  if (!root) return []
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  )
}

/** 把 Tab / Shift+Tab 锁在对话框内；焦点意外跑出去时拉回第一个可聚焦元素。 */
function trapTab(e: KeyboardEvent) {
  const list = focusables()
  if (!list.length) {
    e.preventDefault()
    return
  }
  const active = document.activeElement as HTMLElement | null
  const first = list[0]
  const last = list[list.length - 1]
  if (!panel.value?.contains(active)) {
    e.preventDefault()
    first.focus()
    return
  }
  if (e.shiftKey && active === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && active === last) {
    e.preventDefault()
    first.focus()
  }
}

function onKey(e: KeyboardEvent) {
  if (!props.open) return
  if (e.key === 'Escape') {
    emit('close')
    return
  }
  if (e.key === 'Tab') trapTab(e)
}

function lock(on: boolean) {
  document.body.style.overflow = on ? 'hidden' : ''
}

function restoreFocus() {
  const el = previousFocus
  previousFocus = null
  if (el && typeof el.focus === 'function' && el.isConnected) el.focus()
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  lock(props.open)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  lock(false)
  if (props.open) restoreFocus()
})

watch(
  () => props.open,
  async (open, was) => {
    lock(open)
    if (open) {
      previousFocus = document.activeElement as HTMLElement | null
      await nextTick()
      const list = focusables()
      ;(list[0] ?? panel.value)?.focus()
    } else if (was) {
      restoreFocus()
    }
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="ns-modal">
      <div v-if="open" class="ns-modal" @click.self="emit('close')">
        <div
          ref="panel"
          class="ns-modal__panel"
          role="dialog"
          aria-modal="true"
          tabindex="-1"
          :aria-labelledby="title ? titleId : undefined"
          :aria-label="title ? undefined : '对话框'"
          :style="{ width }"
        >
          <header class="ns-modal__head">
            <div>
              <h2 :id="titleId">{{ title }}</h2>
              <p v-if="desc">{{ desc }}</p>
            </div>
            <button type="button" class="ns-modal__x" aria-label="关闭" @click="emit('close')">✕</button>
          </header>
          <div class="ns-modal__body"><slot /></div>
          <footer v-if="$slots.footer" class="ns-modal__foot"><slot name="footer" /></footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ns-modal {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(28, 26, 23, 0.34);
  backdrop-filter: blur(2px);
  display: grid;
  place-items: center;
  padding: var(--ns-s6);
}
.ns-modal__panel {
  max-width: 100%;
  max-height: 86vh;
  display: flex;
  flex-direction: column;
  background: var(--ns-card);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-xl);
  box-shadow: var(--ns-shadow-3);
  overflow: hidden;
}
.ns-modal__head {
  display: flex;
  align-items: flex-start;
  gap: var(--ns-s4);
  padding: var(--ns-s5) var(--ns-s6) var(--ns-s3);
  border-bottom: 1px solid var(--ns-line);
}
.ns-modal__head > div {
  flex: 1;
}
.ns-modal h2 {
  margin: 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-18);
  font-weight: 700;
}
.ns-modal p {
  margin: 4px 0 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
}
.ns-modal__x {
  border: 0;
  background: transparent;
  color: var(--ns-ink-3);
  cursor: pointer;
  width: 28px;
  height: 28px;
  border-radius: var(--ns-r-sm);
}
.ns-modal__x:hover {
  background: var(--ns-card-2);
  color: var(--ns-ink);
}
.ns-modal__body {
  padding: var(--ns-s5) var(--ns-s6);
  overflow: auto;
}
.ns-modal__foot {
  display: flex;
  justify-content: flex-end;
  gap: var(--ns-s2);
  padding: var(--ns-s3) var(--ns-s6);
  border-top: 1px solid var(--ns-line);
  background: var(--ns-card-2);
}
.ns-modal-enter-active,
.ns-modal-leave-active {
  transition: opacity 0.16s ease;
}
.ns-modal-enter-active .ns-modal__panel,
.ns-modal-leave-active .ns-modal__panel {
  transition: transform 0.18s ease;
}
.ns-modal-enter-from,
.ns-modal-leave-to {
  opacity: 0;
}
.ns-modal-enter-from .ns-modal__panel,
.ns-modal-leave-to .ns-modal__panel {
  transform: translateY(8px) scale(0.99);
}
</style>

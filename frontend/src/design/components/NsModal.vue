<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

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

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.open) emit('close')
}

function lock(on: boolean) {
  document.body.style.overflow = on ? 'hidden' : ''
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  lock(props.open)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  lock(false)
})
watch(() => props.open, lock)
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
          :aria-label="title"
          :style="{ width }"
        >
          <header class="ns-modal__head">
            <div>
              <h2>{{ title }}</h2>
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

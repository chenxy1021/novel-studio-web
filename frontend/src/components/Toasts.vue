<script setup lang="ts">
import { useStudio } from '@/stores/studio'
const studio = useStudio()
</script>

<template>
  <div class="toasts" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="t in studio.toasts" :key="t.id" class="toast" :class="`toast--${t.tone}`">
        <span class="toast__dot" />
        {{ t.text }}
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  z-index: 60;
  display: grid;
  gap: 8px;
  justify-items: center;
  pointer-events: none;
}
.toast {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 560px;
  padding: 9px 14px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-ink);
  color: var(--ns-paper);
  font-size: var(--ns-fs-12);
  box-shadow: var(--ns-shadow-2);
}
.toast__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--ns-ink-4);
  flex: none;
}
.toast--ok .toast__dot {
  background: #6bc79b;
}
.toast--warn .toast__dot {
  background: #e2a24a;
}
.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>

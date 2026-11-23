<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'pink'
    size?: 'sm' | 'md'
    icon?: string
    disabled?: boolean
    block?: boolean
  }>(),
  { variant: 'secondary', size: 'md', icon: '', disabled: false, block: false },
)
</script>

<template>
  <button
    type="button"
    class="ns-btn"
    :class="[`ns-btn--${variant}`, `ns-btn--${size}`, { 'ns-btn--block': block }]"
    :disabled="disabled"
  >
    <span v-if="icon" class="ns-btn__icon" aria-hidden="true">{{ icon }}</span>
    <slot />
  </button>
</template>

<style scoped>
.ns-btn {
  appearance: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid var(--ns-line-2);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: var(--ns-fs-13);
  font-weight: 500;
  line-height: 1;
  padding: 0 14px;
  height: 34px;
  border-radius: var(--ns-r-sm);
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.14s ease, border-color 0.14s ease, color 0.14s ease, box-shadow 0.14s ease;
}
.ns-btn:hover:not(:disabled) {
  background: var(--ns-card-2);
  border-color: var(--ns-ink-4);
}
.ns-btn:active:not(:disabled) {
  transform: translateY(0.5px);
}
.ns-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.ns-btn--sm {
  height: 28px;
  padding: 0 10px;
  font-size: var(--ns-fs-12);
  gap: 4px;
}
.ns-btn--block {
  display: flex;
  width: 100%;
}
.ns-btn--ghost {
  border-color: transparent;
  background: transparent;
  color: var(--ns-ink-2);
}
.ns-btn--ghost:hover:not(:disabled) {
  background: var(--ns-card-2);
  border-color: transparent;
  color: var(--ns-ink);
}
.ns-btn--primary {
  background: var(--ns-ink);
  border-color: var(--ns-ink);
  color: var(--ns-card);
  font-weight: 600;
}
.ns-btn--primary:hover:not(:disabled) {
  background: #000;
  border-color: #000;
}
.ns-btn--pink {
  background: var(--ns-pink);
  border-color: var(--ns-pink);
  color: #fff;
  font-weight: 600;
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.06);
}
.ns-btn--pink:hover:not(:disabled) {
  background: var(--ns-pink-2);
  border-color: var(--ns-pink-2);
}
.ns-btn--danger {
  background: transparent;
  border-color: var(--ns-bad);
  color: var(--ns-bad);
}
.ns-btn--danger:hover:not(:disabled) {
  background: var(--ns-bad-soft);
}
.ns-btn__icon {
  font-size: 13px;
  line-height: 1;
  opacity: 0.85;
}
</style>

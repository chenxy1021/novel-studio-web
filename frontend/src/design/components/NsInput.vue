<script setup lang="ts">
import { computed, useAttrs, useSlots } from 'vue'

defineOptions({ inheritAttrs: false })

const props = withDefaults(
  defineProps<{
    modelValue?: string | number
    label?: string
    hint?: string
    placeholder?: string
    type?: 'text' | 'number' | 'search' | 'password' | 'email'
    multiline?: boolean
    rows?: number
    serif?: boolean
    size?: 'sm' | 'md' | 'lg'
    error?: string
  }>(),
  { modelValue: '', label: '', hint: '', placeholder: '', type: 'text', multiline: false, rows: 4, serif: false, size: 'md', error: '' },
)
const emit = defineEmits<{ 'update:modelValue': [string] }>()
const attrs = useAttrs()
const slots = useSlots()
const value = computed({
  get: () => String(props.modelValue ?? ''),
  set: (v: string) => emit('update:modelValue', v),
})
</script>

<template>
  <label class="ns-field">
    <span v-if="label" class="ns-field__label">{{ label }}</span>
    <span class="ns-field__wrap">
      <span v-if="$slots.prefix" class="ns-field__affix"><slot name="prefix" /></span>
      <textarea
        v-if="multiline"
        v-model="value"
        class="ns-field__input"
        :class="[`ns-field__input--${size}`, { 'ns-field__input--serif': serif, 'ns-field__input--error': error }]"
        :rows="rows"
        :placeholder="placeholder"
        v-bind="attrs"
      />
      <input
        v-else
        v-model="value"
        class="ns-field__input"
        :class="[`ns-field__input--${size}`, { 'ns-field__input--serif': serif, 'ns-field__input--error': error }]"
        :type="type"
        :placeholder="placeholder"
        v-bind="attrs"
      />
    </span>
    <span v-if="error" class="ns-field__error">{{ error }}</span>
    <span v-else-if="hint || slots.hint" class="ns-field__hint"><slot name="hint">{{ hint }}</slot></span>
  </label>
</template>

<style scoped>
.ns-field {
  display: grid;
  gap: 6px;
  min-width: 0;
}
.ns-field__label {
  font-size: var(--ns-fs-12);
  font-weight: 600;
  color: var(--ns-ink-2);
}
.ns-field__wrap {
  display: flex;
  align-items: stretch;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  transition: border-color 0.14s ease, box-shadow 0.14s ease;
  overflow: hidden;
}
.ns-field__wrap:focus-within {
  border-color: var(--ns-pink);
  box-shadow: var(--ns-focus);
}
.ns-field__affix {
  display: grid;
  place-items: center;
  padding-left: 10px;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-13);
}
.ns-field__input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--ns-ink);
  font: inherit;
  padding: 0 11px;
  height: 34px;
  resize: vertical;
}
.ns-field__input--sm {
  height: 28px;
  font-size: var(--ns-fs-12);
}
.ns-field__input--lg {
  height: 40px;
  font-size: var(--ns-fs-14);
}
textarea.ns-field__input {
  height: auto;
  padding: 9px 11px;
  line-height: 1.7;
}
.ns-field__input--serif {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  line-height: var(--ns-lh-prose);
}
.ns-field__input--error {
  box-shadow: inset 0 0 0 1px var(--ns-bad);
}
.ns-field__hint {
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
}
.ns-field__error {
  font-size: var(--ns-fs-11);
  color: var(--ns-bad);
  font-weight: 600;
}
.ns-field__input::placeholder {
  color: var(--ns-ink-4);
}
</style>

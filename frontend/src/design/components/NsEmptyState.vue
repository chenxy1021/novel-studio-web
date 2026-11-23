<script setup lang="ts">
withDefaults(
  defineProps<{
    icon?: string
    title: string
    desc?: string
    compact?: boolean
  }>(),
  { icon: '✎', desc: '', compact: false },
)
</script>

<template>
  <div class="ns-empty" :class="{ 'ns-empty--compact': compact }">
    <div class="ns-empty__icon" aria-hidden="true">{{ icon }}</div>
    <b>{{ title }}</b>
    <p v-if="desc">{{ desc }}</p>
    <div v-if="$slots.default" class="ns-empty__acts"><slot /></div>
  </div>
</template>

<style scoped>
.ns-empty {
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 6px;
  padding: var(--ns-s10) var(--ns-s6);
  border: 1px dashed var(--ns-line-2);
  border-radius: var(--ns-r-md);
  background: color-mix(in srgb, var(--ns-card-2) 70%, transparent);
}
.ns-empty--compact {
  padding: var(--ns-s6) var(--ns-s4);
}
.ns-empty__icon {
  width: 40px;
  height: 40px;
  border-radius: var(--ns-r-md);
  display: grid;
  place-items: center;
  background: var(--ns-pink-soft);
  color: var(--ns-pink);
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-18);
  margin-bottom: 2px;
}
.ns-empty b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
}
.ns-empty p {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
  line-height: 1.7;
  max-width: 46ch;
}
.ns-empty__acts {
  display: flex;
  gap: var(--ns-s2);
  margin-top: var(--ns-s2);
}
</style>

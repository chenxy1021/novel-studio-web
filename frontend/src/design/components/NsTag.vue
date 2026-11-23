<script setup lang="ts">
withDefaults(
  defineProps<{
    tone?: 'neutral' | 'ink' | 'pink' | 'ok' | 'warn' | 'bad' | 'info' | 'gold'
    size?: 'sm' | 'md'
    dot?: boolean
    pill?: boolean
  }>(),
  { tone: 'neutral', size: 'md', dot: false, pill: false },
)
</script>

<template>
  <span class="ns-tag" :class="[`ns-tag--${tone}`, `ns-tag--${size}`, { 'ns-tag--pill': pill }]">
    <i v-if="dot" class="ns-tag__dot" aria-hidden="true" />
    <slot />
  </span>
</template>

<style scoped>
.ns-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border-radius: var(--ns-r-xs);
  padding: 1px 7px;
  font-size: var(--ns-fs-11);
  font-weight: 600;
  line-height: 1.7;
  white-space: nowrap;
  border: 1px solid transparent;
  font-variant-numeric: tabular-nums;
}
.ns-tag--sm {
  font-size: 10.5px;
  padding: 0 6px;
}
.ns-tag--pill {
  border-radius: var(--ns-r-pill);
}
.ns-tag--neutral {
  background: var(--ns-card-2);
  border-color: var(--ns-line);
  color: var(--ns-ink-2);
}
.ns-tag--ink {
  background: var(--ns-ink);
  color: var(--ns-card);
}
.ns-tag--pink {
  background: var(--ns-pink);
  color: #fff;
}
.ns-tag--ok {
  background: var(--ns-ok-soft);
  color: var(--ns-ok);
  border-color: color-mix(in srgb, var(--ns-ok) 20%, transparent);
}
.ns-tag--warn {
  background: var(--ns-warn-soft);
  color: var(--ns-warn);
  border-color: color-mix(in srgb, var(--ns-warn) 20%, transparent);
}
.ns-tag--bad {
  background: var(--ns-bad-soft);
  color: var(--ns-bad);
  border-color: color-mix(in srgb, var(--ns-bad) 20%, transparent);
}
.ns-tag--info {
  background: var(--ns-info-soft);
  color: var(--ns-info);
  border-color: color-mix(in srgb, var(--ns-info) 20%, transparent);
}
.ns-tag--gold {
  background: var(--ns-gold-soft);
  color: var(--ns-gold);
  border-color: color-mix(in srgb, var(--ns-gold) 22%, transparent);
}
.ns-tag__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  flex: none;
}
</style>

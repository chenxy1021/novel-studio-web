<script setup lang="ts">
withDefaults(defineProps<{ label: string; value: string | number; unit?: string; note?: string; tone?: 'plain' | 'pink' | 'gold' }>(), {
  unit: '',
  note: '',
  tone: 'plain',
})
</script>

<template>
  <div class="stat" :class="`stat--${tone}`">
    <div class="stat__label">{{ label }}</div>
    <div class="stat__value ns-num">
      {{ value }}<small v-if="unit">{{ unit }}</small>
    </div>
    <div v-if="note" class="stat__note">{{ note }}</div>
  </div>
</template>

<style scoped>
.stat {
  display: grid;
  gap: 2px;
  padding: 13px 15px 14px;
  background: var(--ns-card);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  min-width: 0;
}
.stat--pink {
  background: var(--ns-pink-soft);
  border-color: var(--ns-pink-line);
}
.stat--gold {
  background: var(--ns-gold-soft);
  border-color: color-mix(in srgb, var(--ns-gold) 22%, transparent);
}
.stat__label {
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
  font-weight: 600;
  letter-spacing: 0.02em;
}
.stat__value {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-28);
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -0.01em;
}
.stat__value small {
  font-family: var(--ns-sans);
  font-size: var(--ns-fs-12);
  font-weight: 500;
  color: var(--ns-ink-3);
  margin-left: 3px;
}
.stat__note {
  font-size: 11.5px;
  color: var(--ns-ink-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>

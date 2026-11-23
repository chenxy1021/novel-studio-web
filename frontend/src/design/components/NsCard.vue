<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string
    eyebrow?: string
    desc?: string
    flush?: boolean
    tone?: 'plain' | 'paper' | 'pink' | 'warn'
  }>(),
  { title: '', eyebrow: '', desc: '', flush: false, tone: 'plain' },
)
</script>

<template>
  <section class="ns-card" :class="[`ns-card--${tone}`, { 'ns-card--flush': flush }]">
    <header v-if="title || eyebrow || desc || $slots.actions" class="ns-card__head">
      <div class="ns-card__titles">
        <div v-if="eyebrow" class="ns-eyebrow">{{ eyebrow }}</div>
        <h3 v-if="title">{{ title }}</h3>
        <p v-if="desc" class="ns-card__desc">{{ desc }}</p>
      </div>
      <div v-if="$slots.actions" class="ns-card__actions"><slot name="actions" /></div>
    </header>
    <div class="ns-card__body" :class="{ 'ns-card__body--tight': flush }"><slot /></div>
    <footer v-if="$slots.footer" class="ns-card__foot"><slot name="footer" /></footer>
  </section>
</template>

<style scoped>
.ns-card {
  background: var(--ns-card);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-lg);
  box-shadow: var(--ns-shadow-1);
  overflow: hidden;
}
.ns-card--paper {
  background: var(--ns-paper-2);
}
.ns-card--pink {
  background: var(--ns-pink-soft);
  border-color: var(--ns-pink-line);
}
.ns-card--warn {
  background: var(--ns-warn-soft);
  border-color: color-mix(in srgb, var(--ns-warn) 30%, transparent);
}
.ns-card__head {
  display: flex;
  align-items: flex-start;
  gap: var(--ns-s4);
  padding: var(--ns-s4) var(--ns-s5) 0;
}
.ns-card--flush .ns-card__head {
  padding-bottom: 0;
}
.ns-card__titles {
  min-width: 0;
  flex: 1;
}
.ns-card h3 {
  margin: 2px 0 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
  font-weight: 700;
  letter-spacing: 0.01em;
  line-height: var(--ns-lh-tight);
}
.ns-card__desc {
  margin: 5px 0 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
  line-height: 1.6;
  max-width: 62ch;
}
.ns-card__actions {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
}
.ns-card__body {
  padding: var(--ns-s4) var(--ns-s5) var(--ns-s5);
}
.ns-card__body--tight {
  padding: 0;
}
.ns-card__foot {
  border-top: 1px solid var(--ns-line);
  background: var(--ns-card-2);
  padding: var(--ns-s3) var(--ns-s5);
  display: flex;
  align-items: center;
  gap: var(--ns-s3);
  flex-wrap: wrap;
}
</style>

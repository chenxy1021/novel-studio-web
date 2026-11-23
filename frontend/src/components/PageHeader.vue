<script setup lang="ts">
withDefaults(defineProps<{ eyebrow?: string; title: string; desc?: string; chip?: string }>(), {
  eyebrow: '',
  desc: '',
  chip: '',
})
</script>

<template>
  <header class="ph">
    <div class="ph__text">
      <div v-if="eyebrow" class="ns-eyebrow">{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <p v-if="desc">{{ desc }}</p>
    </div>
    <div class="ph__side">
      <slot />
    </div>
  </header>
</template>

<style scoped>
.ph {
  display: flex;
  align-items: flex-end;
  gap: var(--ns-s6);
  margin-bottom: var(--ns-s6);
  flex-wrap: wrap;
}
.ph__text {
  min-width: 0;
  flex: 1;
}
.ph h1 {
  margin: 3px 0 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-28);
  font-weight: 700;
  letter-spacing: 0.01em;
  line-height: 1.25;
}
.ph p {
  margin: 7px 0 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-13);
  max-width: 62ch;
  line-height: 1.7;
}
.ph__side {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  flex-wrap: wrap;
}
</style>

<script setup lang="ts">
defineProps<{ ok: boolean; label: string }>()
</script>

<template>
  <span class="rule" :class="{ 'rule--ok': ok }">
    <i>{{ ok ? '✓' : '·' }}</i>{{ label }}
  </span>
</template>

<style scoped>
.rule {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: var(--ns-ink-3);
}
.rule i {
  width: 16px;
  height: 16px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  border: 1px solid var(--ns-line-2);
  font-style: normal;
  font-size: 10px;
}
.rule--ok {
  color: var(--ns-ink-2);
}
.rule--ok i {
  background: var(--ns-ok-soft);
  border-color: transparent;
  color: var(--ns-ok);
  font-weight: 700;
}
</style>

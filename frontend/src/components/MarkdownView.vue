<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '@/lib/markdown'

const props = withDefaults(
  defineProps<{ source: string; empty?: string; maxHeight?: string }>(),
  { empty: '（还没有内容）', maxHeight: '' },
)
const html = computed(() => renderMarkdown(props.source))
</script>

<template>
  <div
    v-if="source.trim()"
    class="md"
    :style="maxHeight ? { maxHeight, overflow: 'auto' } : undefined"
    v-html="html"
  />
  <p v-else class="md md--empty">{{ empty }}</p>
</template>

<style scoped>
.md {
  color: var(--ns-ink-2);
  font-family: var(--ns-serif);
  font-size: 14.5px;
  line-height: 1.95;
  word-break: break-word;
}
.md--empty {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: 12.5px;
}
.md :deep(h1),
.md :deep(h2),
.md :deep(h3),
.md :deep(h4),
.md :deep(h5),
.md :deep(h6) {
  font-family: var(--ns-serif);
  color: var(--ns-ink);
  line-height: 1.45;
  scroll-margin-top: 88px;
  margin: 1.5em 0 0.5em;
}
.md :deep(h1) {
  font-size: 21px;
}
.md :deep(h2) {
  font-size: 18px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--ns-line);
}
.md :deep(h3) {
  font-size: 15.5px;
}
.md :deep(h4) {
  font-size: 14px;
  color: var(--ns-ink-2);
}
.md :deep(h1:first-child),
.md :deep(h2:first-child),
.md :deep(h3:first-child) {
  margin-top: 0;
}
.md :deep(p) {
  margin: 0.65em 0;
}
.md :deep(strong) {
  color: var(--ns-ink);
  font-weight: 700;
}
.md :deep(em) {
  color: var(--ns-ink-2);
}
.md :deep(a) {
  color: var(--ns-pink-2);
  text-underline-offset: 3px;
}
.md :deep(ul),
.md :deep(ol) {
  margin: 0.5em 0;
  padding-left: 1.5em;
}
.md :deep(li) {
  margin: 0.22em 0;
}
.md :deep(li > ul),
.md :deep(li > ol) {
  margin: 0.15em 0;
}
.md :deep(blockquote) {
  margin: 0.8em 0;
  padding: 8px 12px;
  border-left: 3px solid var(--ns-pink-line);
  background: var(--ns-card-2);
  border-radius: 0 var(--ns-r-sm) var(--ns-r-sm) 0;
  color: var(--ns-ink-3);
  font-size: 13.5px;
}
.md :deep(code) {
  font-family: var(--ns-mono);
  font-size: 0.86em;
  background: var(--ns-card-2);
  border: 1px solid var(--ns-line);
  border-radius: 3px;
  padding: 0 4px;
}
.md :deep(pre) {
  margin: 0.8em 0;
  padding: 10px 12px;
  background: var(--ns-card-2);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  overflow: auto;
  font-size: 12px;
  line-height: 1.6;
}
.md :deep(pre code) {
  border: 0;
  background: transparent;
  padding: 0;
}
.md :deep(hr) {
  border: 0;
  border-top: 1px dashed var(--ns-line);
  margin: 1.2em 0;
}
.md :deep(.md-table) {
  margin: 0.8em 0;
  overflow-x: auto;
}
.md :deep(table) {
  border-collapse: collapse;
  width: 100%;
  font-family: var(--ns-sans);
  font-size: 12.5px;
  line-height: 1.6;
}
.md :deep(th),
.md :deep(td) {
  border: 1px solid var(--ns-line);
  padding: 5px 9px;
  text-align: left;
  vertical-align: top;
}
.md :deep(th) {
  background: var(--ns-card-2);
  color: var(--ns-ink);
  font-weight: 600;
  white-space: nowrap;
}
.md :deep(del) {
  color: var(--ns-ink-3);
}
</style>

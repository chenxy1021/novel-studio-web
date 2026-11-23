<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { TABS } from '@/router'
import { useStudio } from '@/stores/studio'

const studio = useStudio()
const route = useRoute()
const tab = computed(() => TABS.find((t) => t.name === route.name) ?? TABS[0])

const gateTone = computed(() =>
  studio.book.gate.phase === 'awaiting_review' ? 'pink' : studio.book.gate.phase === 'writing' ? 'ok' : 'neutral',
)
const gateLabel = computed(() =>
  studio.book.gate.phase === 'awaiting_review' ? '待确认' : studio.book.gate.phase === 'writing' ? '写作中' : '筹备中',
)
const today = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' }).format(new Date())
</script>

<template>
  <header class="top">
    <div class="top__crumb">
      <span class="top__book">{{ studio.book.title }}</span>
      <span class="top__slash">/</span>
      <b>{{ tab.label }}</b>
      <span class="top__hint">{{ tab.hint }}</span>
    </div>
    <div class="top__right">
      <span class="top__gate">
        <i class="top__gate-dot" :class="`top__gate-dot--${gateTone}`" />
        {{ gateLabel }} · 第 {{ studio.book.gate.chapter }} 章
        <span class="top__gate-reason">{{ studio.book.gate.reason }}</span>
      </span>
      <span class="top__date ns-num">{{ today }}</span>
      <button type="button" class="top__cmd" title="命令面板（占位）">⌘ K</button>
    </div>
  </header>
</template>

<style scoped>
.top {
  height: var(--ns-topbar-h);
  flex: none;
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 24px;
  border-bottom: 1px solid var(--ns-line);
  background: color-mix(in srgb, var(--ns-paper) 88%, transparent);
  backdrop-filter: blur(10px);
}
.top__crumb {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.top__book {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.top__slash {
  color: var(--ns-ink-4);
}
.top__crumb b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
  white-space: nowrap;
}
.top__hint {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.top__right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.top__gate {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 10px;
  border-radius: var(--ns-r-pill);
  border: 1px solid var(--ns-line);
  background: var(--ns-card);
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
  max-width: 460px;
}
.top__gate-reason {
  color: var(--ns-ink-3);
  font-weight: 400;
  overflow: hidden;
  text-overflow: ellipsis;
}
.top__gate-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
}
.top__gate-dot--ok {
  background: var(--ns-ok);
}
.top__gate-dot--pink {
  background: var(--ns-pink);
}
.top__gate-dot--neutral {
  background: var(--ns-ink-4);
}
.top__date {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
  white-space: nowrap;
}
.top__cmd {
  border: 1px solid var(--ns-line-2);
  background: var(--ns-card);
  border-radius: var(--ns-r-sm);
  color: var(--ns-ink-3);
  font-family: var(--ns-mono);
  font-size: 11px;
  height: 24px;
  padding: 0 7px;
  cursor: pointer;
}
.top__cmd:hover {
  color: var(--ns-ink);
}
@media (max-width: 960px) {
  .top__hint,
  .top__gate-reason,
  .top__date {
    display: none;
  }
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { tabOf } from '@/router'
import { useStudio } from '@/stores/studio'
import { usePrefs } from '@/stores/prefs'

const studio = useStudio()
const prefs = usePrefs()
const route = useRoute()
const router = useRouter()
const tab = computed(() => tabOf(route.name) ?? tabOf('overview')!)

const MOD = /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent) ? '⌘' : 'Ctrl'

const gateTone = computed(() =>
  studio.book.gate.phase === 'awaiting_review' ? 'pink' : studio.book.gate.phase === 'writing' ? 'ok' : 'muted',
)
const gateLabel = computed(() =>
  studio.book.gate.phase === 'awaiting_review' ? '待确认' : studio.book.gate.phase === 'writing' ? '写作中' : '筹备中',
)
const today = new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' }).format(new Date())

function openProgress() {
  router.push({ name: 'progress' })
}
</script>

<template>
  <header class="top">
    <div class="top__crumb">
      <span class="top__book">{{ studio.book.title }}</span>
      <span class="top__slash" aria-hidden="true">/</span>
      <span class="top__group">{{ tab.group }}</span>
      <span class="top__slash" aria-hidden="true">/</span>
      <b>{{ tab.label }}</b>
      <span class="top__hint">{{ tab.hint }}</span>
    </div>

    <div class="top__right">
      <button type="button" class="top__search" aria-label="打开命令面板" @click="prefs.openPalette()">
        <span class="top__searchicon" aria-hidden="true">⌕</span>
        <span class="top__searchtext">搜索章节、人物、动作</span>
        <kbd class="ns-kbd">{{ MOD }}K</kbd>
      </button>

      <button
        type="button"
        class="top__gate"
        :title="`${gateLabel} · 第 ${studio.nextNumber} 章 — ${studio.book.gate.reason}（点击去进度页）`"
        @click="openProgress"
      >
        <i class="top__gate-dot" :class="`top__gate-dot--${gateTone}`" />
        <span class="top__gate-label">{{ gateLabel }} · 第 {{ studio.nextNumber }} 章</span>
        <span class="top__gate-reason">{{ studio.book.gate.reason }}</span>
      </button>

      <span class="top__date ns-num">{{ today }}</span>

      <button
        type="button"
        class="top__icon"
        :title="`主题：${prefs.themeLabel}（点击切换）`"
        :aria-label="`主题：${prefs.themeLabel}，点击切换`"
        @click="prefs.cycleTheme()"
      >
        {{ prefs.themeIcon }}
      </button>
      <button type="button" class="top__icon" title="键盘快捷键（?）" aria-label="键盘快捷键" @click="prefs.openHelp()">
        ?
      </button>
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
  padding: 0 20px 0 24px;
  border-bottom: 1px solid var(--ns-line);
  background: color-mix(in srgb, var(--ns-paper) 86%, transparent);
  backdrop-filter: blur(10px);
  z-index: var(--ns-z-top);
}
.top__crumb {
  display: flex;
  align-items: baseline;
  gap: 7px;
  min-width: 0;
  flex: 1;
}
.top__book {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 22ch;
}
.top__slash {
  color: var(--ns-ink-4);
}
.top__group {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
  white-space: nowrap;
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
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.top__search {
  display: flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  padding: 0 6px 0 10px;
  min-width: 210px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink-3);
  font: inherit;
  font-size: var(--ns-fs-12);
  cursor: pointer;
  transition: border-color 0.14s ease, color 0.14s ease, background 0.14s ease;
}
.top__search:hover {
  border-color: var(--ns-line-2);
  color: var(--ns-ink-2);
  background: var(--ns-hover);
}
.top__searchicon {
  font-size: 14px;
  line-height: 1;
  color: var(--ns-ink-4);
}
.top__searchtext {
  flex: 1;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.top__gate {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 10px;
  border-radius: var(--ns-r-pill);
  border: 1px solid var(--ns-line);
  background: var(--ns-card);
  font: inherit;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
  color: var(--ns-ink);
  cursor: pointer;
  max-width: 380px;
}
.top__gate:hover {
  border-color: var(--ns-line-2);
  background: var(--ns-hover);
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
.top__gate-dot--muted {
  background: var(--ns-ink-4);
}
.top__date {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
  white-space: nowrap;
}
.top__icon {
  width: 28px;
  height: 28px;
  flex: none;
  display: grid;
  place-items: center;
  border: 1px solid transparent;
  border-radius: var(--ns-r-sm);
  background: transparent;
  color: var(--ns-ink-3);
  font-size: 14px;
  font-family: var(--ns-mono);
  cursor: pointer;
}
.top__icon:hover {
  background: var(--ns-card);
  border-color: var(--ns-line);
  color: var(--ns-ink);
}
@media (max-width: 1180px) {
  .top__search {
    min-width: 0;
  }
  .top__searchtext {
    display: none;
  }
}
@media (max-width: 960px) {
  .top__hint,
  .top__gate-reason,
  .top__date,
  .top__group,
  .top__book + .top__slash {
    display: none;
  }
}
@media (max-width: 720px) {
  .top {
    padding: 0 12px;
    gap: 8px;
  }
  .top__search {
    padding: 0 6px;
  }
  .top__search .ns-kbd {
    display: none;
  }
}
</style>

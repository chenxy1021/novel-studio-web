<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { TABS } from '@/router'
import { useStudio } from '@/stores/studio'
import { pct } from '@/lib/format'
import { SHELF } from '@/mocks'

const studio = useStudio()
const route = useRoute()
const openSwitcher = ref(false)

const progress = computed(() => pct(studio.approved.length, studio.book.targetChapters))

const flags = computed<Record<string, number>>(() => ({
  foreshadow: studio.foreshadows.filter((f) => f.status === 'open' && f.overdue).length,
  progress: studio.pending.length,
  discarded: studio.data.discarded.length,
}))
</script>

<template>
  <aside class="rail">
    <div class="rail__brand">
      <div class="rail__mark" aria-hidden="true">墨</div>
      <div class="rail__brandtext">
        <b>Novel Studio</b>
        <span>长篇小说工作台</span>
      </div>
    </div>

    <div class="rail__bookwrap">
      <button type="button" class="rail__book" :aria-expanded="openSwitcher" @click="openSwitcher = !openSwitcher">
        <span class="rail__bookname">{{ studio.book.title }}</span>
        <span class="rail__bookmeta">{{ studio.approved.length }}/{{ studio.book.targetChapters }} 章 · {{ studio.book.genre.split(' · ')[0] }}</span>
        <span class="rail__bar"><i :style="{ width: `${progress}%` }" /></span>
        <span class="rail__caret" :class="{ 'rail__caret--up': openSwitcher }">⌄</span>
      </button>
      <Transition name="drop">
        <div v-if="openSwitcher" class="rail__switcher">
          <div class="ns-eyebrow">书架</div>
          <button
            v-for="b in SHELF"
            :key="b.key"
            type="button"
            class="rail__switcheritem"
            :class="{ on: studio.key === b.key }"
            @click="studio.key = b.key; openSwitcher = false"
          >
            <span>{{ b.title }}</span>
            <small>{{ b.done }} / {{ b.target }} 章</small>
          </button>
          <div class="rail__switchdivider" />
          <div class="rail__switchfoot">目录：<code>~/Desktop/mine/xiaoshuo</code>（假数据）</div>
        </div>
      </Transition>
    </div>

    <nav class="rail__nav" aria-label="工作台页签">
      <RouterLink
        v-for="tab in TABS"
        :key="tab.name"
        :to="{ name: tab.name }"
        class="rail__item"
        :class="{ on: route.name === tab.name }"
        :title="tab.hint"
      >
        <span class="rail__glyph" aria-hidden="true">{{ tab.glyph }}</span>
        <span class="rail__label">{{ tab.label }}</span>
        <span v-if="flags[tab.name]" class="rail__badge" :class="`rail__badge--${tab.name}`">{{ flags[tab.name] }}</span>
      </RouterLink>
    </nav>

    <div class="rail__foot">
      <div class="rail__streak">
        <b>{{ studio.streak }}</b>
        <span>连续写作<br />天</span>
      </div>
      <div class="rail__streak">
        <b>{{ (studio.wordsToday / 1000).toFixed(1) }}k</b>
        <span>今日<br />字数</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.rail {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 18px 12px 14px;
  background: var(--ns-paper-2);
  border-right: 1px solid var(--ns-line);
}
.rail__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 8px 16px;
}
.rail__mark {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: var(--ns-r-sm);
  background: var(--ns-ink);
  color: var(--ns-paper);
  font-family: var(--ns-serif);
  font-size: 17px;
}
.rail__brandtext {
  display: grid;
  line-height: 1.25;
}
.rail__brandtext b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  letter-spacing: 0.02em;
}
.rail__brandtext span {
  color: var(--ns-ink-3);
  font-size: 10.5px;
  letter-spacing: 0.04em;
}
.rail__bookwrap {
  position: relative;
  margin: 0 4px 14px;
}
.rail__book {
  width: 100%;
  text-align: left;
  border: 1px solid var(--ns-line);
  background: var(--ns-card);
  border-radius: var(--ns-r-md);
  padding: 10px 12px 11px;
  cursor: pointer;
  display: grid;
  gap: 3px;
  font: inherit;
  color: inherit;
  box-shadow: var(--ns-shadow-1);
}
.rail__book:hover {
  border-color: var(--ns-line-2);
}
.rail__bookname {
  font-family: var(--ns-serif);
  font-weight: 700;
  font-size: var(--ns-fs-14);
  padding-right: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rail__bookmeta {
  font-size: 10.5px;
  color: var(--ns-ink-3);
}
.rail__bar {
  display: block;
  height: 3px;
  border-radius: var(--ns-r-pill);
  background: var(--ns-card-2);
  margin-top: 5px;
  overflow: hidden;
}
.rail__bar i {
  display: block;
  height: 100%;
  background: var(--ns-pink);
  border-radius: inherit;
}
.rail__caret {
  position: absolute;
  right: 10px;
  top: 9px;
  color: var(--ns-ink-3);
  font-size: 12px;
  transition: transform 0.15s ease;
}
.rail__caret--up {
  transform: rotate(180deg);
}
.rail__switcher {
  position: absolute;
  left: 0;
  right: 0;
  top: calc(100% + 6px);
  z-index: 20;
  background: var(--ns-card);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  box-shadow: var(--ns-shadow-2);
  padding: 8px;
}
.rail__switcher .ns-eyebrow {
  padding: 2px 6px 6px;
}
.rail__switcheritem {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  padding: 7px 8px;
  border: 0;
  border-radius: var(--ns-r-sm);
  background: transparent;
  font: inherit;
  color: inherit;
  cursor: pointer;
  text-align: left;
}
.rail__switcheritem:hover {
  background: var(--ns-card-2);
}
.rail__switcheritem.on {
  background: var(--ns-pink-soft);
}
.rail__switcheritem small {
  color: var(--ns-ink-3);
  font-size: 10.5px;
  flex: none;
}
.rail__switchdivider {
  height: 1px;
  background: var(--ns-line);
  margin: 6px 0;
}
.rail__switchfoot {
  font-size: 10px;
  color: var(--ns-ink-3);
  padding: 0 6px 2px;
  line-height: 1.6;
}
.rail__switchfoot code {
  font-family: var(--ns-mono);
}
.rail__nav {
  display: grid;
  gap: 1px;
  overflow: auto;
  min-height: 0;
}
.rail__item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-radius: var(--ns-r-sm);
  color: var(--ns-ink-2);
  text-decoration: none;
  font-size: var(--ns-fs-13);
  transition: background 0.12s ease, color 0.12s ease;
}
.rail__item:hover {
  background: var(--ns-card-2);
  color: var(--ns-ink);
}
.rail__item.on {
  background: var(--ns-card);
  color: var(--ns-ink);
  font-weight: 600;
  box-shadow: var(--ns-shadow-1);
}
.rail__item.on::before {
  content: '';
  position: absolute;
  left: -12px;
  top: 7px;
  bottom: 7px;
  width: 2px;
  border-radius: 0 2px 2px 0;
  background: var(--ns-pink);
}
.rail__glyph {
  width: 18px;
  text-align: center;
  color: var(--ns-ink-3);
  font-family: var(--ns-serif);
  font-size: 13px;
}
.rail__item.on .rail__glyph {
  color: var(--ns-pink);
}
.rail__label {
  flex: 1;
}
.rail__badge {
  min-width: 18px;
  height: 17px;
  padding: 0 5px;
  display: grid;
  place-items: center;
  border-radius: var(--ns-r-pill);
  font-size: 10px;
  font-weight: 700;
  background: var(--ns-card-2);
  color: var(--ns-ink-3);
}
.rail__badge--progress {
  background: var(--ns-pink);
  color: #fff;
}
.rail__badge--foreshadow {
  background: var(--ns-warn-soft);
  color: var(--ns-warn);
}
.rail__foot {
  margin-top: auto;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 14px 4px 0;
}
.rail__streak {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 10px;
  border-radius: var(--ns-r-sm);
  background: color-mix(in srgb, var(--ns-card) 70%, transparent);
  border: 1px solid var(--ns-line);
}
.rail__streak b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
  line-height: 1;
}
.rail__streak span {
  font-size: 10px;
  color: var(--ns-ink-3);
  line-height: 1.3;
}
.drop-enter-active,
.drop-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.drop-enter-from,
.drop-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
@media (max-width: 820px) {
  .rail {
    flex-direction: row;
    align-items: center;
    overflow-x: auto;
    padding: 8px;
    border-right: 0;
    border-bottom: 1px solid var(--ns-line);
  }
  .rail__brandtext,
  .rail__bookwrap,
  .rail__foot {
    display: none;
  }
  .rail__nav {
    display: flex;
  }
  .rail__item {
    white-space: nowrap;
  }
  .rail__item.on::before {
    display: none;
  }
}
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { TABS, tabOf } from '@/router'
import { useStudio } from '@/stores/studio'
import { usePrefs } from '@/stores/prefs'
import NavRail from './NavRail.vue'
import TopBar from './TopBar.vue'
import Toasts from './Toasts.vue'
import CommandPalette from './CommandPalette.vue'
import ShortcutsHelp from './ShortcutsHelp.vue'
import WritePanel from './WritePanel.vue'
import RunMiniBar from './RunMiniBar.vue'
import StartView from '@/views/StartView.vue'

const studio = useStudio()
const prefs = usePrefs()
const route = useRoute()
const router = useRouter()

const shellStyle = computed(() => ({
  '--rail-current': prefs.railCollapsed ? 'var(--ns-rail-w-collapsed)' : 'var(--ns-rail-w)',
}))

/** 在输入框里打字时不抢键。 */
function isTyping(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

let gPending = 0
const G_TIMEOUT = 1200

function onKeydown(e: KeyboardEvent) {
  const mod = e.metaKey || e.ctrlKey

  if (mod && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault()
    prefs.paletteOpen ? prefs.closePalette() : prefs.openPalette()
    return
  }

  if (prefs.paletteOpen || prefs.helpOpen) return
  if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return

  if (e.key === '?' || (e.key === '/' && e.shiftKey)) {
    e.preventDefault()
    prefs.openHelp()
    return
  }
  if (e.key === '/') {
    e.preventDefault()
    prefs.openPalette()
    return
  }
  if (e.key === 'T') {
    e.preventDefault()
    prefs.cycleTheme()
    studio.toast(`主题：${prefs.themeLabel}`, 'info')
    return
  }

  if (gPending) {
    const tab = TABS.find((t) => t.key === e.key.toLowerCase())
    window.clearTimeout(gPending)
    gPending = 0
    if (tab) {
      e.preventDefault()
      router.push({ name: tab.name })
    }
    return
  }
  if (e.key === 'g' || e.key === 'G') {
    gPending = window.setTimeout(() => (gPending = 0), G_TIMEOUT)
    return
  }

  // W：打开写面板。只在没有其他弹窗时生效；不抢 G 序列。
  if ((e.key === 'w' || e.key === 'W') && !e.shiftKey) {
    if (studio.writePanel.open) return
    if (document.querySelector('[aria-modal="true"]')) return
    e.preventDefault()
    studio.openWritePanel({ source: 'command' })
  }
}

// 每页一个标题，浏览器标签/历史记录里能分清
watch(
  () => route.name,
  (name) => {
    const tab = tabOf(name)
    document.title = tab ? `${studio.book.title} · ${tab.label} — Novel Studio` : 'Novel Studio · 小说工作台'
  },
  { immediate: true },
)
watch(
  () => studio.book.title,
  () => {
    const tab = tabOf(route.name)
    if (tab) document.title = `${studio.book.title} · ${tab.label} — Novel Studio`
  },
)

onMounted(() => {
  studio.init()
  window.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.clearTimeout(gPending)
})
</script>

<template>
  <StartView v-if="!studio.ready && studio.emptyShelf" />
  <div v-else-if="!studio.ready" class="boot">
    <div class="boot__card">
      <div class="boot__mark" aria-hidden="true">墨</div>
      <h1>{{ studio.loading ? '正在打开书稿…' : studio.error ? '打不开工作台' : '正在准备…' }}</h1>
      <p v-if="studio.error">{{ studio.error }}</p>
      <p v-else>从 <code>~/Desktop/mine/xiaoshuo</code> 读取你的书，存档状态直接落在书目录里。</p>
      <button v-if="studio.error" type="button" class="boot__retry" @click="studio.init()">重试</button>
    </div>
  </div>
  <div v-else class="shell" :style="shellStyle">
    <a class="ns-skip" href="#main">跳到正文区</a>
    <NavRail />
    <main id="main" class="shell__main">
      <TopBar />
      <div class="shell__page">
        <RouterView v-slot="{ Component }">
          <component :is="Component" :key="studio.key" />
        </RouterView>
      </div>
    </main>
    <Toasts />
    <WritePanel />
    <RunMiniBar />
    <CommandPalette />
    <ShortcutsHelp />
  </div>
</template>

<style scoped>
.boot {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
}
.boot__card {
  max-width: 460px;
  text-align: center;
  padding: 40px 32px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-lg);
  background: var(--ns-card);
  box-shadow: var(--ns-shadow);
}
.boot__mark {
  width: 46px;
  height: 46px;
  margin: 0 auto 18px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: var(--ns-ink);
  color: var(--ns-paper);
  font-family: var(--ns-font-display);
  font-size: 22px;
}
.boot h1 {
  margin: 0 0 10px;
  font-size: 20px;
}
.boot p {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: 14px;
  line-height: 1.7;
}
.boot__retry {
  margin-top: 18px;
  padding: 8px 18px;
  border-radius: 999px;
  border: 1px solid var(--ns-line);
  background: var(--ns-ink);
  color: var(--ns-paper);
  cursor: pointer;
}
.shell {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: var(--rail-current, var(--ns-rail-w)) minmax(0, 1fr);
  height: 100%;
  transition: grid-template-columns 0.16s ease;
}
.shell__main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.shell__page {
  flex: 1;
  min-height: 0;
  overflow: auto;
  scroll-behavior: smooth;
}
@media (max-width: 820px) {
  .shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto minmax(0, 1fr);
  }
}
</style>

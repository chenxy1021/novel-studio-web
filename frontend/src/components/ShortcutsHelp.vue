<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { TABS } from '@/router'
import { usePrefs } from '@/stores/prefs'

const prefs = usePrefs()
const MOD = /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent) ? '⌘' : 'Ctrl'

const navKeys = computed(() => TABS.map((t) => ({ label: t.label, key: `g ${t.key}` })))

const globalKeys = computed(() => [
  { keys: [MOD, 'K'], label: '打开命令面板' },
  { keys: ['/'], label: '打开命令面板（直接输入搜索）' },
  { keys: ['?'], label: '打开这张快捷键表' },
  { keys: ['T'], label: '切换主题：跟随系统 / 浅色 / 深色' },
  { keys: ['Esc'], label: '关闭当前浮层' },
])

const progressKeys = [
  { keys: ['J'], label: '下一章' },
  { keys: ['K'], label: '上一章' },
  { keys: ['↵'], label: '展开本章；待确认章直接存档' },
  { keys: ['R'], label: '退回当前章重写' },
  { keys: ['B'], label: '按批体检' },
]

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') prefs.helpOpen = false
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <Transition name="help">
      <div v-if="prefs.helpOpen" class="help" @click.self="prefs.helpOpen = false">
        <div class="help__panel" role="dialog" aria-modal="true" aria-label="键盘快捷键">
          <header class="help__head">
            <div>
              <span class="ns-eyebrow">键盘</span>
              <h2>不动鼠标也能走完一天</h2>
              <p>输入框、文本框里打字时不触发这些键。</p>
            </div>
            <button type="button" class="help__x" aria-label="关闭" @click="prefs.helpOpen = false">✕</button>
          </header>

          <div class="help__grid">
            <section>
              <h3>全局</h3>
              <ul>
                <li v-for="k in globalKeys" :key="k.label">
                  <span class="help__keys">
                    <kbd v-for="x in k.keys" :key="x" class="ns-kbd">{{ x }}</kbd>
                  </span>
                  <span>{{ k.label }}</span>
                </li>
              </ul>
            </section>

            <section>
              <h3>跳转 <span class="help__sub">先按 G</span></h3>
              <ul>
                <li v-for="k in navKeys" :key="k.key">
                  <span class="help__keys"><kbd class="ns-kbd">G</kbd><kbd class="ns-kbd">{{ k.key.slice(2) }}</kbd></span>
                  <span>{{ k.label }}</span>
                </li>
              </ul>
            </section>

            <section>
              <h3>进度页</h3>
              <ul>
                <li v-for="k in progressKeys" :key="k.label">
                  <span class="help__keys"><kbd v-for="x in k.keys" :key="x" class="ns-kbd">{{ x }}</kbd></span>
                  <span>{{ k.label }}</span>
                </li>
              </ul>
            </section>

            <section>
              <h3>不用记也行</h3>
              <p class="help__note">
                任何时候按 <kbd class="ns-kbd">{{ MOD }}K</kbd> 输入「存档」「第 12 章」「伏笔」，
                命令面板会把动作、页面、章节、人物一起搜出来。快捷键只是快一点的那条路。
              </p>
            </section>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.help {
  position: fixed;
  inset: 0;
  z-index: var(--ns-z-palette);
  display: grid;
  place-items: center;
  padding: 24px;
  background: color-mix(in srgb, var(--ns-ink) 26%, transparent);
  backdrop-filter: blur(3px);
}
.help__panel {
  width: min(760px, 100%);
  max-height: 84vh;
  overflow: auto;
  background: var(--ns-card);
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-lg);
  box-shadow: var(--ns-shadow-3);
}
.help__head {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  padding: 20px 24px 14px;
  border-bottom: 1px solid var(--ns-line);
}
.help__head > div {
  flex: 1;
}
.help__head h2 {
  margin: 3px 0 0;
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-18);
}
.help__head p {
  margin: 4px 0 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
}
.help__x {
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: var(--ns-r-sm);
  background: transparent;
  color: var(--ns-ink-3);
  cursor: pointer;
}
.help__x:hover {
  background: var(--ns-hover);
  color: var(--ns-ink);
}
.help__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px 28px;
  padding: 18px 24px 24px;
}
.help__grid h3 {
  margin: 0 0 8px;
  font-size: 11px;
  letter-spacing: 0.07em;
  color: var(--ns-ink-3);
  font-weight: 700;
}
.help__sub {
  font-weight: 400;
  letter-spacing: 0;
  color: var(--ns-ink-4);
}
.help__grid ul {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
}
.help__grid li {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-2);
}
.help__keys {
  display: inline-flex;
  gap: 3px;
  flex: none;
  min-width: 74px;
}
.help__note {
  margin: 0;
  font-size: var(--ns-fs-12);
  line-height: 1.8;
  color: var(--ns-ink-2);
}
.help__note .ns-kbd {
  vertical-align: 1px;
}
.help-enter-active,
.help-leave-active {
  transition: opacity 0.15s ease;
}
.help-enter-from,
.help-leave-to {
  opacity: 0;
}
@media (max-width: 640px) {
  .help__grid {
    grid-template-columns: 1fr;
  }
}
</style>

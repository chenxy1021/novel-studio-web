<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { TABS } from '@/router'
import { useStudio } from '@/stores/studio'
import { usePrefs } from '@/stores/prefs'

type Item = {
  id: string
  group: string
  title: string
  sub?: string
  glyph: string
  hint?: string
  run: () => void
}

const studio = useStudio()
const prefs = usePrefs()
const router = useRouter()

const q = ref('')
const active = ref(0)
const input = ref<HTMLInputElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

const MOD = /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent) ? '⌘' : 'Ctrl'

/** 关掉面板再执行，避免路由跳转后焦点留在已卸载的输入框里。 */
function close() {
  prefs.closePalette()
}
function run(fn: () => void) {
  close()
  nextTick(fn)
}

const actions = computed<Item[]>(() => {
  const list: Item[] = []
  const pending = studio.pending

  if (pending.length) {
    list.push({
      id: 'archive-pending',
      group: '动作',
      title: `存档全部待确认（${pending.length} 章）`,
      sub: `第 ${pending.map((c) => c.number).join('、')} 章`,
      glyph: '✓',
      run: () => run(() => studio.autoArchivePending()),
    })
  }
  list.push({
    id: 'batch-check',
    group: '动作',
    title: '按批体检本段',
    sub: studio.recentSegment ? `第 ${studio.recentSegment.from}–${studio.recentSegment.to} 章` : '逐章铺问题',
    glyph: '⚗',
    run: () =>
      run(() => {
        router.push({ name: 'progress' })
        studio.runBatchCheck()
      }),
  })
  list.push({
    id: 'plan-segment',
    group: '动作',
    title: `规划第 ${studio.nextNumber}–${studio.nextNumber + Math.max(3, studio.book.segmentSize || 10) - 1} 章`,
    sub: '打开段落纲，先看这一批的台阶',
    glyph: '✎',
    run: () => run(() => router.push({ name: 'detail' })),
  })
  list.push({
    id: 'memory-generate',
    group: '动作',
    title: '生成缺失记忆',
    sub: studio.memory?.coverage.missing.length
      ? `缺 ${studio.memory.coverage.missing.length} 章 · 逐章提炼`
      : '打开记忆页看看缺口',
    glyph: '◷',
    run: () =>
      run(() => {
        router.push({ name: 'memory' })
        void studio.generateMissingMemory({})
      }),
  })
  list.push({
    id: 'theme',
    group: '动作',
    title: `切换主题（当前：${prefs.themeLabel}）`,
    sub: '跟随系统 / 浅色 / 深色',
    glyph: prefs.themeIcon,
    run: () => run(() => prefs.cycleTheme()),
  })
  list.push({
    id: 'rail',
    group: '动作',
    title: prefs.railCollapsed ? '展开侧栏' : '收起侧栏',
    sub: '收起后正文区更宽',
    glyph: '▤',
    run: () => run(() => prefs.toggleRail()),
  })
  list.push({
    id: 'help',
    group: '动作',
    title: '键盘快捷键',
    sub: '? 打开同一张表',
    glyph: '?',
    run: () => run(() => prefs.openHelp()),
  })
  return list
})

const navItems = computed<Item[]>(() =>
  TABS.map((t) => ({
    id: `nav-${t.name}`,
    group: '页面',
    title: t.label,
    sub: t.hint,
    glyph: t.glyph,
    hint: `g ${t.key}`,
    run: () => run(() => router.push({ name: t.name })),
  })),
)

const chapterItems = computed<Item[]>(() =>
  studio.sortedChapters.map((c) => ({
    id: `ch-${c.number}`,
    group: '章节',
    title: `第 ${c.number} 章 · ${c.title}`,
    sub: c.approved ? `${c.chars} 字 · 已存档` : '待确认',
    glyph: String(c.number).padStart(3, '0').slice(-2),
    run: () => run(() => router.push({ name: 'progress', query: { chapter: String(c.number) } })),
  })),
)

const characterItems = computed<Item[]>(() =>
  studio.data.characters.map((c) => ({
    id: `person-${c.name}`,
    group: '人物',
    title: c.name,
    sub: `${c.role} · ${c.identity}`,
    glyph: c.name.slice(0, 1),
    run: () => run(() => router.push({ name: 'characters', query: { name: c.name } })),
  })),
)

const foreshadowItems = computed<Item[]>(() =>
  studio.foreshadows
    .filter((f) => f.status === 'open')
    .map((f) => ({
      id: `fs-${f.id}`,
      group: '伏笔',
      title: f.name,
      sub: f.dueChapter ? `第 ${f.dueChapter} 章该收${f.overdue ? ' · 已超期' : ''}` : '未定回收章',
      glyph: '◇',
      run: () => run(() => router.push({ name: 'foreshadow' })),
    })),
)

const bookItems = computed<Item[]>(() =>
  studio.shelf.filter((b) => b.dir !== studio.key).map((b) => ({
    id: `book-${b.dir}`,
    group: '切换书',
    title: b.title,
    sub: `${b.genre} · ${b.chapterCount}/${b.targetChapters} 章`,
    glyph: '书',
    run: () => run(() => studio.openBook(b.dir)),
  })),
)

function normalize(s: string) {
  return s.toLowerCase().replace(/\s+/g, '')
}

const results = computed<Item[]>(() => {
  const kw = normalize(q.value)
  const pool = [...actions.value, ...navItems.value, ...chapterItems.value, ...characterItems.value, ...foreshadowItems.value, ...bookItems.value]
  const filtered = kw ? pool.filter((i) => normalize(`${i.title}${i.sub ?? ''}${i.group}`).includes(kw)) : pool
  // 结果里每个分组最多 6 条，避免章节/人物把页面入口挤下去
  const seen = new Map<string, number>()
  return filtered.filter((i) => {
    const n = (seen.get(i.group) ?? 0) + 1
    seen.set(i.group, n)
    return kw ? n <= 8 : n <= (i.group === '动作' || i.group === '页面' ? 99 : 4)
  })
})

const grouped = computed(() => {
  const out: Array<{ name: string; items: Array<Item & { index: number }> }> = []
  results.value.forEach((item, index) => {
    let g = out.find((x) => x.name === item.group)
    if (!g) {
      g = { name: item.group, items: [] }
      out.push(g)
    }
    g.items.push({ ...item, index })
  })
  return out
})

watch(q, () => (active.value = 0))
watch(
  () => prefs.paletteOpen,
  async (open) => {
    if (!open) return
    q.value = ''
    active.value = 0
    await nextTick()
    input.value?.focus()
  },
)

function move(delta: number) {
  if (!results.value.length) return
  active.value = (active.value + delta + results.value.length) % results.value.length
  nextTick(() => {
    listEl.value?.querySelector<HTMLElement>('.pal__item--active')?.scrollIntoView({ block: 'nearest' })
  })
}

function choose() {
  const item = results.value[active.value]
  if (item) item.run()
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    move(1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    move(-1)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    choose()
  } else if (e.key === 'Escape') {
    e.preventDefault()
    close()
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="pal">
      <div v-if="prefs.paletteOpen" class="pal" role="presentation" @click.self="close">
        <div class="pal__panel" role="dialog" aria-modal="true" aria-label="命令面板">
          <div class="pal__bar">
            <span class="pal__icon" aria-hidden="true">⌕</span>
            <input
              ref="input"
              v-model="q"
              class="pal__input"
              type="text"
              role="combobox"
              aria-expanded="true"
              aria-controls="pal-list"
              aria-autocomplete="list"
              placeholder="跳到页面、找章节/人物，或直接执行一个动作…"
              spellcheck="false"
              @keydown="onKey"
            />
            <kbd class="ns-kbd">Esc</kbd>
          </div>

          <div id="pal-list" ref="listEl" class="pal__list" role="listbox">
            <template v-if="results.length">
              <div v-for="g in grouped" :key="g.name" class="pal__group">
                <div class="pal__groupname">{{ g.name }}</div>
                <button
                  v-for="item in g.items"
                  :key="item.id"
                  type="button"
                  role="option"
                  class="pal__item"
                  :class="{ 'pal__item--active': item.index === active }"
                  :aria-selected="item.index === active"
                  @mousemove="active = item.index"
                  @click="item.run()"
                >
                  <span class="pal__glyph" aria-hidden="true">{{ item.glyph }}</span>
                  <span class="pal__text">
                    <span class="pal__title">{{ item.title }}</span>
                    <span v-if="item.sub" class="pal__sub">{{ item.sub }}</span>
                  </span>
                  <kbd v-if="item.hint" class="ns-kbd">{{ item.hint }}</kbd>
                </button>
              </div>
            </template>
            <div v-else class="pal__empty">
              <b>没有匹配的结果</b>
              <span>试试「存档」「伏笔」「第 12 章」或人物名字。</span>
            </div>
          </div>

          <footer class="pal__foot">
            <span><kbd class="ns-kbd">↑</kbd><kbd class="ns-kbd">↓</kbd> 选择</span>
            <span><kbd class="ns-kbd">↵</kbd> 执行</span>
            <span><kbd class="ns-kbd">Esc</kbd> 关闭</span>
            <span class="pal__footspacer" />
            <span>{{ MOD }}K 随时打开</span>
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.pal {
  position: fixed;
  inset: 0;
  z-index: var(--ns-z-palette);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 10vh 20px 20px;
  background: color-mix(in srgb, var(--ns-ink) 26%, transparent);
  backdrop-filter: blur(3px);
}
.pal__panel {
  width: min(640px, 100%);
  max-height: 76vh;
  display: flex;
  flex-direction: column;
  background: var(--ns-card);
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-lg);
  box-shadow: var(--ns-shadow-3);
  overflow: hidden;
}
.pal__bar {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--ns-line);
}
.pal__icon {
  color: var(--ns-ink-4);
  font-size: 17px;
  line-height: 1;
}
.pal__input {
  flex: 1;
  min-width: 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--ns-ink);
  font: inherit;
  font-size: var(--ns-fs-14);
  line-height: 1.6;
}
.pal__input::placeholder {
  color: var(--ns-ink-4);
}
.pal__list {
  overflow: auto;
  padding: 6px 6px 8px;
  min-height: 0;
}
.pal__groupname {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 8px 10px 4px;
  background: var(--ns-card);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.09em;
  color: var(--ns-ink-4);
}
.pal__item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 0;
  border-radius: var(--ns-r-sm);
  background: transparent;
  color: var(--ns-ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.pal__item--active {
  background: var(--ns-pink-soft);
}
.pal__glyph {
  width: 26px;
  height: 26px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: var(--ns-r-xs);
  background: var(--ns-card-2);
  border: 1px solid var(--ns-line);
  color: var(--ns-ink-3);
  font-family: var(--ns-serif);
  font-size: 12px;
  overflow: hidden;
}
.pal__item--active .pal__glyph {
  background: var(--ns-card);
  border-color: var(--ns-pink-line);
  color: var(--ns-pink-2);
}
.pal__text {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 1px;
}
.pal__title {
  font-size: var(--ns-fs-13);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pal__sub {
  font-size: 11px;
  color: var(--ns-ink-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pal__empty {
  display: grid;
  gap: 4px;
  padding: 26px 14px;
  text-align: center;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
}
.pal__empty b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  color: var(--ns-ink);
}
.pal__foot {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 12px;
  padding: 8px 14px;
  border-top: 1px solid var(--ns-line);
  background: var(--ns-card-2);
  font-size: 10.5px;
  color: var(--ns-ink-3);
}
.pal__foot > span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.pal__footspacer {
  flex: 1;
}
.pal-enter-active,
.pal-leave-active {
  transition: opacity 0.14s ease;
}
.pal-enter-active .pal__panel,
.pal-leave-active .pal__panel {
  transition: transform 0.16s ease;
}
.pal-enter-from,
.pal-leave-to {
  opacity: 0;
}
.pal-enter-from .pal__panel,
.pal-leave-to .pal__panel {
  transform: translateY(-6px) scale(0.995);
}
</style>

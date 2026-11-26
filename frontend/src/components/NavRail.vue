<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Input, Modal } from '@/design'
import NewBookForm from './NewBookForm.vue'
import { TABS, TAB_GROUPS, type TabGroup } from '@/router'
import { useStudio } from '@/stores/studio'
import { usePrefs } from '@/stores/prefs'
import type { ShelfBook } from '@/api/studio'
import { pct } from '@/lib/format'

const studio = useStudio()
const prefs = usePrefs()
const route = useRoute()
const router = useRouter()
const openSwitcher = ref(false)

const deleteTarget = ref<ShelfBook | null>(null)
const deleteConfirm = ref('')
const deleting = ref(false)
const showNew = ref(false)

function onCreated() {
  showNew.value = false
  openSwitcher.value = false
  router.push({ name: 'workflow' })
}

function askDelete(b: ShelfBook) {
  openSwitcher.value = false
  deleteTarget.value = b
  deleteConfirm.value = ''
}

async function confirmDelete() {
  const target = deleteTarget.value
  if (!target || deleteConfirm.value.trim() !== target.title) return
  deleting.value = true
  try {
    await studio.deleteBook(target.dir)
    deleteTarget.value = null
  } catch (e) {
    studio.toast(`删除失败：${e instanceof Error ? e.message : String(e)}`, 'warn')
  } finally {
    deleting.value = false
  }
}

const progress = computed(() => pct(studio.approved.length, studio.book.targetChapters))

const flags = computed<Record<string, number>>(() => ({
  progress: studio.pending.length,
  foreshadow: studio.foreshadows.filter((f) => f.status === 'open' && f.overdue).length,
  discarded: studio.data.discarded.length,
}))

const groups = computed(() =>
  TAB_GROUPS.map((label: TabGroup) => ({
    label,
    tabs: TABS.filter((t) => t.group === label),
  })).filter((g) => g.tabs.length),
)

const gateLabel = computed(() =>
  studio.book.gate.phase === 'awaiting_review' ? '待确认' : studio.book.gate.phase === 'writing' ? '写作中' : '筹备中',
)
const gateTone = computed(() =>
  studio.book.gate.phase === 'awaiting_review' ? 'pink' : studio.book.gate.phase === 'writing' ? 'ok' : 'muted',
)

/** 侧栏底部只留一个「下一步」：待确认优先，其次到期伏笔，最后才是规划下一段。 */
const nextAction = computed(() => {
  if (!studio.book.outlineText) {
    return { label: '生成大纲 + 世界观', hint: '开书流程第 1 步', to: 'workflow' as const, tone: 'pink' as const }
  }
  if (!studio.chapters.length) {
    const n = Math.max(3, studio.book.segmentSize || 10)
    return { label: `写第 1–${n} 章`, hint: '细纲 + 正文', to: 'workflow' as const, tone: 'pink' as const }
  }
  const pending = studio.pending
  if (pending.length) {
    return {
      label: `处理 ${pending.length} 章待确认`,
      hint: `第 ${pending.map((c) => c.number).join('、')} 章`,
      to: 'progress' as const,
      tone: 'pink' as const,
    }
  }
  const overdue = studio.foreshadows.filter((f) => f.status === 'open' && f.overdue)
  if (overdue.length) {
    return { label: `收 ${overdue.length} 条到期伏笔`, hint: overdue[0].name, to: 'foreshadow' as const, tone: 'warn' as const }
  }
  return {
    label: `规划第 ${studio.nextNumber}–${studio.nextNumber + Math.max(3, studio.book.segmentSize || 10) - 1} 章`,
    hint: '本段还没定台阶',
    to: 'detail' as const,
    tone: 'pink' as const,
  }
})

function goNext() {
  const first = studio.pending[0]
  if (first) {
    // 带章号进进度页：明确是去审这一章，不会触发自动存档
    router.push({ name: 'progress', query: { chapter: String(first.number) } })
    return
  }
  router.push({ name: nextAction.value.to })
}

function switchBook(dir: string) {
  studio.openBook(dir)
  openSwitcher.value = false
}
</script>

<template>
  <aside class="rail" :class="{ 'rail--collapsed': prefs.railCollapsed }">
    <div class="rail__brand">
      <div class="rail__mark" aria-hidden="true">墨</div>
      <div class="rail__brandtext">
        <b>Novel Studio</b>
        <span>长篇小说工作台</span>
      </div>
      <button
        type="button"
        class="rail__collapse"
        :aria-label="prefs.railCollapsed ? '展开侧栏' : '收起侧栏'"
        :title="prefs.railCollapsed ? '展开侧栏' : '收起侧栏'"
        @click="prefs.toggleRail()"
      >
        {{ prefs.railCollapsed ? '»' : '«' }}
      </button>
    </div>

    <div class="rail__bookwrap">
      <button
        type="button"
        class="rail__book"
        :aria-expanded="openSwitcher"
        :title="prefs.railCollapsed ? `${studio.book.title} · 切换书` : undefined"
        @click="openSwitcher = !openSwitcher"
      >
        <span class="rail__bookcover" aria-hidden="true">{{ studio.book.title.slice(0, 1) }}</span>
        <span class="rail__booktext">
          <span class="rail__bookname">{{ studio.book.title }}</span>
          <span class="rail__bookmeta">{{ studio.approved.length }}/{{ studio.book.targetChapters }} 章</span>
          <span class="rail__bar"><i :style="{ width: `${progress}%` }" /></span>
        </span>
        <span class="rail__caret" :class="{ 'rail__caret--up': openSwitcher }" aria-hidden="true">⌄</span>
      </button>
      <Transition name="drop">
        <div v-if="openSwitcher" class="rail__switcher">
          <div class="ns-eyebrow">书架</div>
          <div v-for="b in studio.shelf" :key="b.dir" class="rail__switchrow">
            <button
              type="button"
              class="rail__switcheritem"
              :class="{ on: studio.key === b.dir }"
              @click="switchBook(b.dir)"
            >
              <span>{{ b.title }}</span>
              <small>{{ b.chapterCount }} / {{ b.targetChapters }} 章</small>
            </button>
            <button
              type="button"
              class="rail__switchdel"
              :title="`删除《${b.title}》`"
              :aria-label="`删除《${b.title}》`"
              @click="askDelete(b)"
            >
              ✕
            </button>
          </div>
          <button type="button" class="rail__switchnew" @click="showNew = true; openSwitcher = false">
            ＋ 新建小说
          </button>
          <div class="rail__switchdivider" />
          <div class="rail__switchfoot">目录：<code>~/Desktop/mine/xiaoshuo</code></div>
        </div>
      </Transition>
    </div>

    <nav class="rail__nav" aria-label="工作台页签">
      <div v-for="g in groups" :key="g.label" class="rail__group">
        <div class="rail__groupname" :aria-hidden="prefs.railCollapsed">{{ g.label }}</div>
        <RouterLink
          v-for="tab in g.tabs"
          :key="tab.name"
          :to="{ name: tab.name }"
          class="rail__item"
          :class="{ on: route.name === tab.name }"
          :title="`${tab.label} · ${tab.hint}（g ${tab.key}）`"
          :aria-current="route.name === tab.name ? 'page' : undefined"
        >
          <span class="rail__glyph" aria-hidden="true">{{ tab.glyph }}</span>
          <span class="rail__label">{{ tab.label }}</span>
          <span v-if="flags[tab.name]" class="rail__badge" :class="`rail__badge--${tab.name}`">
            {{ flags[tab.name] }}
          </span>
        </RouterLink>
      </div>
    </nav>

    <div class="rail__foot">
      <div class="rail__status">
        <div class="rail__statushead">
          <i class="rail__dot" :class="`rail__dot--${gateTone}`" />
          <span class="rail__statustext">{{ gateLabel }} · 第 {{ studio.nextNumber }} 章</span>
        </div>
        <button type="button" class="rail__next" :class="`rail__next--${nextAction.tone}`" @click="goNext">
          <span class="rail__nextlabel">{{ nextAction.label }}</span>
          <span class="rail__nexthint">{{ nextAction.hint }}</span>
        </button>
      </div>
      <div class="rail__streak">
        <span><b>{{ studio.streak }}</b> 天连续</span>
        <span><b>{{ (studio.wordsToday / 1000).toFixed(1) }}k</b> 今日字</span>
      </div>
    </div>

    <Modal
      :open="!!deleteTarget"
      title="永久删除这本书？"
      desc="会直接删掉整本书目录和全部章节，不进回收站，删了无法从应用内恢复。"
      width="520px"
      @close="deleteTarget = null"
    >
      <p class="deltext">
        请输入书名 <b>{{ deleteTarget?.title }}</b> 确认：
      </p>
      <Input v-model="deleteConfirm" :placeholder="deleteTarget?.title" />
      <template #footer>
        <Button variant="ghost" @click="deleteTarget = null">取消</Button>
        <Button
          :disabled="deleting || deleteConfirm.trim() !== deleteTarget?.title"
          variant="danger"
          @click="confirmDelete"
        >
          {{ deleting ? '正在删除…' : '永久删除' }}
        </Button>
      </template>
    </Modal>

    <Modal
      :open="showNew"
      title="新建小说"
      desc="填章节数和每章字数，让 AI 按选题起书名、写简介；选中后建在 ~/Desktop/mine/xiaoshuo/书名/。"
      width="980px"
      @close="showNew = false"
    >
      <NewBookForm @created="onCreated" />
    </Modal>
  </aside>
</template>

<style scoped>
.rail {
  position: relative;
  z-index: var(--ns-z-rail);
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 16px 10px 12px;
  background: var(--ns-paper-2);
  border-right: 1px solid var(--ns-line);
  transition: width 0.16s ease;
}
.rail__brand {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 0 6px 14px;
  min-height: 46px;
}
.rail__mark {
  width: 32px;
  height: 32px;
  flex: none;
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
  min-width: 0;
  flex: 1;
}
.rail__brandtext b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.rail__brandtext span {
  color: var(--ns-ink-3);
  font-size: 10.5px;
  letter-spacing: 0.04em;
  white-space: nowrap;
}
.rail__collapse {
  flex: none;
  width: 24px;
  height: 24px;
  display: grid;
  place-items: center;
  border: 1px solid transparent;
  border-radius: var(--ns-r-sm);
  background: transparent;
  color: var(--ns-ink-4);
  font-size: 13px;
  cursor: pointer;
}
.rail__collapse:hover {
  background: var(--ns-card);
  border-color: var(--ns-line);
  color: var(--ns-ink);
}
.rail__bookwrap {
  position: relative;
  margin: 0 2px 12px;
}
.rail__book {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 9px;
  text-align: left;
  border: 1px solid var(--ns-line);
  background: var(--ns-card);
  border-radius: var(--ns-r-md);
  padding: 8px 9px;
  cursor: pointer;
  font: inherit;
  color: inherit;
  box-shadow: var(--ns-shadow-1);
}
.rail__book:hover {
  border-color: var(--ns-line-2);
}
.rail__bookcover {
  width: 26px;
  height: 34px;
  flex: none;
  display: grid;
  place-items: center;
  border-radius: 2px 4px 4px 2px;
  background: linear-gradient(160deg, var(--ns-pink) 0%, var(--ns-pink-2) 100%);
  color: #fff;
  font-family: var(--ns-serif);
  font-size: 14px;
  box-shadow: inset 2px 0 0 rgba(255, 255, 255, 0.28);
}
.rail__booktext {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 2px;
}
.rail__bookname {
  font-family: var(--ns-serif);
  font-weight: 700;
  font-size: var(--ns-fs-13);
  padding-right: 12px;
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
  background: var(--ns-chart-track);
  overflow: hidden;
}
.rail__bar i {
  display: block;
  height: 100%;
  background: var(--ns-pink);
  border-radius: inherit;
  transition: width 0.25s ease;
}
.rail__caret {
  position: absolute;
  right: 8px;
  top: 8px;
  color: var(--ns-ink-4);
  font-size: 11px;
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
  z-index: 30;
  background: var(--ns-card);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  box-shadow: var(--ns-shadow-2);
  padding: 8px;
}
.rail__switcher .ns-eyebrow {
  padding: 2px 6px 6px;
}
.rail__switchrow {
  display: flex;
  align-items: center;
  gap: 2px;
}
.rail__switchrow .rail__switcheritem {
  flex: 1;
  min-width: 0;
}
.rail__switchdel {
  flex: none;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: var(--ns-r-sm);
  background: transparent;
  color: var(--ns-ink-3);
  font-size: 11px;
  line-height: 1;
  cursor: pointer;
}
.rail__switchdel:hover {
  background: var(--ns-pink-soft);
  color: var(--ns-pink-2);
}
.deltext {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--ns-ink-2);
}
.deltext b {
  color: var(--ns-ink);
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
  background: var(--ns-hover);
}
.rail__switcheritem.on {
  background: var(--ns-pink-soft);
  color: var(--ns-pink-2);
  font-weight: 600;
}
.rail__switcheritem small {
  color: var(--ns-ink-3);
  font-size: 10.5px;
  flex: none;
}
.rail__switchnew {
  width: 100%;
  margin-top: 4px;
  padding: 7px 8px;
  border: 1px dashed var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: transparent;
  color: var(--ns-ink-2);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.rail__switchnew:hover {
  background: var(--ns-hover);
  color: var(--ns-ink);
}
.rail__switchdivider {
  height: 1px;
  background: var(--ns-line);
  margin: 6px 0;
}
.rail__switchfoot {
  font-size: 10px;
  color: var(--ns-ink-4);
  padding: 0 6px 2px;
  line-height: 1.6;
}
.rail__switchfoot code {
  font-family: var(--ns-mono);
}
.rail__nav {
  display: grid;
  gap: 2px;
  overflow: auto;
  min-height: 0;
  padding-bottom: 4px;
}
.rail__group + .rail__group {
  margin-top: 8px;
}
.rail__groupname {
  padding: 4px 10px 3px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.09em;
  color: var(--ns-ink-4);
}
.rail__item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: var(--ns-r-sm);
  color: var(--ns-ink-2);
  text-decoration: none;
  font-size: var(--ns-fs-13);
  transition: background 0.12s ease, color 0.12s ease;
}
.rail__item:hover {
  background: var(--ns-hover);
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
  left: -10px;
  top: 6px;
  bottom: 6px;
  width: 2px;
  border-radius: 0 2px 2px 0;
  background: var(--ns-pink);
}
.rail__glyph {
  width: 18px;
  flex: none;
  text-align: center;
  color: var(--ns-ink-4);
  font-family: var(--ns-serif);
  font-size: 13px;
}
.rail__item.on .rail__glyph {
  color: var(--ns-pink);
}
.rail__label {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
  padding-top: 12px;
  display: grid;
  gap: 8px;
}
.rail__status {
  display: grid;
  gap: 7px;
  padding: 10px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: color-mix(in srgb, var(--ns-card) 72%, transparent);
}
.rail__statushead {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.rail__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex: none;
}
.rail__dot--pink {
  background: var(--ns-pink);
}
.rail__dot--ok {
  background: var(--ns-ok);
}
.rail__dot--muted {
  background: var(--ns-ink-4);
}
.rail__statustext {
  font-size: 10.5px;
  color: var(--ns-ink-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rail__next {
  display: grid;
  gap: 1px;
  width: 100%;
  padding: 7px 9px;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink);
  text-align: left;
  font: inherit;
  cursor: pointer;
  transition: border-color 0.14s ease, background 0.14s ease;
}
.rail__next:hover {
  border-color: var(--ns-ink-4);
  background: var(--ns-hover);
}
.rail__next--pink {
  background: var(--ns-pink);
  border-color: var(--ns-pink);
  color: #fff;
}
.rail__next--pink:hover {
  background: var(--ns-pink-2);
  border-color: var(--ns-pink-2);
}
.rail__next--warn {
  background: var(--ns-warn-soft);
  border-color: color-mix(in srgb, var(--ns-warn) 34%, transparent);
  color: var(--ns-warn);
}
.rail__nextlabel {
  font-size: var(--ns-fs-12);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rail__nexthint {
  font-size: 10px;
  opacity: 0.72;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rail__streak {
  display: flex;
  justify-content: space-between;
  gap: 6px;
  padding: 0 4px;
  font-size: 10px;
  color: var(--ns-ink-3);
}
.rail__streak b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-12);
  color: var(--ns-ink);
  margin-right: 2px;
}

/* ---- collapsed: icon rail, more room for prose ---- */
.rail--collapsed {
  padding-left: 8px;
  padding-right: 8px;
}
.rail--collapsed .rail__brand {
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  padding: 0 0 12px;
}
.rail--collapsed .rail__brandtext,
.rail--collapsed .rail__booktext,
.rail--collapsed .rail__caret,
.rail--collapsed .rail__groupname,
.rail--collapsed .rail__label,
.rail--collapsed .rail__status,
.rail--collapsed .rail__streak {
  display: none;
}
.rail--collapsed .rail__collapse {
  width: 100%;
  height: 20px;
  font-size: 11px;
}
.rail--collapsed .rail__book {
  justify-content: center;
  padding: 6px;
}
.rail--collapsed .rail__item {
  justify-content: center;
  padding: 8px 0;
}
.rail--collapsed .rail__badge {
  position: absolute;
  top: 2px;
  right: 6px;
  min-width: 7px;
  width: 7px;
  height: 7px;
  padding: 0;
  font-size: 0;
}
.rail--collapsed .rail__group + .rail__group {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--ns-line);
}
.rail--collapsed .rail__glyph {
  color: var(--ns-ink-3);
}
.rail--collapsed .rail__item.on .rail__glyph {
  color: var(--ns-pink);
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
  .rail,
  .rail--collapsed {
    flex-direction: row;
    align-items: center;
    overflow-x: auto;
    padding: 7px 8px;
    border-right: 0;
    border-bottom: 1px solid var(--ns-line);
  }
  .rail__brandtext,
  .rail__bookwrap,
  .rail__foot,
  .rail__collapse {
    display: none;
  }
  .rail__brand {
    padding: 0 8px 0 2px;
    min-height: 0;
  }
  .rail__nav {
    display: flex;
    gap: 2px;
    overflow: visible;
  }
  .rail__group {
    display: contents;
  }
  .rail__group + .rail__group {
    margin-top: 0;
    padding-top: 0;
    border-top: 0;
  }
  .rail__groupname {
    display: none;
  }
  .rail__item,
  .rail--collapsed .rail__item {
    justify-content: flex-start;
    white-space: nowrap;
    padding: 6px 9px;
  }
  /* 手机上不认「收起侧栏」：图标没有标签就认不出来了 */
  .rail--collapsed .rail__label {
    display: block;
  }
  .rail--collapsed .rail__badge {
    position: static;
    min-width: 18px;
    width: auto;
    height: 17px;
    padding: 0 5px;
    font-size: 10px;
  }
  .rail__item.on::before {
    display: none;
  }
}
</style>

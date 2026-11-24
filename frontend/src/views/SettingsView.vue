<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Card, Table, type Column } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import ModelSettingsCard from '@/components/ModelSettingsCard.vue'
import { useStudio } from '@/stores/studio'
import { usePrefs, type Theme } from '@/stores/prefs'

const studio = useStudio()
const prefs = usePrefs()
const THEMES: Array<{ k: Theme; t: string; d: string }> = [
  { k: 'auto', t: '跟随系统', d: '系统深浅色变了，界面跟着变' },
  { k: 'light', t: '浅色', d: '暖纸底，白天写作用' },
  { k: 'dark', t: '深色', d: '夜里不刺眼' },
]

const recentUsage = computed(() => [...studio.data.usage].slice(-8).reverse())
const usageCols: Column<(typeof recentUsage.value)[number]>[] = [
  { key: 'at', label: '时间', width: '130px' },
  { key: 'kind', label: '动作', width: '90px' },
  { key: 'chapter', label: '章', numeric: true, width: '56px' },
  { key: 'tokens', label: 'tokens', numeric: true, width: '90px' },
  { key: 'verdict', label: '结果', width: '90px' },
]
const tokensTotal = computed(() => studio.data.usage.reduce((s, u) => s + u.tokens, 0))
const autoSaveHint = computed(() =>
  prefs.autoArchive ? '待确认章进「进度」页会自动存档，不弹确认框' : '关掉后，待确认章要手动点「存档」',
)

// 写作与存档：两个可改值，失焦/回车时写回 project.json
const minChars = ref(studio.book.minChars)
const segmentSize = ref(studio.book.segmentSize || 10)
const savingBook = ref(false)

watch(
  () => [studio.book.minChars, studio.book.segmentSize],
  ([m, s]) => {
    minChars.value = m
    segmentSize.value = s || 10
  },
)

async function saveBook(patch: { minChars?: number; segmentSize?: number }) {
  if (savingBook.value) return
  savingBook.value = true
  try {
    await studio.saveBookSettings(patch)
  } catch {
    minChars.value = studio.book.minChars
    segmentSize.value = studio.book.segmentSize
  } finally {
    savingBook.value = false
  }
}

function blurOnEnter(e: KeyboardEvent) {
  const el = e.target as HTMLInputElement | null
  el?.blur()
}

function commitMinChars() {
  const v = Math.max(0, Math.min(20000, Math.round(Number(minChars.value) || 0)))
  if (v === studio.book.minChars) {
    minChars.value = v
    return
  }
  void saveBook({ minChars: v })
}

function commitSegmentSize() {
  const v = Math.max(3, Math.min(30, Math.round(Number(segmentSize.value) || 10)))
  if (v === studio.book.segmentSize) {
    segmentSize.value = v
    return
  }
  void saveBook({ segmentSize: v })
}
</script>

<template>
  <div class="page">
    <PageHeader eyebrow="项目配置" title="设置" desc="这里改的都是这本书的行为，不动别的书。改动先在本页生效，再写回 project.json。" />

    <div class="cols">
      <div class="ns-stack">
        <Card title="项目" desc="路径、题材、平台在建书时定死；要换落点请改环境变量 DSH_NOVEL_HOME。">
          <dl class="rows">
            <div><dt>书名</dt><dd>{{ studio.book.title }}</dd></div>
            <div><dt>目录</dt><dd class="ns-mono tiny">{{ studio.book.dir }}</dd></div>
            <div><dt>题材</dt><dd>{{ studio.book.genre }}</dd></div>
            <div><dt>平台</dt><dd>{{ studio.book.platform }}</dd></div>
            <div><dt>目标</dt><dd>{{ studio.book.targetChapters }} 章 · 每章约 {{ studio.book.wordsPerChapter }} 字</dd></div>
            <div><dt>更新时间</dt><dd class="ns-num">{{ studio.book.updatedAt }}</dd></div>
          </dl>
        </Card>

        <ModelSettingsCard />

      </div>

      <div class="ns-stack">
        <Card title="外观" desc="主题和侧栏宽度只存在这台浏览器里，不写进书稿。快捷键 T 也能切主题。">
          <div class="themes">
            <button
              v-for="t in THEMES"
              :key="t.k"
              type="button"
              class="themeopt"
              :class="{ on: prefs.theme === t.k }"
              :aria-pressed="prefs.theme === t.k"
              @click="prefs.theme = t.k"
            >
              <span class="themeopt__preview" :class="`themeopt__preview--${t.k}`" aria-hidden="true">
                <i /><i /><i />
              </span>
              <b>{{ t.t }}</b>
              <small>{{ t.d }}</small>
            </button>
          </div>
          <div class="switchrow">
            <div>
              <b>收起侧栏</b>
              <p>只留图标，正文区更宽；也可以点侧栏左上角的 «。</p>
            </div>
            <button
              type="button"
              class="switch"
              :class="{ on: prefs.railCollapsed }"
              role="switch"
              :aria-checked="prefs.railCollapsed"
              @click="prefs.toggleRail()"
            >
              <i />
            </button>
          </div>
        </Card>

        <Card title="写作与存档" desc="作者只做三个决定：选题、这一章过不过、方向改不改。">
          <div class="switchrow">
            <div>
              <b>待确认章自动存档</b>
              <p>{{ autoSaveHint }}</p>
            </div>
            <button
              type="button"
              class="switch"
              :class="{ on: prefs.autoArchive }"
              role="switch"
              :aria-checked="prefs.autoArchive"
              @click="prefs.autoArchive = !prefs.autoArchive"
            >
              <i />
            </button>
          </div>
          <div class="switchrow">
            <div>
              <b>章节字数硬下限</b>
              <p>长篇每章低于这个字数会标「待修」；填 0 表示不设下限。全书 ≤50 章的短篇默认不限。</p>
            </div>
            <div class="minchars">
              <input
                v-model.number="minChars"
                type="number"
                min="0"
                max="20000"
                step="100"
                :disabled="savingBook"
                aria-label="每章字数硬下限"
                @blur="commitMinChars"
                @keydown.enter.prevent="blurOnEnter"
              />
              <span>字</span>
            </div>
          </div>
          <div class="switchrow">
            <div>
              <b>批量写作一段几章</b>
              <p>
                默认 {{ segmentSize }} 章一段，一段一份段落纲（3–5 个台阶），不逐章排细纲；
                范围 3–30 章，改完影响下一次规划。
              </p>
            </div>
            <div class="minchars">
              <input
                v-model.number="segmentSize"
                type="number"
                min="3"
                max="30"
                step="1"
                :disabled="savingBook"
                aria-label="每段章数"
                @blur="commitSegmentSize"
                @keydown.enter.prevent="blurOnEnter"
              />
              <span>章</span>
            </div>
          </div>
        </Card>

      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.cols {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr);
  gap: 14px;
  align-items: start;
}
.rows {
  margin: 0;
  display: grid;
}
.rows > div {
  display: grid;
  grid-template-columns: 88px minmax(0, 1fr);
  gap: 12px;
  padding: 8px 0;
  border-top: 1px dashed var(--ns-line);
  font-size: 12.5px;
}
.rows > div:first-child {
  border-top: 0;
  padding-top: 0;
}
.rows dt {
  color: var(--ns-ink-3);
  font-size: 11.5px;
}
.rows dd {
  margin: 0;
  color: var(--ns-ink);
}
.rows dd.tiny {
  font-size: 11px;
  word-break: break-all;
  color: var(--ns-ink-2);
}
.model {
  display: grid;
  grid-template-columns: 1fr 1.4fr auto;
  gap: 10px;
  align-items: end;
}
.model-stack {
  display: grid;
  gap: 10px;
}
.model-stack .model {
  grid-template-columns: 1fr 1fr;
}
.model-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.probe {
  font-size: 11.5px;
}
.probe.ok {
  color: var(--ns-ok, #2f7d4f);
}
.probe.bad {
  color: var(--ns-warn, #a8452f);
}
.model label {
  display: grid;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--ns-ink-3);
}
.model select,
.model input {
  height: 34px;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: 12.5px;
  padding: 0 10px;
  outline: none;
}
.model select:focus,
.model input:focus {
  border-color: var(--ns-pink);
  box-shadow: var(--ns-focus);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  border: 1px solid var(--ns-line-2);
  background: var(--ns-card);
  color: var(--ns-ink-2);
  border-radius: var(--ns-r-pill);
  padding: 4px 12px;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}
.chip:hover {
  border-color: var(--ns-ink-4);
}
.chip.on {
  background: var(--ns-ink);
  border-color: var(--ns-ink);
  color: var(--ns-card);
  font-weight: 600;
}
.themes {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}
.themeopt {
  display: grid;
  gap: 3px;
  padding: 8px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.14s ease, box-shadow 0.14s ease;
}
.themeopt:hover {
  border-color: var(--ns-line-2);
}
.themeopt.on {
  border-color: var(--ns-pink);
  box-shadow: 0 0 0 1px var(--ns-pink) inset;
}
.themeopt b {
  font-size: 12px;
}
.themeopt small {
  font-size: 10.5px;
  color: var(--ns-ink-3);
  line-height: 1.45;
}
.themeopt__preview {
  display: grid;
  gap: 3px;
  padding: 6px;
  margin-bottom: 4px;
  border-radius: 4px;
  border: 1px solid var(--ns-line);
}
.themeopt__preview i {
  display: block;
  height: 4px;
  border-radius: 2px;
  background: currentColor;
  opacity: 0.32;
}
.themeopt__preview i:first-child {
  width: 60%;
  opacity: 0.75;
}
.themeopt__preview i:nth-child(2) {
  width: 88%;
}
.themeopt__preview--light {
  background: #f7f4ee;
  color: #1c1a17;
}
.themeopt__preview--dark {
  background: #141311;
  color: #f2ede3;
}
.themeopt__preview--auto {
  background: linear-gradient(100deg, #f7f4ee 0 50%, #141311 50% 100%);
  color: #7d7568;
}
.switchrow {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 11px 0;
  border-top: 1px dashed var(--ns-line);
}
.switchrow:first-child {
  border-top: 0;
  padding-top: 0;
}
.switchrow > div:first-child {
  flex: 1;
}
.switchrow b {
  font-size: 12.5px;
}
.switchrow p {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: var(--ns-ink-3);
  line-height: 1.6;
}
.switch {
  flex: none;
  width: 38px;
  height: 22px;
  border-radius: var(--ns-r-pill);
  border: 1px solid var(--ns-line-2);
  background: var(--ns-card-2);
  position: relative;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.switch i {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--ns-card);
  box-shadow: var(--ns-shadow-1);
  transition: transform 0.15s ease;
}
.switch.on {
  background: var(--ns-pink);
  border-color: var(--ns-pink);
}
.switch.on i {
  transform: translateX(16px);
}
.minchars {
  display: flex;
  align-items: center;
  gap: 6px;
}
.minchars input {
  width: 82px;
  height: 30px;
  text-align: right;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  font: inherit;
  font-variant-numeric: tabular-nums;
  padding: 0 8px;
  outline: none;
  color: var(--ns-ink);
  background: var(--ns-card);
}
.minchars span {
  font-size: 12px;
  color: var(--ns-ink-3);
}
.switchrow--static {
  align-items: flex-start;
}
.repairlist {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--ns-ink-2);
}
.repairlist span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.repaired {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--ns-ink-2);
  padding: 9px 11px;
  background: var(--ns-ok-soft);
  border-radius: var(--ns-r-sm);
}
@media (max-width: 980px) {
  .cols {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 620px) {
  .page {
    padding: 20px 16px 64px;
  }
  .model {
    grid-template-columns: 1fr;
  }
}
</style>

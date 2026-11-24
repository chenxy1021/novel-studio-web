<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Modal, Tag } from '@/design'
import type { FocusRef, ReferencePack, ReferenceSection } from '@/api/references'

const props = withDefaults(
  defineProps<{
    open: boolean
    chapter: number
    pack: ReferencePack | null
    loading?: boolean
    existing?: boolean
    focus?: FocusRef[]
    focusOptions?: FocusRef[]
    error?: string
  }>(),
  {
    loading: false,
    existing: false,
    focus: () => [],
    focusOptions: () => [],
    error: '',
  },
)

const emit = defineEmits<{
  close: []
  refresh: []
  'update:focus': [value: FocusRef[]]
  write: []
  go: [route: string]
}>()

const GROUP_ORDER = ['强调', '结构', '伏笔', '人物', '世界', '前情', '写法'] as const
const DEFAULT_OPEN = new Set(['结构', '伏笔', '前情'])

const expanded = ref<Record<string, boolean>>({})
const openSection = ref<Record<string, boolean>>({})
const addKey = ref('')

const groups = computed(() => {
  const map = new Map<string, ReferenceSection[]>()
  for (const s of props.pack?.sections ?? []) {
    const list = map.get(s.group) ?? []
    list.push(s)
    map.set(s.group, list)
  }
  return [...GROUP_ORDER, ...map.keys()]
    .filter((g, i, all) => all.indexOf(g) === i && map.has(g))
    .map((group) => ({ group, rows: map.get(group) ?? [] }))
})

const summary = computed(() => {
  const p = props.pack
  if (!p) return ''
  const filled = p.sections.filter((s) => !s.missing).length
  return `${filled} 类 · ${p.summary.items} 条 · 约 ${p.summary.chars} 字`
})

const missing = computed(() => {
  const rank: Record<string, number> = {
    'character-state': 0,
    'continuity-state': 1,
    relations: 2,
    factions: 2,
    locations: 3,
    items: 4,
    'chapter-memory': 5,
    'volume-memory': 6,
    timeline: 7,
  }
  return (props.pack?.sections ?? [])
    .filter((s) => s.missing && !s.optional)
    .sort((a, b) => (rank[a.key] ?? 99) - (rank[b.key] ?? 99))
})

const focusLabels = computed(() => new Set(props.focus.map((f) => `${f.type}:${f.key}`)))

const available = computed(() =>
  props.focusOptions.filter((o) => !focusLabels.value.has(`${o.type}:${o.key}`)),
)

function routeFor(key: string): string {
  if (key.startsWith('foreshadow')) return '/foreshadow'
  if (key === 'volume-outline' || key === 'stage') return '/detail'
  if (key === 'characters') return '/characters'
  if (key === 'character-state') return '/memory'
  if (key === 'relations') return '/setup?tab=relations'
  if (key === 'continuity-state') return '/characters'
  if (key === 'info-gaps') return '/setup?tab=gaps'
  if (key.startsWith('chapter-memory') || key === 'archived-summaries') return '/memory'
  if (key === 'volume-memory' || key === 'timeline') return '/memory'
  if (key === 'rules' || key === 'nuewen' || key === 'style' || key === 'platform') return '/setup'
  if (key === 'world' || key === 'factions' || key === 'locations' || key === 'items') return '/outline?tab=world'
  return '/setup'
}

const FIX_LABEL: Record<string, string> = {
  'character-state': '去记忆页补写',
  'continuity-state': '去人物页',
  relations: '去设定页',
  'info-gaps': '去补信息差',
  factions: '去设定页',
  locations: '去世界观栏',
  items: '去设定页',
  'chapter-memory': '去记忆页补写',
  'volume-memory': '去记忆页补写',
  timeline: '去记忆页补写',
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    const next: Record<string, boolean> = {}
    for (const g of groups.value) next[g.group] = DEFAULT_OPEN.has(g.group)
    expanded.value = next
    openSection.value = {}
    addKey.value = ''
  },
  { immediate: true },
)

watch(groups, (list) => {
  if (!props.open) return
  for (const g of list) if (!(g.group in expanded.value)) expanded.value[g.group] = DEFAULT_OPEN.has(g.group)
})

function toggleGroup(group: string) {
  expanded.value = { ...expanded.value, [group]: !expanded.value[group] }
}

function toggleSection(key: string) {
  openSection.value = { ...openSection.value, [key]: !openSection.value[key] }
}

function addFocus() {
  const opt = available.value.find((o) => `${o.type}:${o.key}` === addKey.value)
  if (!opt || props.focus.length >= 5) return
  emit('update:focus', [...props.focus, opt])
  addKey.value = ''
}

function removeFocus(index: number) {
  emit('update:focus', props.focus.filter((_, i) => i !== index))
}
</script>

<template>
  <Modal
    :open="open"
    :title="`第 ${chapter} 章 · 本章参考资料`"
    width="720px"
    desc="生成细纲和正文时实际会注入的资料。标灰的项没生成，补上能减少跑偏。"
    @close="emit('close')"
  >
    <div class="ref">
      <div class="ref__bar">
        <span class="ref__summary">{{ loading ? '正在打包参考资料…' : summary }}</span>
        <Tag v-if="existing" size="sm" tone="ok">已有正文</Tag>
        <Button size="sm" variant="ghost" :disabled="loading" @click="emit('refresh')">刷新资料</Button>
      </div>

      <p v-if="error" class="ref__error">{{ error }}</p>

      <div v-if="loading && !pack" class="ref__skeleton">
        <div v-for="i in 6" :key="i" class="ref__skel" />
      </div>

      <template v-else-if="pack">
        <div class="ref__groups">
          <section v-for="g in groups" :key="g.group" class="ref__group">
            <button type="button" class="ref__grouphead" :aria-expanded="!!expanded[g.group]" @click="toggleGroup(g.group)">
              <span class="ref__caret">{{ expanded[g.group] ? '▾' : '▸' }}</span>
              <b>{{ g.group }}</b>
              <span class="ref__gcount">{{ g.rows.filter((r) => !r.missing).length }}/{{ g.rows.length }} 类</span>
            </button>
            <div v-if="expanded[g.group]" class="ref__rows">
              <div v-for="s in g.rows" :key="s.key" class="ref__row" :class="{ 'ref__row--missing': s.missing }">
                <button type="button" class="ref__rowhead" :disabled="s.missing" @click="toggleSection(s.key)">
                  <span class="ref__rname">{{ s.label }}</span>
                  <span v-if="s.missing" class="ref__rmiss">缺</span>
                  <span v-else class="ref__rcount">{{ s.count }} 条</span>
                  <Tag v-if="s.truncated" size="sm" tone="warn">已截断</Tag>
                  <span class="ref__rsource">{{ s.source }}</span>
                </button>
                <div v-if="openSection[s.key] && !s.missing" class="ref__text">
                  {{ s.text }}
                </div>
                <div v-if="s.missing && FIX_LABEL[s.key]" class="ref__fix">
                  <span>还没有这项资料</span>
                  <button type="button" class="ref__link" @click="emit('go', routeFor(s.key))">
                    {{ FIX_LABEL[s.key] }} →
                  </button>
                </div>
              </div>
            </div>
          </section>
        </div>

        <div v-if="missing.length" class="ref__missing">
          <div class="ref__label">缺失</div>
          <div v-for="s in missing" :key="`m-${s.key}`" class="ref__missrow">
            <span>{{ s.label }}</span>
            <span class="ref__misstext">{{ s.source }} 没有内容</span>
            <button type="button" class="ref__link" @click="emit('go', routeFor(s.key))">
              {{ FIX_LABEL[s.key] || '去补齐' }} →
            </button>
          </div>
        </div>

        <div class="ref__focus">
          <div class="ref__label">本章额外强调</div>
          <div class="ref__focusrow">
            <select v-model="addKey" class="ref__select" :disabled="focus.length >= 5 || !available.length">
              <option value="">＋ 添加强调</option>
              <option v-for="o in available" :key="`${o.type}:${o.key}`" :value="`${o.type}:${o.key}`">
                {{ o.label || o.key }}
              </option>
            </select>
            <Button size="sm" :disabled="!addKey || focus.length >= 5" @click="addFocus">添加</Button>
            <span class="ref__hint">已选 1–5 条，会置顶注入，不替代常规资料。</span>
          </div>
          <div class="ref__chips">
            <span v-for="(f, i) in focus" :key="`${f.type}:${f.key}`" class="ref__chip">
              {{ f.label || f.key }}
              <button type="button" aria-label="移除" @click="removeFocus(i)">×</button>
            </span>
          </div>
        </div>
      </template>

      <div v-else class="ref__empty">
        <b>这一章还没有任何可注入的资料</b>
        <p>先把大纲、设定或伏笔补上，再回来。</p>
        <Button size="sm" @click="emit('go', '/setup')">去设定页</Button>
      </div>
    </div>

    <template #footer>
      <Button variant="ghost" @click="emit('close')">关闭</Button>
      <Button variant="primary" @click="emit('write')">
        {{ existing ? '重写本章…' : '以此开写本章' }}
      </Button>
    </template>
  </Modal>
</template>

<style scoped>
.ref {
  display: flex;
  flex-direction: column;
  gap: var(--ns-s3);
  min-height: 220px;
}
.ref__bar {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
}
.ref__summary {
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  font-variant-numeric: tabular-nums;
}
.ref__bar .ns-btn {
  margin-left: auto;
}
.ref__error {
  margin: 0;
  color: var(--ns-bad);
  font-size: var(--ns-fs-12);
}
.ref__skeleton {
  display: grid;
  gap: var(--ns-s2);
}
.ref__skel {
  height: 34px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  animation: refpulse 1.2s ease-in-out infinite;
}
@keyframes refpulse {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}
.ref__groups {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ref__group {
  border-top: 1px solid var(--ns-line);
}
.ref__grouphead {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  border: 0;
  background: none;
  color: var(--ns-ink);
  font: inherit;
  font-size: var(--ns-fs-13);
  cursor: pointer;
  padding: var(--ns-s2) 0;
  text-align: left;
}
.ref__caret {
  width: 12px;
  color: var(--ns-ink-3);
}
.ref__gcount {
  margin-left: auto;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
}
.ref__rows {
  padding: 0 0 var(--ns-s2) 20px;
}
.ref__row {
  padding: 3px 0;
}
.ref__row--missing {
  opacity: 0.72;
}
.ref__rowhead {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  border: 0;
  background: none;
  color: var(--ns-ink);
  font: inherit;
  font-size: var(--ns-fs-12);
  cursor: pointer;
  text-align: left;
  padding: 2px 0;
}
.ref__rowhead:disabled {
  cursor: default;
}
.ref__rname {
  font-weight: 500;
}
.ref__rcount {
  color: var(--ns-ink-3);
  font-variant-numeric: tabular-nums;
}
.ref__rmiss {
  color: var(--ns-warn);
  font-size: var(--ns-fs-11);
}
.ref__rsource {
  margin-left: auto;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.ref__text {
  max-height: 180px;
  overflow: auto;
  white-space: pre-wrap;
  background: var(--ns-card-2);
  border-radius: var(--ns-r-sm);
  padding: var(--ns-s2);
  font-size: var(--ns-fs-12);
  line-height: 1.65;
  color: var(--ns-ink-2);
  margin: 2px 0 6px;
}
.ref__fix {
  display: flex;
  gap: var(--ns-s2);
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
  padding-left: 2px;
}
.ref__link {
  border: 0;
  background: none;
  color: var(--ns-pink);
  font: inherit;
  font-size: inherit;
  cursor: pointer;
  padding: 0;
}
.ref__missing {
  border-top: 1px solid var(--ns-line);
  padding-top: var(--ns-s2);
  display: grid;
  gap: 4px;
}
.ref__label {
  font-size: var(--ns-fs-12);
  font-weight: 600;
  color: var(--ns-ink-2);
}
.ref__missrow {
  display: flex;
  align-items: baseline;
  gap: var(--ns-s2);
  font-size: var(--ns-fs-12);
}
.ref__misstext {
  color: var(--ns-ink-3);
  margin-left: auto;
}
.ref__focus {
  border-top: 1px solid var(--ns-line);
  padding-top: var(--ns-s2);
  display: grid;
  gap: var(--ns-s1);
}
.ref__focusrow {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  flex-wrap: wrap;
}
.ref__select {
  height: 28px;
  max-width: 220px;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: var(--ns-fs-12);
  padding: 0 var(--ns-s1);
}
.ref__hint {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.ref__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.ref__chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-pill);
  padding: 1px 8px;
  font-size: var(--ns-fs-11);
  background: var(--ns-card-2);
}
.ref__chip button {
  border: 0;
  background: none;
  color: var(--ns-ink-3);
  cursor: pointer;
  padding: 0;
  font-size: 12px;
}
.ref__empty {
  display: flex;
  flex-direction: column;
  gap: var(--ns-s2);
  align-items: flex-start;
  padding: var(--ns-s5);
  color: var(--ns-ink-2);
}
.ref__empty p {
  margin: 0;
  font-size: var(--ns-fs-13);
}
</style>

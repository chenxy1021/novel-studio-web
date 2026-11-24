<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Card, Tag } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import StyleFields from '@/components/StyleFields.vue'
import { useStudio } from '@/stores/studio'
import type { ApiStyle } from '@/api/studio'

const studio = useStudio()
const router = useRouter()

const styleDraft = ref<Partial<ApiStyle>>({})
const styleSaving = ref(false)
const presetBusy = ref('')

const presetList = computed(() => studio.stylePresets)
const appliedPresetId = computed(() => String(studio.style?.presetId ?? ''))

const summaryRows = computed(() => {
  const s = { ...(studio.style ?? {}), ...styleDraft.value } as ApiStyle
  return [
    { label: '视角', value: s.pov },
    { label: '人称', value: s.person },
    { label: '句长', value: s.sentence },
    { label: '段落', value: s.paragraph },
    { label: '节奏', value: s.rhythm },
    { label: '对话', value: s.dialogueRatio },
    { label: '禁用', value: (s.banned ?? []).length ? `${(s.banned ?? []).length} 条` : '' },
    { label: '样章', value: (s.samples ?? []).length ? `${(s.samples ?? []).length} 段` : '' },
  ].filter((r) => String(r.value ?? '').trim())
})

const bookHasStyle = computed(() => Object.keys(studio.style ?? {}).some((k) => !['version', 'updatedAt'].includes(k)))
const sourceLabel = computed(() =>
  studio.styleSource === 'book' ? '本书默认已设置' : studio.styleSource === 'platform' ? '按平台默认' : '还没设置',
)

async function loadDraft() {
  if (!studio.style) {
    try {
      await studio.loadStyle()
    } catch {
      return
    }
  }
  styleDraft.value = { ...(studio.style ?? {}) }
}

watch(
  () => studio.style,
  (s) => {
    if (s) styleDraft.value = { ...styleDraft.value, ...s }
  },
)

onMounted(() => {
  void loadDraft()
  if (!studio.stylePresets.length) void studio.loadStylePresets().catch(() => {})
})

async function applyPreset(id: string, name: string) {
  if (presetBusy.value) return
  if (bookHasStyle.value) {
    const ok = window.confirm(
      `把「${name}」设为本书默认文风？\n会覆盖同名字段；样章会换成这位作家的样章（你手填或编辑过的样章保留）。`,
    )
    if (!ok) return
  }
  presetBusy.value = id
  try {
    await studio.applyPreset(id, true)
    styleDraft.value = { ...(studio.style ?? {}) }
  } catch {
    /* store 已 toast */
  } finally {
    presetBusy.value = ''
  }
}

async function saveStyleDraft() {
  if (styleSaving.value) return
  styleSaving.value = true
  try {
    await studio.saveStyle(styleDraft.value)
  } catch {
    /* store 已 toast */
  } finally {
    styleSaving.value = false
  }
}

function goWrite() {
  void router.push({ name: 'workflow' })
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="写作基线"
      title="文风"
      desc="这一份是全书默认写法：视角、句长、节奏、对话比例和禁用表达。每次开写前还会再确认一次，可临时覆盖；文风只决定怎么写，不改情节事实。"
    >
      <Button icon="✍" variant="ghost" @click="goWrite">去开写 →</Button>
      <Button
        variant="pink"
        :disabled="styleSaving || studio.styleBusy"
        @click="saveStyleDraft"
      >{{ styleSaving ? '保存中…' : '保存文风' }}</Button>
    </PageHeader>

    <Card
      eyebrow="作家参照"
      title="从一位作家的写法开始"
      desc="只借写法（句长、节奏、对白密度、禁用表达），不复制句子；套用后仍可按本书需要逐项改。"
      class="presets"
    >
      <div class="presets__grid">
        <button
          v-for="p in presetList"
          :key="p.id"
          type="button"
          class="preset"
          :class="{ on: appliedPresetId === p.id }"
          :disabled="!!presetBusy"
          @click="applyPreset(p.id, p.name)"
        >
          <span class="preset__head">
            <b>{{ p.name }}</b>
            <Tag v-if="appliedPresetId === p.id" size="sm" tone="ok">当前</Tag>
            <Tag v-else-if="p.advisor" size="sm" tone="neutral">参照</Tag>
            <Tag v-if="p.samples?.length" size="sm" tone="neutral">含样章</Tag>
            <span v-if="presetBusy === p.id" class="preset__busy">套用中…</span>
          </span>
          <span class="preset__summary">{{ p.summary }}</span>
          <span class="preset__traits">
            <i v-for="t in p.traits.slice(0, 4)" :key="t">{{ t }}</i>
          </span>
        </button>
      </div>
      <p v-if="!presetList.length" class="ns-muted">预设加载中…</p>
    </Card>

    <Card
      eyebrow="本书默认"
      title="文风字段"
      :desc="`${sourceLabel}。保存后只影响之后的批次；正在运行的批次用启动那一刻的值。`"
      class="fields"
    >
      <template #actions>
        <Tag size="sm" :tone="studio.styleSource === 'book' ? 'ok' : 'neutral'">{{ sourceLabel }}</Tag>
      </template>

      <div v-if="summaryRows.length" class="fields__chips">
        <span v-for="r in summaryRows" :key="r.label" class="fields__chip">
          <i>{{ r.label }}</i>{{ r.value }}
        </span>
      </div>

      <StyleFields v-model="styleDraft" hide-presets />

      <template #footer>
        <span class="fields__note">例：少用成语；情绪落在动作上；不写总结句。</span>
        <Button variant="pink" :disabled="styleSaving || studio.styleBusy" @click="saveStyleDraft">
          {{ styleSaving ? '保存中…' : '保存文风' }}
        </Button>
      </template>
    </Card>
  </div>
</template>

<style scoped>
.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.presets,
.fields {
  margin-bottom: 18px;
}
.presets__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.preset {
  display: grid;
  gap: 6px;
  text-align: left;
  font: inherit;
  padding: 12px 14px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  color: var(--ns-ink);
  cursor: pointer;
  transition: border-color 0.14s ease, background 0.14s ease;
}
.preset:hover:not(:disabled) {
  border-color: var(--ns-pink-line);
  background: var(--ns-card);
}
.preset.on {
  border-color: var(--ns-pink);
  background: var(--ns-pink-soft);
}
.preset:disabled {
  opacity: 0.7;
  cursor: default;
}
.preset__head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.preset__head b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-15);
}
.preset__busy {
  margin-left: auto;
  font-size: 11px;
  color: var(--ns-ink-3);
}
.preset__summary {
  font-size: 12px;
  line-height: 1.65;
  color: var(--ns-ink-2);
}
.preset__traits {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.preset__traits i {
  font-style: normal;
  font-size: 10.5px;
  color: var(--ns-ink-3);
  background: var(--ns-card);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-pill);
  padding: 0 6px;
  line-height: 1.7;
}
.fields__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}
.fields__chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-pill);
  background: var(--ns-card-2);
  font-size: 11.5px;
  color: var(--ns-ink-2);
}
.fields__chip i {
  font-style: normal;
  color: var(--ns-ink-3);
}
.fields__note {
  flex: 1;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  line-height: 1.6;
}
@media (max-width: 900px) {
  .presets__grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 620px) {
  .page {
    padding: 20px 16px 64px;
  }
}
</style>

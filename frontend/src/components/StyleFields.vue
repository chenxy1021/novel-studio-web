<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Input } from '@/design'
import type { ApiStyle } from '@/api/studio'
import { useStudio } from '@/stores/studio'

const props = withDefaults(
  defineProps<{
    modelValue: Partial<ApiStyle>
    compact?: boolean
    /** 开写面板里只改本批 override，不悄悄改书默认。 */
    localPresets?: boolean
    /** 页面已有自己的预设入口时，隐藏字段区里的下拉。 */
    hidePresets?: boolean
  }>(),
  { compact: false, localPresets: false, hidePresets: false },
)
const emit = defineEmits<{ 'update:modelValue': [Partial<ApiStyle>] }>()
const studio = useStudio()

const POV = ['第三人称限制', '第一人称', '第三人称全知']
const PERSON = ['他/她', '我']
const SENTENCE = ['短句为主', '长短交错', '长句铺陈']
const PARAGRAPH = ['1–3 句', '3–5 句', '长段']
const RHYTHM = ['紧', '缓', '张弛']
const DIALOGUE = ['低 10–20%', '中 20–40%', '高 40%+']

function patch(key: keyof ApiStyle, value: unknown) {
  emit('update:modelValue', { ...props.modelValue, [key]: value } as Partial<ApiStyle>)
}

function scalar(key: 'pov' | 'person' | 'sentence' | 'paragraph' | 'rhythm' | 'dialogueRatio') {
  return computed({
    get: () => String(props.modelValue[key] ?? ''),
    set: (v: string) => patch(key, v),
  })
}

const pov = scalar('pov')
const person = scalar('person')
const sentence = scalar('sentence')
const paragraph = scalar('paragraph')
const rhythm = scalar('rhythm')
const dialogueRatio = scalar('dialogueRatio')

function withCurrent(list: string[], current: string): string[] {
  return current && !list.includes(current) ? [...list, current] : list
}

const bannedText = computed({
  get: () => (props.modelValue.banned ?? []).join('\n'),
  set: (v: string) => patch('banned', v.split('\n')),
})

const notes = computed({
  get: () => String(props.modelValue.notes ?? ''),
  set: (v: string) => patch('notes', v),
})

const referenceText = computed({
  get: () =>
    (props.modelValue.references ?? [])
      .map((r) => (typeof r === 'string' ? r : [r.author, r.work ? `《${r.work}》` : '', r.note].filter(Boolean).join(' ')))
      .join('\n'),
  set: (v: string) => patch('references', v.split('\n')),
})

type SampleRow = { text: string; label: string; note?: string }

const samples = computed<SampleRow[]>(() =>
  (props.modelValue.samples ?? []).map((s) =>
    typeof s === 'string' ? { text: s, label: '' } : { text: s.text, label: s.label ?? '', note: s.note },
  ),
)

function emitSamples(list: SampleRow[]) {
  patch(
    'samples',
    list.map((s) => {
      const row: { text: string; label?: string; note?: string } = { text: s.text }
      if (s.label) row.label = s.label
      if (s.note) row.note = s.note
      return row
    }),
  )
}

function updateSample(i: number, key: keyof SampleRow, value: string) {
  emitSamples(samples.value.map((s, idx) => (idx === i ? { ...s, [key]: value } : s)))
}

function addSample() {
  if (samples.value.length >= 3) return
  emitSamples([...samples.value, { text: '', label: '' }])
}

function removeSample(i: number) {
  emitSamples(samples.value.filter((_, idx) => idx !== i))
}

const presetId = ref('')
onMounted(() => {
  if (!studio.stylePresets.length) void studio.loadStylePresets().catch(() => {})
})

async function onPresetChange() {
  const id = presetId.value
  presetId.value = ''
  if (!id) return

  // 开写面板：预设只作用于本批 override，不写进本书默认。
  if (props.localPresets) {
    const preset = studio.stylePresets.find((p) => p.id === id)
    if (!preset) {
      void studio.loadStylePresets().catch(() => {})
      return
    }
    emit('update:modelValue', { ...props.modelValue, ...preset.fields, presetId: id })
    studio.toast(`本批按「${preset.name}」写；只借写法，不复制句子`, 'info')
    return
  }

  try {
    await studio.applyPreset(id, false)
    studio.toast('参考写法，不复制句子；本书字段优先', 'info')
  } catch {
    /* applyPreset 已 toast */
  }
}
</script>

<template>
  <div class="sf" :class="{ 'sf--compact': compact }">
    <div v-if="!hidePresets" class="sf__preset">
      <span class="sf__presetlabel">从参照开始</span>
      <select
        class="sf__select sf__select--preset"
        :value="presetId"
        :disabled="studio.styleBusy"
        aria-label="套用文风预设"
        @change="presetId = ($event.target as HTMLSelectElement).value; onPresetChange()"
      >
        <option value="">选一位作家当参照…</option>
        <option v-for="p in studio.stylePresets" :key="p.id" :value="p.id">
          {{ p.name }} · {{ p.summary }}
        </option>
      </select>
      <span class="sf__hint">{{ localPresets ? '只改本批，不动书默认' : '只借写法，不复制句子' }}</span>
    </div>

    <div class="sf__grid">
      <label class="sf__field">
        <span class="sf__label">视角</span>
        <select v-model="pov" class="sf__select">
          <option v-for="v in withCurrent(POV, pov)" :key="v" :value="v">{{ v || '不指定' }}</option>
        </select>
      </label>
      <label class="sf__field">
        <span class="sf__label">叙述人称</span>
        <select v-model="person" class="sf__select">
          <option v-for="v in withCurrent(PERSON, person)" :key="v" :value="v">{{ v || '不指定' }}</option>
        </select>
      </label>
      <label class="sf__field">
        <span class="sf__label">句长</span>
        <select v-model="sentence" class="sf__select">
          <option v-for="v in withCurrent(SENTENCE, sentence)" :key="v" :value="v">{{ v || '不指定' }}</option>
        </select>
      </label>
      <label class="sf__field">
        <span class="sf__label">段落长度</span>
        <select v-model="paragraph" class="sf__select">
          <option v-for="v in withCurrent(PARAGRAPH, paragraph)" :key="v" :value="v">{{ v || '不指定' }}</option>
        </select>
      </label>
      <label class="sf__field">
        <span class="sf__label">节奏</span>
        <select v-model="rhythm" class="sf__select">
          <option v-for="v in withCurrent(RHYTHM, rhythm)" :key="v" :value="v">{{ v || '不指定' }}</option>
        </select>
      </label>
      <label class="sf__field">
        <span class="sf__label">对话比例</span>
        <select v-model="dialogueRatio" class="sf__select">
          <option v-for="v in withCurrent(DIALOGUE, dialogueRatio)" :key="v" :value="v">{{ v || '不指定' }}</option>
        </select>
      </label>
    </div>

    <Input
      v-model="bannedText"
      label="禁用表达"
      hint="一行一条，最多 30 条；写进细纲与正文提示词。"
      multiline
      :rows="compact ? 3 : 4"
      placeholder="例：他很难过&#10;空气仿佛凝固"
    />

    <div class="sf__samples">
      <div class="sf__sectionhead">
        <span class="sf__label">样章</span>
        <span class="sf__hint">{{ samples.length }} / 3 段 · 最多注入前 2 段</span>
      </div>
      <div v-for="(s, i) in samples" :key="i" class="sf__sample">
        <div class="sf__samplehead">
          <input
            class="sf__input sf__input--label"
            :value="s.label"
            maxlength="12"
            placeholder="标签，如「开场」"
            aria-label="样章标签"
            @input="updateSample(i, 'label', ($event.target as HTMLInputElement).value)"
          />
          <button type="button" class="sf__x" aria-label="删除这段样章" @click="removeSample(i)">✕</button>
        </div>
        <textarea
          class="sf__textarea"
          :value="s.text"
          :rows="compact ? 2 : 3"
          maxlength="800"
          placeholder="粘贴一段 200–500 字的样章…"
          @input="updateSample(i, 'text', ($event.target as HTMLTextAreaElement).value)"
        />
        <p v-if="s.note" class="sf__note">{{ s.note }}</p>
      </div>
      <button v-if="samples.length < 3" type="button" class="sf__add" @click="addSample">＋ 添加样章</button>
    </div>

    <Input
      v-model="referenceText"
      label="参考作者/作品"
      hint="一行一条，最多 5 条；只写风格特征，不复制原文。"
      multiline
      :rows="compact ? 2 : 3"
      placeholder="例：示例作者《示例作品》 冷叙事、短句、少形容词"
    />

    <Input
      v-model="notes"
      label="补充说明"
      hint="≤500 字；例：少用成语；情绪落在动作上；不写总结句。"
      multiline
      :rows="compact ? 2 : 3"
      placeholder="例：少用成语；情绪落在动作上；不写总结句。"
    />
  </div>
</template>

<style scoped>
.sf {
  display: grid;
  gap: var(--ns-s4);
}
.sf__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--ns-s3);
}
.sf--compact .sf__grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.sf__field {
  display: grid;
  gap: 5px;
  min-width: 0;
}
.sf__label {
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  font-weight: 600;
}
.sf__select,
.sf__input,
.sf__textarea {
  width: 100%;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: var(--ns-fs-12);
  padding: 0 9px;
  height: 30px;
}
.sf__select:focus,
.sf__input:focus,
.sf__textarea:focus {
  outline: none;
  border-color: var(--ns-pink);
  box-shadow: var(--ns-focus);
}
.sf__textarea {
  height: auto;
  padding: 8px 9px;
  line-height: 1.7;
  resize: vertical;
}
.sf__hint {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
}
.sf__note {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.sf__preset {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--ns-s3);
  padding: var(--ns-s3);
  border: 1px dashed var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.sf__presetlabel {
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  font-weight: 600;
  white-space: nowrap;
}
.sf__select--preset {
  height: 30px;
}
.sf__samples {
  display: grid;
  gap: var(--ns-s2);
}
.sf__sectionhead {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--ns-s3);
}
.sf__sample {
  display: grid;
  gap: 5px;
  padding: var(--ns-s2);
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
}
.sf__samplehead {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
}
.sf__input--label {
  flex: 1;
  height: 28px;
}
.sf__x {
  flex: none;
  width: 26px;
  height: 26px;
  border: 0;
  border-radius: var(--ns-r-xs);
  background: transparent;
  color: var(--ns-ink-3);
  cursor: pointer;
}
.sf__x:hover {
  background: var(--ns-card-2);
  color: var(--ns-ink);
}
.sf__add {
  justify-self: start;
  border: 1px dashed var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: transparent;
  color: var(--ns-ink-2);
  font: inherit;
  font-size: var(--ns-fs-12);
  padding: 5px 10px;
  cursor: pointer;
}
.sf__add:hover {
  background: var(--ns-card-2);
}
@media (max-width: 760px) {
  .sf__grid,
  .sf--compact .sf__grid {
    grid-template-columns: 1fr;
  }
  .sf__preset {
    grid-template-columns: 1fr;
  }
}
</style>

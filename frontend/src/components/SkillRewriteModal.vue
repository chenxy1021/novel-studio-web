<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Modal } from '@/design'
import GenStream from './GenStream.vue'
import type { AiTells } from '@/api/checkup'
import type { Finding } from '@/api/client'

/** 改写过程实时回显；父组件只在 kind 是 rewrite 时传进来。 */
type RewriteStream = { active: boolean; text: string; stage: string; startedAt: number }

const props = withDefaults(
  defineProps<{
    open: boolean
    chapter: number
    suggested?: string[]
    findings?: Finding[]
    aiTells?: AiTells | null
    busy?: boolean
    error?: string
    stream?: RewriteStream | null
  }>(),
  { suggested: () => [], findings: () => [], aiTells: null, busy: false, error: '', stream: null },
)

const emit = defineEmits<{
  close: []
  submit: [payload: { skills: string[]; instruction: string }]
}>()

type SkillRow = { id: string; label: string; note: string }

const checked = ref<Record<string, boolean>>({})
const instruction = ref('')
const touched = ref(false)

const rows = computed<SkillRow[]>(() => {
  const tells = props.aiTells?.total ?? 0
  const high = props.findings.filter((f) => f.severity === 'high').length
  const voice = props.findings.filter((f) => /口吻|对话|voice|dialogue/i.test(`${f.code} ${f.message}`)).length
  const scene = props.findings.filter((f) => /场景|节奏|概括|scene|pacing/i.test(`${f.code} ${f.message}`)).length
  const hook = props.findings.some((f) => /end-hook|章尾/i.test(`${f.code} ${f.message}`))
  const continuity = props.findings.filter((f) =>
    /continuity|hard-rule|foreshadow|逻辑|吃书|连续/i.test(`${f.code} ${f.message}`),
  ).length
  return [
    { id: 'deai', label: '去 AI 味', note: tells ? `${tells} 处 AI 痕迹` : high ? `${high} 处硬伤` : '保守清理' },
    { id: 'dialogue', label: '对话打磨', note: voice ? `${voice} 条口吻/对话问题` : '当前未命中' },
    { id: 'scene', label: '场景落地', note: scene ? `${scene} 条场景/节奏问题` : '当前未命中' },
    { id: 'hook', label: '章末钩子', note: hook ? '章尾偏弱' : '当前未命中' },
    { id: 'continuity', label: '连续性检查', note: continuity ? `${continuity} 条连续性提醒` : '保守检查' },
    { id: 'styleSamples', label: '文风样本', note: '有样章时校准文风' },
  ]
})

function applySuggested() {
  const preset = new Set(props.suggested)
  checked.value = Object.fromEntries(rows.value.map((r) => [r.id, preset.has(r.id)]))
}

watch(
  () => props.open,
  (open) => {
    if (!open) return
    touched.value = false
    applySuggested()
    instruction.value = ''
  },
  { immediate: true },
)

/** 体检结果可能在弹窗打开后才回来；用户没动过勾选时补上预选。 */
watch(
  () => props.suggested.join(','),
  () => {
    if (props.open && !touched.value) applySuggested()
  },
)

const selected = computed(() => rows.value.filter((r) => checked.value[r.id]).map((r) => r.id))

/** 会写进提示词的问题条目：确定性体检 + AI 复检（后端还会自己再跑一遍体检）。 */
const issues = computed(() => props.findings.filter((f) => f.severity === 'high' || f.severity === 'mid'))
const aiIssueCount = computed(() => issues.value.filter((f) => f.source === 'ai').length)

function toggle(id: string) {
  touched.value = true
  checked.value = { ...checked.value, [id]: !checked.value[id] }
}

function submit() {
  if (props.busy || !selected.value.length) return
  emit('submit', { skills: selected.value, instruction: instruction.value.trim() })
}

</script>

<template>
  <Modal
    :open="open"
    :title="`按技能改写第 ${chapter} 章`"
    width="620px"
    desc="只改命中问题的段落；保留已经发生的情节事实、人物关系和揭示顺序；不新增设定、不新增角色。改完停在待确认。"
    @close="emit('close')"
  >
    <div class="rw">
      <div class="rw__skills">
        <div class="rw__label">这次用哪些技能</div>
        <label v-for="row in rows" :key="row.id" class="rw__skill">
          <input
            type="checkbox"
            :checked="!!checked[row.id]"
            :disabled="busy"
            @change="toggle(row.id)"
          />
          <span class="rw__skillname">{{ row.label }}</span>
          <span class="rw__skillnote">{{ row.note }}</span>
        </label>
        <div class="rw__platform">平台打法：始终开启（平台禁忌不能关）</div>
      </div>

      <p class="rw__issues">
        <template v-if="issues.length">
          会把体检/复检出的 {{ issues.length }} 条问题写进改写要求<template v-if="aiIssueCount">（其中 AI 复检 {{ aiIssueCount }} 条）</template>，让模型照着改。
        </template>
        <template v-else>还没有体检结果：这次只按技能和平台打法改；先点「体检」能把具体问题一起交出去。</template>
      </p>

      <label class="rw__field">
        <span class="rw__label">补充要求（可选）</span>
        <textarea
          v-model="instruction"
          rows="3"
          :disabled="busy"
          placeholder="例：只改第 3、7 段，不要动结尾。"
        />
      </label>

      <GenStream
        v-if="stream && (stream.active || stream.text)"
        :active="stream.active"
        :text="stream.text"
        :stage="stream.stage"
        :started-at="stream.startedAt"
        :title="`第 ${chapter} 章 · 按技能改写`"
        kind="rewrite"
      />

      <p class="rw__footnote">旧稿会进「废章」，可恢复。生成过程会实时显示在上面。</p>
      <p v-if="error" class="rw__error">{{ error }}</p>
      <p v-if="!selected.length" class="rw__warn">至少选一个技能。</p>
    </div>

    <template #footer>
      <Button variant="ghost" :disabled="busy" @click="emit('close')">取消</Button>
      <Button variant="primary" :disabled="busy || !selected.length" @click="submit">
        {{ busy ? '正在按技能改写…' : '开始改写' }}
      </Button>
    </template>
  </Modal>
</template>

<style scoped>
.rw {
  display: flex;
  flex-direction: column;
  gap: var(--ns-s4);
}
.rw__label {
  font-size: var(--ns-fs-12);
  font-weight: 600;
  color: var(--ns-ink-2);
  margin-bottom: var(--ns-s2);
}
.rw__skills {
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  padding: var(--ns-s3);
  background: var(--ns-card-2);
}
.rw__skill {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  padding: 4px 0;
  font-size: var(--ns-fs-13);
  cursor: pointer;
}
.rw__skillname {
  font-weight: 500;
}
.rw__skillnote {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
  margin-left: auto;
  text-align: right;
}
.rw__platform {
  margin-top: var(--ns-s2);
  padding-top: var(--ns-s2);
  border-top: 1px solid var(--ns-line);
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
}
.rw__issues {
  margin: 0;
  padding: var(--ns-s2) var(--ns-s3);
  border-left: 2px solid var(--ns-pink);
  background: var(--ns-card-2);
  border-radius: var(--ns-r-sm);
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  line-height: 1.6;
}
.rw__field {
  display: flex;
  flex-direction: column;
}
.rw__field textarea {
  width: 100%;
  resize: vertical;
  border: 1px solid var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: var(--ns-fs-13);
  line-height: 1.6;
  padding: var(--ns-s2);
}
.rw__field textarea:focus {
  outline: 2px solid var(--ns-pink-soft);
  border-color: var(--ns-pink);
}
.rw__footnote {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
}
.rw__error {
  margin: 0;
  color: var(--ns-bad);
  font-size: var(--ns-fs-12);
}
.rw__warn {
  margin: 0;
  color: var(--ns-warn);
  font-size: var(--ns-fs-12);
}
</style>

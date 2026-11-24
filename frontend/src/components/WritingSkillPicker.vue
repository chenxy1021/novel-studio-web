<script setup lang="ts">
import { computed } from 'vue'
import type { WritingSkills } from '@/api/studio'

type SkillKey = keyof WritingSkills

const props = withDefaults(
  defineProps<{
    modelValue: Partial<WritingSkills>
    nuewenEnabled?: boolean
    hasSamples?: boolean
  }>(),
  { nuewenEnabled: false, hasSamples: true },
)
const emit = defineEmits<{ 'update:modelValue': [Partial<WritingSkills>] }>()

type SkillMeta = {
  id: SkillKey
  name: string
  desc: string
  cost: string
  stage: string
  defaultOn: boolean
}

const SKILLS: SkillMeta[] = [
  {
    id: 'deai',
    name: '去 AI 味',
    desc: '生成后扫 AI 痕迹，命中硬伤时改写一次',
    cost: '命中时最多 +1 次调用',
    stage: '生成后',
    defaultOn: true,
  },
  {
    id: 'dialogue',
    name: '对话打磨',
    desc: '按人物口吻改对话，删解释性对白',
    cost: '不额外调用',
    stage: '正文',
    defaultOn: true,
  },
  {
    id: 'scene',
    name: '场景落地',
    desc: '每一拍写成具体场景，不写旁白概括',
    cost: '不额外调用',
    stage: '细纲 + 正文',
    defaultOn: true,
  },
  {
    id: 'hook',
    name: '章末钩子',
    desc: '章末留信息 / 危险 / 选择型钩子',
    cost: '不额外调用',
    stage: '细纲 + 正文 + 检查',
    defaultOn: true,
  },
  {
    id: 'continuity',
    name: '连续性检查',
    desc: '带入人物状态、关系、伏笔、时间线',
    cost: '不额外调用',
    stage: '细纲 + 正文',
    defaultOn: true,
  },
  {
    id: 'platform',
    name: '平台打法',
    desc: '按平台字数、段落、对话比、禁忌写',
    cost: '不额外调用',
    stage: '细纲 + 正文',
    defaultOn: true,
  },
  {
    id: 'nuewen',
    name: '虐文公式',
    desc: '按「最 X → 最非 X」推进反转与代价',
    cost: '不额外调用',
    stage: '细纲 + 正文',
    defaultOn: false,
  },
  {
    id: 'styleSamples',
    name: '文风样本',
    desc: '把样章作为语感参照',
    cost: '不额外调用',
    stage: '正文',
    defaultOn: true,
  },
]

function isOn(meta: SkillMeta): boolean {
  const value = props.modelValue[meta.id]
  if (typeof value === 'boolean') return value
  if (meta.id === 'nuewen') return props.nuewenEnabled
  return meta.defaultOn
}

function isDisabled(meta: SkillMeta): boolean {
  return meta.id === 'nuewen' && !props.nuewenEnabled
}

function toggle(meta: SkillMeta) {
  if (isDisabled(meta)) return
  emit('update:modelValue', { ...props.modelValue, [meta.id]: !isOn(meta) })
}

const enabledCount = computed(() => SKILLS.filter((m) => isOn(m)).length)
const costHint = computed(() => {
  const deai = isOn(SKILLS[0])
  return deai
    ? '本批 1 次细纲 + 每章 1 次正文，命中时再加 1 次去 AI 味改写'
    : '本批 1 次细纲 + 每章 1 次正文，不额外改写'
})

defineExpose({ enabledCount, costHint })
</script>

<template>
  <div class="sk">
    <p class="sk__lead">决定这一批用哪些方法写、写完后检查什么。默认值按书记住；下面的改动只作用于这一批。</p>

    <ul class="sk__list">
      <li
        v-for="meta in SKILLS"
        :key="meta.id"
        class="sk__row"
        :class="{ 'sk__row--off': isDisabled(meta), 'sk__row--unavailable': meta.id === 'styleSamples' && !hasSamples }"
      >
        <label class="sk__main">
          <input
            type="checkbox"
            class="sk__check"
            :checked="isOn(meta)"
            :disabled="isDisabled(meta)"
            @change="toggle(meta)"
          />
          <span class="sk__text">
            <span class="sk__name">{{ meta.name }}</span>
            <span class="sk__desc">{{ meta.desc }}</span>
            <span class="sk__meta">
              <span>默认{{ meta.defaultOn ? '开' : '关' }}</span>
              <span>· {{ meta.cost }}</span>
              <span>· {{ meta.stage }}</span>
            </span>
          </span>
        </label>
        <span v-if="meta.id === 'nuewen' && !nuewenEnabled" class="sk__note">未开启虐文模式</span>
        <span v-else-if="meta.id === 'styleSamples' && !hasSamples" class="sk__note">无样章，开启也不生效</span>
      </li>
    </ul>

    <p class="sk__foot">
      已开 {{ enabledCount }} / 8 · {{ costHint }}
    </p>
  </div>
</template>

<style scoped>
.sk {
  display: grid;
  gap: var(--ns-s3);
}
.sk__lead,
.sk__foot {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  line-height: 1.7;
}
.sk__list {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.sk__row {
  display: flex;
  align-items: flex-start;
  gap: var(--ns-s3);
  padding: 7px 8px;
  border-radius: var(--ns-r-sm);
}
.sk__row:hover {
  background: var(--ns-card-2);
}
.sk__row--off {
  opacity: 0.55;
}
.sk__row--unavailable .sk__name {
  color: var(--ns-ink-3);
}
.sk__main {
  display: flex;
  align-items: flex-start;
  gap: var(--ns-s3);
  flex: 1;
  min-width: 0;
  cursor: pointer;
}
.sk__row--off .sk__main {
  cursor: not-allowed;
}
.sk__check {
  flex: none;
  width: 16px;
  height: 16px;
  margin: 2px 0 0;
  accent-color: var(--ns-pink);
}
.sk__text {
  display: grid;
  gap: 2px;
  min-width: 0;
}
.sk__name {
  color: var(--ns-ink);
  font-size: var(--ns-fs-12);
  font-weight: 600;
}
.sk__desc {
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  line-height: 1.55;
}
.sk__meta {
  color: var(--ns-ink-4);
  font-size: var(--ns-fs-11);
  font-variant-numeric: tabular-nums;
}
.sk__note {
  flex: none;
  color: var(--ns-warn);
  font-size: var(--ns-fs-11);
  white-space: nowrap;
}
</style>

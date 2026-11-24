<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Tag } from '@/design'
import GenStream from './GenStream.vue'
import type { AiCheckResult, CheckResult, RuleCheck, TellCategory } from '@/api/checkup'
import { AI_GROUPS, SEVERITY_LABEL, SEVERITY_TONE } from '@/api/checkup'
import type { Finding } from '@/api/client'

type AiStream = { active: boolean; stage: string; reason: string; startedAt: number }

const props = withDefaults(
  defineProps<{
    chapter: number
    result: CheckResult | AiCheckResult | null
    loading?: boolean
    aiLoading?: boolean
    stale?: boolean
    canRewrite?: boolean
    /** AI 复检的实时思考过程；父组件只在 kind 是 ai-check 时传进来。 */
    aiStream?: AiStream | null
  }>(),
  { loading: false, aiLoading: false, stale: false, canRewrite: true, aiStream: null },
)

const emit = defineEmits<{
  close: []
  refresh: []
  'ai-check': []
  rewrite: []
  locate: [payload: { text: string; paragraph: number; offset: number }]
}>()

const open = ref<Record<string, boolean>>({})
const showRules = ref(true)

const aiResult = computed<AiCheckResult | null>(() =>
  props.result && 'groups' in props.result ? (props.result as AiCheckResult) : null,
)

/** 这次复检对照了哪些跨章材料，给作者一个明确的检查范围。 */
const semContext = computed(() => {
  const ctx = aiResult.value?.context
  if (!ctx) return ''
  const parts: string[] = []
  if (ctx.priorChapters > 0) parts.push(`前 ${ctx.priorChapters} 章记忆`)
  if (ctx.prevTail) parts.push('上一章结尾')
  if (ctx.outline) parts.push('本章细纲')
  return parts.length ? `对照范围：${parts.join(' · ')}` : ''
})

const tells = computed(() => props.result?.aiTells)
const categories = computed<TellCategory[]>(() => {
  const rank = { high: 0, mid: 1, low: 2 }
  return [...(tells.value?.categories ?? [])].sort(
    (a, b) => rank[a.severity] - rank[b.severity] || b.count - a.count,
  )
})

const hardCount = computed(() => props.result?.findings.filter((f) => f.severity === 'high').length ?? 0)
const midCount = computed(() => props.result?.findings.filter((f) => f.severity === 'mid').length ?? 0)
const restCount = computed(
  () => props.result?.findings.filter((f) => f.severity !== 'high' && f.severity !== 'mid').length ?? 0,
)

const rules = computed<RuleCheck[]>(() => props.result?.rules ?? [])

/** 硬伤分类默认展开；其余折叠，避免一屏全是字。 */
watch(
  categories,
  (list) => {
    const next = { ...open.value }
    for (const c of list) if (!(c.id in next)) next[c.id] = c.severity === 'high'
    open.value = next
  },
  { immediate: true },
)

function toggle(id: string) {
  open.value = { ...open.value, [id]: !open.value[id] }
}

function short(text: string, max = 40) {
  const t = String(text || '').trim()
  return t.length > max ? `${t.slice(0, max)}…` : t
}

function locate(sample: { text: string; paragraph: number; offset: number }) {
  emit('locate', sample)
}

function ruleTone(state: RuleCheck['state']): 'ok' | 'warn' | 'bad' {
  return state
}

function groupFindings(code: string): Finding[] {
  return aiResult.value?.groups.find((g) => g.code === code)?.findings ?? []
}

function groupCount(code: string): number {
  return groupFindings(code).length
}

const semanticTotal = computed(() =>
  AI_GROUPS.reduce((sum, g) => sum + groupCount(g.code), 0),
)
</script>

<template>
  <section class="chk" :class="{ 'chk--busy': loading }" :aria-label="`第 ${chapter} 章体检`">
    <header class="chk__head">
      <div class="chk__title">
        <b>第 {{ chapter }} 章 · 体检</b>
        <Tag v-if="stale" size="sm" tone="warn">结果基于旧稿</Tag>
        <Tag v-if="result" size="sm" :tone="hardCount ? 'bad' : midCount ? 'warn' : 'ok'">
          {{ hardCount ? `${hardCount} 硬伤` : midCount ? `${midCount} 需改` : '体检通过' }}
        </Tag>
      </div>
      <div class="chk__headacts">
        <Button size="sm" variant="ghost" :disabled="loading" @click="emit('refresh')">
          {{ loading ? '体检中…' : '重新体检' }}
        </Button>
        <Button size="sm" variant="ghost" @click="emit('close')">关闭</Button>
      </div>
    </header>

    <div v-if="!result && !loading" class="chk__empty">
      <b>还没体检</b>
      <p>确定性体检不调模型，几秒出结果。</p>
      <Button size="sm" variant="primary" @click="emit('refresh')">开始体检</Button>
    </div>
    <div v-else-if="!result" class="chk__empty">
      <b>体检中…</b>
      <p>正在跑本地规则，不调模型。</p>
    </div>

    <template v-else-if="result">
      <div class="chk__conclusion">
        结论：{{ hardCount }} 硬伤 · {{ midCount }} 需改 · {{ restCount }} 提醒
        <span v-if="tells"> · AI 痕迹：{{ tells.level }} · {{ tells.total }} 处 · 密度 {{ tells.density }}/千字</span>
      </div>

      <div class="chk__block">
        <div class="chk__blockhead">
          <b>确定性体检</b>
          <span class="chk__hint">不调模型；分类、次数、样例与定位都来自本地规则</span>
        </div>

        <div v-if="!categories.length" class="chk__ok">没有命中 AI 痕迹规则。</div>
        <div v-for="cat in categories" :key="cat.id" class="chk__cat">
          <button type="button" class="chk__cathead" :aria-expanded="!!open[cat.id]" @click="toggle(cat.id)">
            <span class="chk__caret">{{ open[cat.id] ? '▾' : '▸' }}</span>
            <span class="chk__catname">{{ cat.label }}</span>
            <span class="chk__count">{{ cat.count }} 次</span>
            <Tag size="sm" :tone="SEVERITY_TONE[cat.severity]">{{ SEVERITY_LABEL[cat.severity] }}</Tag>
          </button>
          <ul v-if="open[cat.id]" class="chk__samples">
            <li v-for="(s, i) in cat.samples.slice(0, 2)" :key="i" class="chk__sample">
              <span class="chk__quote">「{{ short(s.text) }}」</span>
              <span class="chk__where">第 {{ s.paragraph || '?' }} 段 · 第 {{ (s.offset ?? 0) + 1 }} 字</span>
              <button type="button" class="chk__locate" @click="locate(s)">定位</button>
            </li>
            <li v-if="cat.samples.length > 2" class="chk__more">
              还有 {{ cat.samples.length - 2 }} 条样例，低于 40 字的不再展开
            </li>
          </ul>
        </div>

        <div v-if="rules.length" class="chk__rules">
          <button type="button" class="chk__ruleshead" @click="showRules = !showRules">
            {{ showRules ? '▾' : '▸' }} 其他确定性检查
          </button>
          <div v-if="showRules" class="chk__rulegrid">
            <div v-for="r in rules" :key="r.id" class="chk__rule">
              <Tag size="sm" :tone="ruleTone(r.state)">{{ r.label }}</Tag>
              <span>{{ r.message || r.label }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="chk__block">
        <div class="chk__blockhead">
          <b>AI 语义复检</b>
          <span v-if="aiResult" class="chk__hint">六类：吃书 / 动机 / 口吻 / 对话 / 信息重复 / 情绪总结</span>
        </div>

        <GenStream
          v-if="aiStream && (aiStream.active || aiStream.reason)"
          :active="aiStream.active"
          text=""
          :reason="aiStream.reason"
          :stage="aiStream.stage"
          :started-at="aiStream.startedAt"
          :title="`第 ${chapter} 章 · AI 复检`"
          kind="ai-check"
        />

        <div v-if="!aiResult" class="chk__semempty">
          <p>还没做语义复检。模型会读本章，并对照前情提要、上一章结尾和本章细纲，找吃书、动机、口吻、对话、信息重复、情绪总结。约 1–2 分钟，会记一次用量。</p>
          <Button size="sm" :disabled="aiLoading" @click="emit('ai-check')">
            {{ aiLoading ? 'AI 复检中…' : 'AI 复检' }}
          </Button>
        </div>
        <template v-else>
          <p v-if="semContext" class="chk__scope">{{ semContext }}</p>
          <div v-if="!semanticTotal" class="chk__ok">六类语义问题都没发现。</div>
          <div v-for="g in AI_GROUPS" :key="g.code" class="chk__group">
            <div class="chk__grouphead">
              <b>{{ g.label }}</b>
              <span class="chk__count">{{ groupCount(g.code) }} 条</span>
            </div>
            <ul v-if="groupCount(g.code)" class="chk__findings">
              <li v-for="(f, i) in groupFindings(g.code)" :key="i" class="chk__finding">
                <Tag size="sm" :tone="SEVERITY_TONE[f.severity]">{{ SEVERITY_LABEL[f.severity] }}</Tag>
                <div>
                  <b>{{ f.message }}</b>
                  <p v-if="f.hint">{{ f.hint }}</p>
                </div>
              </li>
            </ul>
          </div>
          <div class="chk__semfoot">
            <Button size="sm" variant="ghost" :disabled="aiLoading" @click="emit('ai-check')">
              {{ aiLoading ? 'AI 复检中…' : '重新 AI 复检' }}
            </Button>
          </div>
        </template>
      </div>

      <footer class="chk__foot">
        <span class="chk__footnote">旧稿会进「废章」，可恢复；改完停在待确认。</span>
        <Button
          size="sm"
          variant="primary"
          :disabled="!canRewrite || loading || aiLoading"
          @click="emit('rewrite')"
        >
          按技能改写
        </Button>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.chk {
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-lg);
  background: var(--ns-card);
  overflow: hidden;
}
.chk--busy {
  opacity: 0.72;
  pointer-events: none;
}
.chk__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ns-s3);
  padding: var(--ns-s3) var(--ns-s4);
  border-bottom: 1px solid var(--ns-line);
  background: var(--ns-card-2);
}
.chk__title {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  flex-wrap: wrap;
}
.chk__headacts {
  display: flex;
  gap: var(--ns-s1);
}
.chk__empty,
.chk__semempty {
  padding: var(--ns-s5);
  display: flex;
  flex-direction: column;
  gap: var(--ns-s2);
  align-items: flex-start;
  color: var(--ns-ink-2);
}
.chk__empty p,
.chk__semempty p {
  margin: 0;
  font-size: var(--ns-fs-13);
  line-height: 1.6;
}
.chk__conclusion {
  padding: var(--ns-s2) var(--ns-s4);
  border-bottom: 1px solid var(--ns-line);
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-2);
  font-variant-numeric: tabular-nums;
}
.chk__block {
  padding: var(--ns-s3) var(--ns-s4);
  border-bottom: 1px solid var(--ns-line);
}
.chk__blockhead {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--ns-s3);
  margin-bottom: var(--ns-s2);
}
.chk__hint {
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
}
.chk__scope {
  margin: 0 0 var(--ns-s2);
  padding: 4px 9px;
  border-left: 2px solid var(--ns-pink);
  background: var(--ns-card-2);
  border-radius: var(--ns-r-sm);
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-2);
}
.chk__ok {
  font-size: var(--ns-fs-13);
  color: var(--ns-ok);
}
.chk__cat {
  border-top: 1px solid var(--ns-line);
}
.chk__cathead {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  padding: var(--ns-s2) 0;
  background: none;
  border: 0;
  color: var(--ns-ink);
  font: inherit;
  font-size: var(--ns-fs-13);
  cursor: pointer;
  text-align: left;
}
.chk__caret {
  width: 12px;
  color: var(--ns-ink-3);
}
.chk__catname {
  font-weight: 600;
}
.chk__count {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-12);
  font-variant-numeric: tabular-nums;
  margin-left: auto;
}
.chk__samples {
  list-style: none;
  margin: 0 0 var(--ns-s2);
  padding: 0 0 0 20px;
}
.chk__sample {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  padding: 3px 0;
  font-size: var(--ns-fs-12);
}
.chk__quote {
  color: var(--ns-ink);
}
.chk__where {
  color: var(--ns-ink-3);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.chk__locate {
  border: 0;
  background: none;
  color: var(--ns-pink);
  font: inherit;
  font-size: var(--ns-fs-12);
  cursor: pointer;
  padding: 0 2px;
}
.chk__more {
  color: var(--ns-ink-3);
  font-size: var(--ns-fs-11);
  padding-top: 2px;
}
.chk__rules {
  margin-top: var(--ns-s2);
  border-top: 1px solid var(--ns-line);
  padding-top: var(--ns-s2);
}
.chk__ruleshead {
  border: 0;
  background: none;
  color: var(--ns-ink-2);
  font: inherit;
  font-size: var(--ns-fs-12);
  cursor: pointer;
  padding: 0;
}
.chk__rulegrid {
  display: grid;
  gap: 4px;
  margin-top: var(--ns-s2);
}
.chk__rule {
  display: flex;
  align-items: baseline;
  gap: var(--ns-s2);
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-2);
}
.chk__group {
  border-top: 1px solid var(--ns-line);
  padding: var(--ns-s2) 0;
}
.chk__grouphead {
  display: flex;
  align-items: center;
  gap: var(--ns-s2);
  font-size: var(--ns-fs-13);
}
.chk__findings {
  list-style: none;
  margin: var(--ns-s2) 0 0;
  padding: 0;
  display: grid;
  gap: var(--ns-s2);
}
.chk__finding {
  display: flex;
  gap: var(--ns-s2);
  align-items: flex-start;
  font-size: var(--ns-fs-12);
  line-height: 1.55;
}
.chk__finding p {
  margin: 2px 0 0;
  color: var(--ns-ink-2);
}
.chk__semfoot {
  padding-top: var(--ns-s2);
}
.chk__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ns-s3);
  padding: var(--ns-s3) var(--ns-s4);
}
.chk__footnote {
  font-size: var(--ns-fs-11);
  color: var(--ns-ink-3);
}
</style>

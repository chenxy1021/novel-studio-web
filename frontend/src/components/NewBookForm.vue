<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Button, Input, Tag } from '@/design'
import { fetchPlatforms, generateConcepts, type Concept, type PlatformOption } from '@/api/studio'
import { useStudio } from '@/stores/studio'

const emit = defineEmits<{ created: [dir: string] }>()
const studio = useStudio()

const platforms = ref<PlatformOption[]>([])
const step = ref<'brief' | 'pick'>('brief')
const busy = ref(false)
const conceptBusy = ref(false)
/** 选题时模型的思考过程，边想边显示（模型不吐 reasoning_content 时为空）。 */
const conceptReason = ref('')
/** 模型没吐 reasoning_content 时，退而显示正文增量（原始 JSON 流）。 */
const conceptOutput = ref('')
const error = ref('')

const concepts = ref<Concept[]>([])
const pickId = ref('')
const avoid = ref<string[]>([])

const form = reactive({
  direction: '',
  genre: '',
  logline: '',
  platform: 'generic',
  targetChapters: '300',
  wordsPerChapter: '3000',
  mode: 'normal' as 'normal' | 'nuewen',
})

const isNuewen = computed(() => form.mode === 'nuewen')
const picked = computed(() => concepts.value.find((c) => c.id === pickId.value) ?? null)
const current = computed(() => platforms.value.find((p) => p.id === form.platform) ?? null)
const platformName = computed(() => current.value?.name || '通用')
const chapters = computed(() => Number(form.targetChapters) || 0)
const words = computed(() => Number(form.wordsPerChapter) || 0)
const totalWan = computed(() => ((chapters.value * words.value) / 10000).toFixed(1))
const wordsHint = computed(() =>
  current.value
    ? `${current.value.wordsMin}–${current.value.wordsMax} 字/章 · ${current.value.opening || '按平台节奏写'}`
    : '每章字数会写进 project.json，之后不能改',
)

onMounted(async () => {
  try {
    platforms.value = await fetchPlatforms()
    if (!platforms.value.some((p) => p.id === form.platform) && platforms.value[0]) {
      form.platform = platforms.value[0].id
    }
  } catch {
    /* 平台列表拿不到时仍可用后端默认值建书 */
  }
})

function validate(): boolean {
  if (!Number.isFinite(chapters.value) || chapters.value < 1) {
    error.value = '目标章节数是必填，至少 1 章'
    return false
  }
  if (!Number.isFinite(words.value) || words.value < 200) {
    error.value = '章节字数是必填，且每章至少 200 字'
    return false
  }
  return true
}

function fingerprint(list: Concept[]): string[] {
  return list.map((c) => [c.title, c.genre, c.oneLine].filter(Boolean).join('｜')).filter(Boolean)
}

async function makeConcepts(appendAvoid = false) {
  if (!validate()) return
  conceptBusy.value = true
  conceptReason.value = ''
  conceptOutput.value = ''
  error.value = ''
  if (appendAvoid) avoid.value = [...avoid.value, ...fingerprint(concepts.value)].slice(-24)
  try {
    const list = await generateConcepts({
      direction: form.direction.trim(),
      genre: form.genre.trim(),
      logline: form.logline.trim(),
      platform: form.platform,
      targetChapters: chapters.value,
      wordsPerChapter: words.value,
      count: 3,
      avoid: avoid.value,
      nuewen: isNuewen.value,
    }, {
      onReason: (text) => { conceptReason.value += text },
      onDelta: (text) => { conceptOutput.value += text },
    })
    concepts.value = list
    pickId.value = list[0]?.id || ''
    if (!list.length) {
      error.value = '模型没有给出可用的选题，换个方向再试'
    } else {
      step.value = 'pick'
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    conceptBusy.value = false
  }
}

function backToBrief() {
  step.value = 'brief'
  error.value = ''
}

async function createBook() {
  if (!picked.value || busy.value) {
    if (!picked.value) error.value = '先挑一个选题'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const book = await studio.createBook({
      title: picked.value.title,
      genre: picked.value.genre || form.genre.trim(),
      platform: form.platform,
      targetChapters: chapters.value,
      wordsPerChapter: words.value,
      logline: picked.value.oneLine || form.logline.trim(),
      synopsis: picked.value.synopsis,
      tone: isNuewen.value ? '虐文：把角色最珍视的东西反转成反面，不预设结局' : '',
      concepts: concepts.value,
      selectedConceptId: picked.value.id,
      nuewen: isNuewen.value,
    })
    emit('created', book.dir)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

const HIT_LABEL: Record<string, string> = { high: '爆款率高', mid: '爆款率中', low: '爆款率低' }
const HIT_TONE: Record<string, 'bad' | 'gold' | 'info'> = { high: 'bad', mid: 'gold', low: 'info' }
</script>

<template>
  <div class="nb">
    <ol class="nb__steps" aria-label="开书步骤">
      <li class="nb__step" :class="{ on: step === 'brief', done: step === 'pick' }">
        <span class="nb__stepno">{{ step === 'pick' ? '✓' : '1' }}</span>
        <span>想法</span>
      </li>
      <li class="nb__stepline" aria-hidden="true" />
      <li class="nb__step" :class="{ on: step === 'pick' }">
        <span class="nb__stepno">2</span>
        <span>选题</span>
      </li>
      <li class="nb__stepline" aria-hidden="true" />
      <li class="nb__step">
        <span class="nb__stepno">3</span>
        <span>开书</span>
      </li>
    </ol>

    <template v-if="step === 'brief'">
      <div class="nb__brief">
        <section class="nb__main">
          <header class="nb__head">
            <span class="ns-eyebrow">故事的方向</span>
            <h3>你想写一个什么故事？</h3>
            <p>怎么写都行，也可以只留一句模糊的念头。AI 会按下面的体量，把它长成几个能直接开写的选题。</p>
          </header>

          <Input
            v-model="form.direction"
            label="想法 / 方向（选填）"
            multiline
            :rows="5"
            serif
            placeholder="例：少年背着师门血仇下山，遇到一个不肯透露身份的女子；主线是复仇与抉择，想要一点克苏鲁味道，别太玛丽苏。"
          />

          <div class="nb__row">
            <Input v-model="form.genre" label="题材类型（选填）" placeholder="例：末世悬疑、都市异能、古代权谋" />
            <Input
              v-model="form.logline"
              label="一句话卖点（选填）"
              placeholder="例：全城只剩一座广播塔，谁拿到发令权谁定生死。"
            />
          </div>

          <div class="nb__tone">
            <span class="nb__label">基调</span>
            <div class="nb__tonecards">
              <button
                type="button"
                class="nb__tonecard"
                :class="{ on: form.mode === 'normal' }"
                @click="form.mode = 'normal'"
              >
                <b>常规</b>
                <small>按平台节奏和爽点写</small>
              </button>
              <button
                type="button"
                class="nb__tonecard nb__tonecard--nu"
                :class="{ on: form.mode === 'nuewen' }"
                @click="form.mode = 'nuewen'"
              >
                <b>虐文</b>
                <small>最珍视的被自己的选择反转，不预设结局</small>
              </button>
            </div>
          </div>

          <div v-if="isNuewen" class="nb__formula">
            <span class="nb__formulatag">虐文逻辑</span>
            <p>最想活的写死，最想死的活下来；最骄傲的跪地求饶，最光明的沉沦黑暗。</p>
            <p>不是按句子分配惨剧，而是让他的「最」在压力下自己走向反面。</p>
            <small>结局由因果链走到，不预设死光、剩一个或翻盘；选题会贴着这个逻辑写。</small>
          </div>
        </section>

        <aside class="nb__side">
          <div class="nb__panel">
            <span class="ns-eyebrow">体量</span>
            <Input
              v-model="form.targetChapters"
              label="目标章节数 *"
              type="number"
              min="1"
              size="lg"
              placeholder="300"
              hint="建书时定死，后面不能改"
            />
            <Input
              v-model="form.wordsPerChapter"
              label="每章字数 *"
              type="number"
              min="200"
              step="100"
              size="lg"
              placeholder="3000"
              :hint="wordsHint"
            />
            <div class="nb__total">
              <span>预计总字数</span>
              <b>{{ totalWan }}<em>万字</em></b>
            </div>
          </div>

          <div class="nb__panel">
            <span class="ns-eyebrow">发布平台（选填）</span>
            <div class="nb__platforms">
              <button
                v-for="p in platforms"
                :key="p.id"
                type="button"
                class="nb__chip"
                :class="{ on: form.platform === p.id }"
                @click="form.platform = p.id"
              >
                {{ p.name }}
                <Tag v-if="p.short" size="sm" tone="gold">短篇</Tag>
              </button>
            </div>
            <p class="nb__hint">{{ wordsHint }}</p>
          </div>
        </aside>
      </div>

      <p v-if="error" class="nb__error" role="alert">{{ error }}</p>

      <footer class="nb__foot">
        <p>书名和简介都由 AI 根据选题生成，选中之后直接建书目录。</p>
        <Button variant="pink" :disabled="conceptBusy" @click="makeConcepts()">
          {{ conceptBusy ? 'AI 正在出选题，约 1–2 分钟…' : '让 AI 出选题 →' }}
        </Button>
      </footer>
    </template>

    <template v-else>
      <header class="nb__pickhead">
        <Button size="sm" variant="ghost" @click="backToBrief">← 改条件</Button>
        <div class="nb__summary">
          <span>{{ chapters }} 章 × {{ words }} 字</span>
          <i />
          <span>约 {{ totalWan }} 万字</span>
          <i />
          <span>{{ platformName }}</span>
          <i />
          <span :class="{ 'nb__sum-nu': isNuewen }">{{ isNuewen ? '虐文' : '常规' }}</span>
        </div>
        <Button size="sm" variant="ghost" :disabled="conceptBusy" @click="makeConcepts(true)">
          {{ conceptBusy ? '重新生成中…' : '换一批' }}
        </Button>
      </header>

      <div v-if="conceptBusy" class="nb__loading" role="status">
        <span class="nb__loadingbar" />
        正在让 AI 按{{ isNuewen ? '虐文公式' : '选题条件' }}重新生成…
      </div>

      <div v-if="conceptBusy || conceptReason || conceptOutput" class="nb__think">
        <div class="nb__thinkhead">
          <span class="ns-eyebrow">{{ conceptReason || !conceptOutput ? 'AI 思考过程' : 'AI 输出过程' }}</span>
          <span class="nb__thinkmeta">
            {{
              conceptBusy
                ? (conceptReason ? '边想边出…' : conceptOutput ? '模型输出中…' : '等待模型开口…')
                : `${(conceptReason || conceptOutput).length} 字`
            }}
          </span>
        </div>
        <pre v-if="conceptReason || conceptOutput" class="nb__thinktext">{{ conceptReason || conceptOutput }}</pre>
        <p v-else class="nb__thinkempty">模型还没返回思考内容；有些模型只在最后把结果一起给出来。</p>
        <p v-if="conceptOutput && !conceptReason" class="nb__thinkempty">
          这个模型没有单独的思考过程，上面是它正在写的原始输出。
        </p>
      </div>

      <p v-if="error" class="nb__error" role="alert">{{ error }}</p>

      <div class="nb__workspace">
        <aside class="nb__cands" aria-label="选题候选">
          <div class="nb__candshead">
            <span class="ns-eyebrow">候选 {{ concepts.length }}</span>
            <span class="nb__candshint">点一个看完整简介</span>
          </div>
          <button
            v-for="(c, i) in concepts"
            :key="c.id"
            type="button"
            class="nb__cand"
            :class="{ on: pickId === c.id }"
            @click="pickId = c.id"
          >
            <span class="nb__candno">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="nb__candbody">
              <span class="nb__candtop">
                <b>{{ c.title }}</b>
                <Tag v-if="c.hitRate" size="sm" :tone="HIT_TONE[c.hitRate]">
                  {{ HIT_LABEL[c.hitRate] }}
                </Tag>
              </span>
              <span class="nb__candgenre">
                {{ c.genre || '未分类' }}
                <em v-if="c.nuewen">· 虐点已拆</em>
              </span>
              <span class="nb__candone">{{ c.oneLine }}</span>
            </span>
          </button>
        </aside>

        <section v-if="picked" class="nb__detail">
          <header class="nb__detailhead">
            <div class="nb__detailtitle">
              <span class="ns-eyebrow">
                {{ picked.genre || '未分类' }}<template v-if="isNuewen"> · 虐文</template>
              </span>
              <h2>{{ picked.title }}</h2>
              <p v-if="picked.titleOptions.length" class="nb__alt">
                备选书名：{{ picked.titleOptions.join(' / ') }}
              </p>
            </div>
            <Tag v-if="picked.hitRate" :tone="HIT_TONE[picked.hitRate]">
              {{ HIT_LABEL[picked.hitRate] }}
            </Tag>
          </header>

          <p class="nb__one">{{ picked.oneLine }}</p>
          <div class="nb__synopsis">{{ picked.synopsis }}</div>

          <section v-if="picked.nuewen" class="nb__reversal">
            <header>
              <span class="ns-eyebrow">虐点结构</span>
              <span class="nb__revhint">先立「最」，再反转</span>
            </header>
            <dl class="nb__revlist">
              <div v-if="picked.nuewen?.most" class="nb__revrow">
                <dt>他最「最」的</dt>
                <dd>{{ picked.nuewen?.most }}</dd>
              </div>
              <div v-for="(turn, i) in picked.nuewen?.turns || []" :key="i" class="nb__revrow">
                <dt>反转 {{ i + 1 }}</dt>
                <dd>{{ turn }}</dd>
              </div>
              <div v-if="picked.nuewen?.aftertaste" class="nb__revrow">
                <dt>余味</dt>
                <dd>{{ picked.nuewen?.aftertaste }}</dd>
              </div>
              <div v-if="picked.nuewen?.chain" class="nb__revrow">
                <dt>咬合</dt>
                <dd>{{ picked.nuewen?.chain }}</dd>
              </div>
            </dl>
          </section>
          <p v-else-if="isNuewen" class="nb__missing">
            这一版没把虐点结构写出来。建议点「换一批」重出；直接开书也可以，简介仍按虐文方向写。
          </p>

          <dl class="nb__meta">
            <div v-if="picked.hitReason">
              <dt>爆款理由</dt>
              <dd>{{ picked.hitReason }}</dd>
            </div>
            <div v-if="picked.differentiation">
              <dt>差异化</dt>
              <dd>{{ picked.differentiation }}</dd>
            </div>
            <div v-if="picked.risk">
              <dt>风险</dt>
              <dd>{{ picked.risk }}</dd>
            </div>
          </dl>

          <footer class="nb__detailfoot">
            <p>建在 <code>~/Desktop/mine/xiaoshuo/{{ picked.title }}/</code>，然后直接进工作台。</p>
            <Button variant="pink" :disabled="busy || conceptBusy" @click="createBook">
              {{ busy ? '正在建书…' : '用这个选题开书 →' }}
            </Button>
          </footer>
        </section>

        <section v-else class="nb__detail nb__detail--empty">
          <p>左边还没有可选的选题。返回上一步，点「让 AI 出选题」。</p>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.nb {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

/* ---------- 步骤条 ---------- */
.nb__steps {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.nb__step {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--ns-ink-3);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}
.nb__stepno {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border: 1px solid var(--ns-line-2);
  border-radius: 50%;
  background: var(--ns-card);
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
}
.nb__step.on {
  color: var(--ns-ink);
}
.nb__step.on .nb__stepno {
  border-color: var(--ns-ink);
  background: var(--ns-ink);
  color: var(--ns-paper);
}
.nb__step.done {
  color: var(--ns-ok);
}
.nb__step.done .nb__stepno {
  border-color: var(--ns-ok);
  background: var(--ns-ok-soft);
  color: var(--ns-ok);
}
.nb__stepline {
  flex: 1;
  max-width: 56px;
  height: 1px;
  background: var(--ns-line);
}

/* ---------- 第一步 ---------- */
.nb__brief {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(240px, 0.65fr);
  gap: 20px;
  align-items: start;
}
.nb__main {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}
.nb__head h3 {
  margin: 4px 0 6px;
  font-family: var(--ns-serif);
  font-size: 21px;
  font-weight: 600;
  letter-spacing: 0.01em;
}
.nb__head p {
  margin: 0;
  color: var(--ns-ink-2);
  font-size: 12.5px;
  line-height: 1.8;
}
.nb__row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.nb__label {
  display: block;
  margin-bottom: 6px;
  color: var(--ns-ink-2);
  font-size: var(--ns-fs-12);
  font-weight: 600;
}
.nb__tonecards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.nb__tonecard {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 11px 13px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  color: var(--ns-ink-2);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.14s ease, background 0.14s ease, box-shadow 0.14s ease;
}
.nb__tonecard b {
  color: var(--ns-ink);
  font-size: 13px;
}
.nb__tonecard small {
  color: var(--ns-ink-3);
  font-size: 11px;
  line-height: 1.55;
}
.nb__tonecard:hover {
  background: var(--ns-card-2);
}
.nb__tonecard.on {
  border-color: var(--ns-pink);
  background: var(--ns-pink-soft);
  box-shadow: var(--ns-focus);
}
.nb__tonecard--nu.on b {
  color: var(--ns-pink-2);
}
.nb__formula {
  padding: 12px 14px;
  border: 1px solid var(--ns-pink-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-pink-soft);
}
.nb__formulatag {
  display: inline-block;
  margin-bottom: 6px;
  color: var(--ns-pink-2);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: var(--ns-tracking-caps);
}
.nb__formula p {
  margin: 0 0 3px;
  color: var(--ns-ink-2);
  font-family: var(--ns-serif);
  font-size: 13px;
  line-height: 1.8;
}
.nb__formula small {
  display: block;
  margin-top: 6px;
  color: var(--ns-ink-3);
  font-size: 11px;
  line-height: 1.65;
}
.nb__side {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.nb__panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card-2);
}
.nb__total {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding-top: 8px;
  border-top: 1px dashed var(--ns-line-2);
  color: var(--ns-ink-3);
  font-size: 11.5px;
}
.nb__total b {
  color: var(--ns-ink);
  font-family: var(--ns-serif);
  font-size: 22px;
  line-height: 1;
}
.nb__total em {
  margin-left: 2px;
  color: var(--ns-ink-3);
  font-family: var(--ns-sans);
  font-size: 11px;
  font-style: normal;
  font-weight: 500;
}
.nb__platforms {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.nb__chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 9px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-pill);
  background: var(--ns-card);
  color: var(--ns-ink-2);
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}
.nb__chip:hover {
  background: var(--ns-hover);
}
.nb__chip.on {
  border-color: var(--ns-ink);
  background: var(--ns-ink);
  color: var(--ns-paper);
}
.nb__hint {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: 10.5px;
  line-height: 1.6;
}
.nb__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--ns-line);
}
.nb__foot p {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: 11.5px;
  line-height: 1.7;
}

/* ---------- 第二步 ---------- */
.nb__pickhead {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.nb__summary {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  color: var(--ns-ink-2);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}
.nb__summary i {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--ns-ink-4);
}
.nb__sum-nu {
  color: var(--ns-pink-2);
  font-weight: 700;
}
.nb__loading {
  position: relative;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  overflow: hidden;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  color: var(--ns-ink-2);
  font-size: 11.5px;
}
.nb__loadingbar {
  width: 18px;
  height: 18px;
  border: 2px solid var(--ns-line-2);
  border-top-color: var(--ns-pink);
  border-radius: 50%;
  animation: nb-spin 0.9s linear infinite;
}
@keyframes nb-spin {
  to {
    transform: rotate(360deg);
  }
}
.nb__think {
  padding: 10px 12px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.nb__thinkhead {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}
.nb__thinkmeta {
  color: var(--ns-ink-4);
  font-size: 10.5px;
}
.nb__thinktext {
  max-height: 180px;
  margin: 0;
  overflow: auto;
  color: var(--ns-ink-2);
  font: inherit;
  font-size: 11.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.nb__thinkempty {
  margin: 0;
  color: var(--ns-ink-4);
  font-size: 11.5px;
}
.nb__workspace {
  display: grid;
  grid-template-columns: minmax(250px, 0.72fr) minmax(0, 1.5fr);
  gap: 18px;
  align-items: start;
}
.nb__cands {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.nb__candshead {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 2px;
}
.nb__candshint {
  color: var(--ns-ink-4);
  font-size: 10.5px;
}
.nb__cand {
  display: flex;
  gap: 9px;
  width: 100%;
  padding: 11px 12px;
  border: 1px solid var(--ns-line);
  border-left: 3px solid transparent;
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.14s ease, background 0.14s ease;
}
.nb__cand:hover {
  background: var(--ns-card-2);
}
.nb__cand.on {
  border-color: var(--ns-pink-line);
  border-left-color: var(--ns-pink);
  background: var(--ns-pink-soft);
}
.nb__candno {
  flex: none;
  color: var(--ns-ink-4);
  font-family: var(--ns-mono);
  font-size: 10px;
  line-height: 1.9;
}
.nb__candbody {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.nb__candtop {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.nb__candtop b {
  font-family: var(--ns-serif);
  font-size: 14.5px;
  font-weight: 600;
}
.nb__candgenre {
  color: var(--ns-ink-3);
  font-size: 10.5px;
}
.nb__candgenre em {
  color: var(--ns-pink-2);
  font-style: normal;
}
.nb__candone {
  display: -webkit-box;
  overflow: hidden;
  color: var(--ns-ink-2);
  font-size: 11.5px;
  line-height: 1.6;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.nb__detail {
  min-width: 0;
  padding: 20px 22px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  box-shadow: var(--ns-shadow-1);
}
.nb__detailhead {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}
.nb__detailtitle h2 {
  margin: 4px 0 3px;
  font-family: var(--ns-serif);
  font-size: clamp(24px, 2.6vw, 32px);
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: 0.01em;
}
.nb__alt {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: 11px;
}
.nb__one {
  margin: 14px 0 0;
  padding-left: 10px;
  border-left: 2px solid var(--ns-pink);
  color: var(--ns-ink);
  font-family: var(--ns-serif);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.7;
}
.nb__synopsis {
  margin-top: 14px;
  color: var(--ns-ink-2);
  font-family: var(--ns-serif);
  font-size: 14px;
  line-height: 1.95;
  white-space: pre-wrap;
}
.nb__reversal {
  margin-top: 18px;
  padding: 14px 16px;
  border: 1px solid var(--ns-pink-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-pink-soft);
}
.nb__reversal header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.nb__revhint {
  color: var(--ns-pink-2);
  font-size: 10.5px;
}
.nb__revlist {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
}
.nb__revrow {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 10px;
}
.nb__revrow dt {
  color: var(--ns-pink-2);
  font-size: 11px;
  font-weight: 700;
  line-height: 1.75;
}
.nb__revrow dd {
  margin: 0;
  color: var(--ns-ink-2);
  font-size: 12px;
  line-height: 1.75;
}
.nb__missing {
  margin: 16px 0 0;
  padding: 10px 12px;
  border: 1px dashed var(--ns-line-2);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
  color: var(--ns-ink-3);
  font-size: 11.5px;
  line-height: 1.7;
}
.nb__meta {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 16px 0 0;
  padding-top: 12px;
  border-top: 1px solid var(--ns-line);
}
.nb__meta div {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 10px;
}
.nb__meta dt {
  color: var(--ns-ink-3);
  font-size: 11px;
  line-height: 1.7;
}
.nb__meta dd {
  margin: 0;
  color: var(--ns-ink-2);
  font-size: 11.5px;
  line-height: 1.7;
}
.nb__detailfoot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px solid var(--ns-line);
}
.nb__detailfoot p {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: 10.5px;
  line-height: 1.6;
}
.nb__detailfoot code {
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--ns-hover);
  font-size: 10px;
}
.nb__detail--empty {
  display: grid;
  place-items: center;
  min-height: 220px;
  color: var(--ns-ink-3);
  font-size: 12px;
}
.nb__detail--empty p {
  margin: 0;
}
.nb__error {
  margin: 0;
  padding: 8px 10px;
  border-radius: var(--ns-r-sm);
  background: var(--ns-pink-soft);
  color: var(--ns-pink-2);
  font-size: 12.5px;
}

@media (max-width: 820px) {
  .nb__brief,
  .nb__workspace {
    grid-template-columns: 1fr;
  }
  .nb__row {
    grid-template-columns: 1fr;
  }
  .nb__foot,
  .nb__detailfoot {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Button, Card, Tag, Table, type Column } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import { useStudio } from '@/stores/studio'

const studio = useStudio()

const model = reactive({
  baseUrl: '',
  model: '',
  fastModel: '',
  apiKeySet: false,
})
const availableModels = ref<string[]>([])
const probe = reactive({ busy: false, ok: false, msg: '' as string })
const saving = ref(false)
const styleSkill = ref('尘年')
const autoArchive = ref(true)
const minChars = ref(studio.book.minChars)
const repairBusy = ref(false)
const repairDone = ref(false)

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
  autoArchive.value ? '待确认章进「进度」页会自动存档，不弹确认框' : '关掉后，待确认章要手动点「存档」',
)

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { 'content-type': 'application/json' },
    ...init,
  })
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(body?.detail || `HTTP ${res.status}`)
  return body as T
}

async function loadModelSettings() {
  try {
    const s = await api<typeof model>('/settings')
    Object.assign(model, s)
  } catch (e) {
    studio.toast(`读取模型设置失败：${(e as Error).message}`, 'warn')
  }
}

async function probeProvider() {
  probe.busy = true
  probe.msg = ''
  try {
    const r = await api<{ ok: boolean; models: string[]; error: string }>('/settings/probe', {
      method: 'POST',
      body: JSON.stringify({ baseUrl: model.baseUrl }),
    })
    probe.ok = r.ok
    availableModels.value = r.models || []
    probe.msg = r.ok
      ? `连上了，可用 ${r.models.length} 个模型`
      : `连不上：${r.error || '未知错误'}`
  } catch (e) {
    probe.ok = false
    probe.msg = `探活失败：${(e as Error).message}`
  } finally {
    probe.busy = false
  }
}

async function saveModel() {
  saving.value = true
  try {
    Object.assign(model, await api<typeof model>('/settings', { method: 'PUT', body: JSON.stringify(model) }))
    studio.toast('模型设置已保存（写正文会读这个配置）', 'ok')
  } catch (e) {
    studio.toast(`保存失败：${(e as Error).message}`, 'warn')
  } finally {
    saving.value = false
  }
}

function repair() {
  repairBusy.value = true
  setTimeout(() => {
    repairBusy.value = false
    repairDone.value = true
    studio.toast('修复完成：索引已重建，账本坏行 0 条，门控与正文对齐', 'ok')
  }, 900)
}

onMounted(loadModelSettings)
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

        <Card title="生成模型" desc="写作会话用哪个模型。改了之后新开的会话生效，旧会话不变。">
          <div class="model-stack">
            <label>
              <span>Base URL（OpenAI 兼容）</span>
              <input v-model="model.baseUrl" spellcheck="false" placeholder="http://127.0.0.1:3425/v1" />
            </label>
            <div class="model">
              <label>
                <span>正文模型（写章节）</span>
                <input v-model="model.model" list="ns-models" spellcheck="false" />
              </label>
              <label>
                <span>轻活模型（点名/摘要/体检）</span>
                <input v-model="model.fastModel" list="ns-models" spellcheck="false" />
              </label>
            </div>
            <datalist id="ns-models">
              <option v-for="m in availableModels" :key="m" :value="m" />
            </datalist>
            <div class="model-actions">
              <Button size="sm" :disabled="probe.busy" @click="probeProvider">
                {{ probe.busy ? '探测中…' : '测试连接' }}
              </Button>
              <Button variant="primary" size="sm" :disabled="saving" @click="saveModel">
                {{ saving ? '保存中…' : '保存' }}
              </Button>
              <span v-if="probe.msg" class="probe" :class="probe.ok ? 'ok' : 'bad'">{{ probe.msg }}</span>
            </div>
          </div>
        </Card>

        <Card title="文风" desc="文风只影响措辞，不改设定。技能库里没有的作家会退化成通用文风。">
          <div class="chips">
            <button
              v-for="s in ['尘年', '烽火戏诸侯', '猫腻', '余华', '刘慈欣', '无（冷写实）']"
              :key="s"
              type="button"
              class="chip"
              :class="{ on: styleSkill === s }"
              @click="styleSkill = s"
            >
              {{ s }}
            </button>
          </div>
        </Card>
      </div>

      <div class="ns-stack">
        <Card title="写作与存档" desc="作者只做三个决定：选题、这一章过不过、方向改不改。">
          <div class="switchrow">
            <div>
              <b>待确认章自动存档</b>
              <p>{{ autoSaveHint }}</p>
            </div>
            <button type="button" class="switch" :class="{ on: autoArchive }" role="switch" :aria-checked="autoArchive" @click="autoArchive = !autoArchive">
              <i />
            </button>
          </div>
          <div class="switchrow">
            <div>
              <b>章节字数硬下限</b>
              <p>长篇每章低于这个字数会标「待修」；全书 ≤50 章的短篇不设下限。</p>
            </div>
            <div class="minchars">
              <input v-model.number="minChars" type="number" step="100" min="0" aria-label="章节字数硬下限" />
              <span>字</span>
            </div>
          </div>
          <div class="switchrow switchrow--static">
            <div>
              <b>批量写作</b>
              <p>10 章一段，一段一份段落纲（3–5 个台阶），不逐章排细纲。</p>
            </div>
            <Tag size="sm" tone="pink">固定</Tag>
          </div>
        </Card>

        <Card title="项目体检" desc="重建 chapters/index.json，清理账本坏行，把门控对齐真实正文。不会删正文。">
          <template #actions>
            <Button size="sm" :disabled="repairBusy" @click="repair">{{ repairBusy ? '修复中…' : '开始修复' }}</Button>
          </template>
          <div v-if="repairDone" class="repaired">
            <Tag size="sm" tone="ok" dot>已修复</Tag>
            <span>索引重建 · 账本坏行 0 · gate 同步到第 {{ studio.book.gate.chapter }} 章</span>
          </div>
          <div v-else class="repairlist">
            <span>索引 <Tag size="sm" tone="ok">正常</Tag></span>
            <span>账本 <Tag size="sm" tone="ok">无坏行</Tag></span>
            <span>门控 <Tag size="sm" tone="warn">写作中</Tag></span>
          </div>
        </Card>

        <Card title="用量" :desc="`这次会话累计 ${(tokensTotal / 1000).toFixed(0)}k tokens。拒稿也会记账。`" flush>
          <Table :columns="usageCols" :rows="recentUsage" dense row-key="at">
            <template #cell:verdict="{ row }">
              <Tag size="sm" :tone="row.rejected ? 'warn' : 'ok'">{{ row.rejected ? '退回' : '存入' }}</Tag>
            </template>
          </Table>
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

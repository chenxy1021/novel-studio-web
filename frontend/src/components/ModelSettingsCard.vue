<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Button, Card } from '@/design'
import { useStudio } from '@/stores/studio'

const studio = useStudio()

const model = reactive({
  baseUrl: '',
  model: '',
  fastModel: '',
  apiKeySet: false,
  apiKey: '',
})
const availableModels = ref<string[]>([])
const probe = reactive({ busy: false, ok: false, msg: '' as string })
const saving = ref(false)

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
    model.apiKey = ''
    studio.toast('模型设置已保存（写正文会读这个配置）', 'ok')
  } catch (e) {
    studio.toast(`保存失败：${(e as Error).message}`, 'warn')
  } finally {
    saving.value = false
  }
}

onMounted(loadModelSettings)
</script>

<template>
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
      <label>
        <span>API Key（可选，留空保持不变）</span>
        <input
          v-model="model.apiKey"
          type="password"
          autocomplete="off"
          :placeholder="model.apiKeySet ? '已配置，留空保持不变' : '本机代理一般不用填'"
        />
      </label>
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
</template>

<style scoped>
.model-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.model-stack label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 12px;
  color: var(--ns-ink-2);
}
.model-stack input {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card);
  color: var(--ns-ink);
  font: inherit;
  font-size: 12.5px;
}
.model-stack input:focus {
  outline: 2px solid var(--ns-pink-soft);
  border-color: var(--ns-pink);
}
.model {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.model-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.probe {
  font-size: 11.5px;
}
.probe.ok {
  color: var(--ns-ok);
}
.probe.bad {
  color: var(--ns-bad);
}
.model__key {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: 11.5px;
}
@media (max-width: 640px) {
  .model {
    grid-template-columns: 1fr;
  }
}
</style>

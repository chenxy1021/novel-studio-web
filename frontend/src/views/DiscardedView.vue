<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, Card, Tag, EmptyState } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import { useStudio } from '@/stores/studio'
import type { Discard } from '@/mocks'

const studio = useStudio()
const open = ref<string | null>(null)
const removed = ref<string[]>([])

const list = computed(() => studio.data.discarded.filter((d) => !removed.value.includes(d.draftFile)))
const chars = computed(() => list.value.reduce((s, d) => s + d.chars, 0))

async function copy(d: Discard) {
  try {
    await navigator.clipboard.writeText(`${d.title}\n\n${d.lead}`)
    studio.toast(`已复制第 ${d.number} 章废稿开头`, 'ok')
  } catch {
    studio.toast('复制失败：浏览器不允许写剪贴板', 'warn')
  }
}

function restore(d: Discard) {
  studio.toast(`第 ${d.number} 章已从废稿恢复。回到「进度」页重新确认存档。`, 'ok')
}

function purge(d: Discard) {
  removed.value = [...removed.value, d.draftFile]
  studio.toast(`已永久删除 ${d.draftFile}（正文不受影响）`, 'warn')
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="退回与作废"
      title="废章"
      desc="体检没过、退回重写、去味替换下来的旧稿都在这里。旧稿可看、可恢复，也可以永久删除——删的只是草稿文件，不碰正文。"
    >
      <Button variant="ghost" icon="↻">刷新</Button>
    </PageHeader>

    <div class="bar">
      <span><b class="ns-num">{{ list.length }}</b> 份废稿</span>
      <span class="bar__dim">·</span>
      <span>合计 <b class="ns-num">{{ chars }}</b> 字</span>
      <span class="bar__hint">退回重写时旧稿会自动存进这里，章号会释放。</span>
    </div>

    <div v-if="list.length" class="list">
      <Card v-for="d in list" :key="d.draftFile" flush class="draft">
        <div class="draft__head" @click="open = open === d.draftFile ? null : d.draftFile">
          <span class="draft__num ns-mono">{{ String(d.number).padStart(3, '0') }}</span>
          <div class="draft__title">
            <b>{{ d.title }}</b>
            <span>{{ d.reason }}</span>
          </div>
          <div class="draft__meta">
            <span class="ns-num">{{ d.chars }} 字</span>
            <span class="draft__date ns-num">{{ d.at }}</span>
            <span class="draft__caret">{{ open === d.draftFile ? '⌃' : '⌄' }}</span>
          </div>
        </div>
        <Transition name="draft">
          <div v-if="open === d.draftFile" class="draft__body">
            <div class="draft__file ns-mono">
              <Tag size="sm" tone="neutral">drafts/</Tag>
              {{ d.draftFile.replace(/^drafts\//, '') }}
            </div>
            <p class="ns-serif draft__lead">{{ d.lead }}</p>
            <div class="draft__acts">
              <Button size="sm" variant="ghost" @click="copy(d)">复制</Button>
              <Button size="sm" @click="restore(d)">恢复到待确认</Button>
              <Button size="sm" variant="danger" @click="purge(d)">永久删除</Button>
            </div>
          </div>
        </Transition>
      </Card>
    </div>
    <EmptyState v-else icon="⌫" title="没有废稿" desc="在「进度」页对某一章做体检、确认作废后，旧稿会进这里。" />
  </div>
</template>

<style scoped>
.page {
  max-width: 960px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 10px 14px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
  margin-bottom: 14px;
  font-size: 12px;
  color: var(--ns-ink-2);
}
.bar b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-16);
}
.bar__dim {
  color: var(--ns-ink-4);
}
.bar__hint {
  margin-left: auto;
  font-size: 11px;
  color: var(--ns-ink-3);
}
.list {
  display: grid;
  gap: 8px;
}
.draft__head {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 13px 16px;
  cursor: pointer;
}
.draft__num {
  flex: none;
  font-size: var(--ns-fs-12);
  color: var(--ns-ink-4);
  padding-top: 2px;
}
.draft__title {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 3px;
}
.draft__title b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
}
.draft__title span {
  font-size: 11.5px;
  color: var(--ns-ink-3);
}
.draft__meta {
  flex: none;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: var(--ns-ink-3);
}
.draft__caret {
  color: var(--ns-ink-4);
}
.draft__body {
  border-top: 1px dashed var(--ns-line);
  padding: 12px 16px 14px 48px;
}
.draft__file {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10.5px;
  color: var(--ns-ink-3);
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.draft__lead {
  margin: 0;
  padding: 12px 14px;
  background: var(--ns-paper);
  border-radius: var(--ns-r-sm);
  border-left: 2px solid var(--ns-line-2);
  font-size: var(--ns-fs-14);
  line-height: 1.9;
  color: var(--ns-ink-2);
}
.draft__acts {
  display: flex;
  gap: 6px;
  margin-top: 10px;
  justify-content: flex-end;
}
.draft-enter-active,
.draft-leave-active {
  transition: opacity 0.15s ease;
}
.draft-enter-from,
.draft-leave-to {
  opacity: 0;
}
@media (max-width: 680px) {
  .page {
    padding: 20px 16px 64px;
  }
  .draft__meta,
  .bar__hint {
    display: none;
  }
  .draft__body {
    padding-left: 16px;
  }
}
</style>

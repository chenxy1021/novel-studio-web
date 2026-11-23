<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, Card, Tag } from '@/design'
import PageHeader from '@/components/PageHeader.vue'
import { useStudio } from '@/stores/studio'

const studio = useStudio()
const dirty = ref(false)
const draft = ref('')

const base = computed(() =>
  [
    '## 1. 世界基底',
    '',
    studio.book.synopsis,
    '',
    '## 2. 历史与时间线',
    '',
    `断讯第七年。${studio.data.timeline[0]?.summary ?? ''}`,
    '',
    '## 3. 日常与氛围',
    '',
    ...studio.data.world.map((w) => `**${w.name}**：${w.detail}`),
    '',
    '## 4. 自洽检查',
    '',
    '- 主角为什么现在才行动：塔下的风向变了，只有他知道。',
    '- 反派为什么不在第 1 章动手：对方要的是「令」，不是人。',
  ].join('\n'),
)

watch([() => studio.key], () => {
  draft.value = base.value
  dirty.value = false
}, { immediate: true })

watch(draft, () => (dirty.value = true))

function save() {
  dirty.value = false
  studio.toast('世界观已保存', 'ok')
}

const habits = computed(() => studio.data.world)
const ruleCount = computed(() => studio.data.rules.length)
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="地基"
      title="世界观"
      desc="世界观不写设定百科，只写「人物真正活在里面会怎样」：钱怎么流通、称呼怎么叫、什么忌讳不能说。"
    >
      <Button variant="ghost">深入推演</Button>
      <Button variant="pink" :disabled="!dirty" @click="save">{{ dirty ? '保存世界观 ·' : '已保存' }}</Button>
    </PageHeader>

    <div class="grid">
      <Card flush class="habits">
        <div class="habits__head">
          <span class="ns-eyebrow">只有这里才有</span>
          <Tag size="sm" tone="gold">{{ habits.length }} 条</Tag>
        </div>
        <ul class="habits__list">
          <li v-for="h in habits" :key="h.key">
            <b>{{ h.name }}</b>
            <p>{{ h.detail }}</p>
          </li>
        </ul>
        <div class="habits__foot">
          <span>硬规则 {{ ruleCount }} 条 · 势力 {{ studio.data.factions.length }} 个 · 地点 {{ habits.length }} 处</span>
          <Button size="sm" variant="ghost" @click="$router.push({ name: 'setup' })">去设定页 →</Button>
        </div>
      </Card>

      <Card flush>
        <div class="editor__bar">
          <span class="ns-eyebrow">世界观正文 · Markdown</span>
          <div class="editor__tools">
            <Tag v-if="dirty" size="sm" tone="warn" dot>未保存</Tag>
            <Tag v-else size="sm" tone="ok">已同步</Tag>
            <span class="ns-num editor__words">{{ draft.length }} 字符</span>
          </div>
        </div>
        <textarea v-model="draft" class="editor__area" spellcheck="false" aria-label="世界观正文" />
        <div class="editor__foot">保存后，每次写正文都会把这份正文塞进上下文；改了它等于换了地基。</div>
      </Card>
    </div>

    <Card title="自洽检查" desc="四个问题过一遍，读者才不会问「为什么不直接 X 一下」。" class="checks">
      <div class="checks__grid">
        <div v-for="(q, i) in [
          { q: '主角为什么现在才行动？', a: '塔下风向变了，只有他一个守塔人听得出来。' },
          { q: '对手为什么不在第 1 章就赢？', a: '对方要的是「令」，不是人；塔只剩一台发射机。' },
          { q: '这套体系为什么没把普通人淘汰？', a: '收容站靠广播对表，停播一次就没法分粮。' },
          { q: '如果读者问「为什么不直接解决」？', a: '没有第二台发射机，也没有第二个人会报时。' },
        ]" :key="i" class="checks__item">
          <span>0{{ i + 1 }}</span>
          <div>
            <b>{{ q.q }}</b>
            <p>{{ q.a }}</p>
          </div>
        </div>
      </div>
    </Card>
  </div>
</template>

<style scoped>
.page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 28px 32px 72px;
}
.grid {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  margin-bottom: 16px;
}
.habits__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 13px 16px 4px;
}
.habits__list {
  list-style: none;
  margin: 0;
  padding: 6px 16px 8px;
}
.habits__list li {
  padding: 10px 0;
  border-bottom: 1px dashed var(--ns-line);
}
.habits__list li:last-child {
  border-bottom: 0;
}
.habits__list b {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-14);
}
.habits__list p {
  margin: 3px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--ns-ink-2);
}
.habits__foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid var(--ns-line);
  background: var(--ns-card-2);
  font-size: 11px;
  color: var(--ns-ink-3);
  flex-wrap: wrap;
}
.editor__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 16px;
  background: var(--ns-card-2);
  border-bottom: 1px solid var(--ns-line);
  flex-wrap: wrap;
}
.editor__tools {
  display: flex;
  align-items: center;
  gap: 10px;
}
.editor__words {
  font-size: 11px;
  color: var(--ns-ink-3);
}
.editor__area {
  display: block;
  width: 100%;
  border: 0;
  outline: 0;
  resize: vertical;
  min-height: clamp(420px, 52vh, 620px);
  padding: 18px 22px;
  background: var(--ns-card);
  color: var(--ns-ink-2);
  font-family: var(--ns-serif);
  font-size: 14.5px;
  line-height: 1.95;
}
.editor__area:focus {
  background: var(--ns-paper);
}
.editor__foot {
  padding: 10px 16px;
  border-top: 1px solid var(--ns-line);
  font-size: 11px;
  color: var(--ns-ink-3);
}
.checks__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.checks__item {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-sm);
  background: var(--ns-card-2);
}
.checks__item > span {
  font-family: var(--ns-serif);
  font-size: var(--ns-fs-18);
  color: var(--ns-pink);
  line-height: 1;
}
.checks__item b {
  font-size: 12.5px;
}
.checks__item p {
  margin: 3px 0 0;
  font-size: 12px;
  color: var(--ns-ink-2);
  line-height: 1.65;
}
@media (max-width: 960px) {
  .grid,
  .checks__grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 620px) {
  .page {
    padding: 20px 16px 64px;
  }
}
</style>

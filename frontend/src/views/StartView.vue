<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Card, Modal, Tag } from '@/design'
import NewBookForm from '@/components/NewBookForm.vue'
import ModelSettingsCard from '@/components/ModelSettingsCard.vue'
import Toasts from '@/components/Toasts.vue'
import { useStudio } from '@/stores/studio'

const studio = useStudio()
const router = useRouter()
const showModel = ref(false)

async function rescan() {
  await studio.init()
}

/** 建书后直接进开书流程：下一步就是由梗概生成大纲 + 世界观。 */
function onCreated() {
  router.push({ name: 'workflow' })
}
</script>

<template>
  <div class="start">
    <header class="start__head">
      <div class="start__brand">
        <div class="start__mark" aria-hidden="true">墨</div>
        <div>
          <b>Novel Studio</b>
          <span>长篇小说工作台</span>
        </div>
      </div>
      <div class="start__headact">
        <Button size="sm" variant="secondary" @click="showModel = true">模型设置</Button>
        <Tag tone="info">书架是空的</Tag>
      </div>
    </header>

    <main class="start__main">
      <section class="start__hero">
        <div class="start__herotext">
          <span class="ns-eyebrow">新书 · 选题工作台</span>
          <h1>先立选题，<br />再开书。</h1>
          <p>
            说说你想写什么，定下体量，AI 会给你几个带着书名和简介的选题。
            选中一个，书目录就建好了。
          </p>
        </div>
        <ol class="start__flow">
          <li>
            <b>01</b>
            <span>想法</span>
            <small>方向、题材、卖点，想填再填</small>
          </li>
          <li>
            <b>02</b>
            <span>选题</span>
            <small>AI 起书名、写简介；虐文模式带反转结构</small>
          </li>
          <li>
            <b>03</b>
            <span>开书</span>
            <small>进工作台分卷、排段落、写正文</small>
          </li>
        </ol>
      </section>

      <Card class="start__panel" title="新书选题" desc="目标章节数和每章字数必填；其余都能留空。">
        <NewBookForm @created="onCreated" />
      </Card>

      <p class="start__note">
        已经有书目录？把它放回 <code>~/Desktop/mine/xiaoshuo</code>，然后点右下角「重新扫描」。
      </p>
    </main>

    <Modal
      :open="showModel"
      title="模型设置"
      desc="没有书也能先配好模型。这里是全局配置，新建的书都会用。"
      width="620px"
      @close="showModel = false"
    >
      <ModelSettingsCard />
    </Modal>

    <footer class="start__foot">
      <span>书目录：<code>~/Desktop/mine/xiaoshuo</code></span>
      <Button size="sm" variant="ghost" @click="rescan">重新扫描</Button>
    </footer>
    <Toasts />
  </div>
</template>

<style scoped>
.start {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 28px;
  padding: 26px clamp(20px, 5vw, 64px) 40px;
  background: var(--ns-paper);
  overflow-y: auto;
}
.start__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  max-width: 1180px;
  width: 100%;
  margin: 0 auto;
}
.start__headact {
  display: flex;
  align-items: center;
  gap: 8px;
}
.start__brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.start__mark {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: var(--ns-ink);
  color: var(--ns-paper);
  font-family: var(--ns-serif);
  font-size: 17px;
}
.start__brand b {
  display: block;
  font-size: 13.5px;
  letter-spacing: 0.02em;
}
.start__brand span {
  display: block;
  color: var(--ns-ink-3);
  font-size: 11px;
}

.start__main {
  display: flex;
  flex-direction: column;
  gap: 22px;
  max-width: 1180px;
  width: 100%;
  margin: 0 auto;
}

.start__hero {
  display: grid;
  grid-template-columns: minmax(280px, 0.9fr) minmax(420px, 1.1fr);
  gap: clamp(24px, 5vw, 72px);
  align-items: end;
  padding: 12px 0 22px;
  border-bottom: 1px solid var(--ns-line);
}
.start__herotext h1 {
  margin: 8px 0 12px;
  font-family: var(--ns-serif);
  font-size: clamp(34px, 3.8vw, 52px);
  font-weight: 600;
  line-height: 1.24;
  letter-spacing: 0.01em;
}
.start__herotext p {
  max-width: 34em;
  margin: 0;
  color: var(--ns-ink-2);
  font-size: 13.5px;
  line-height: 1.85;
}
.start__flow {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
  border-top: 1px solid var(--ns-line);
}
.start__flow li {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 14px 14px 0 0;
  border-right: 1px solid var(--ns-line);
}
.start__flow li:last-child {
  border-right: 0;
  padding-right: 0;
}
.start__flow b {
  color: var(--ns-pink-2);
  font-family: var(--ns-mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
}
.start__flow span {
  color: var(--ns-ink);
  font-family: var(--ns-serif);
  font-size: 17px;
  font-weight: 600;
}
.start__flow small {
  color: var(--ns-ink-3);
  font-size: 11px;
  line-height: 1.65;
}

.start__panel {
  box-shadow: var(--ns-shadow-1);
}
.start__note {
  margin: 0;
  color: var(--ns-ink-3);
  font-size: 11.5px;
  text-align: center;
}
.start__note code,
.start__foot code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--ns-hover);
  font-size: 11px;
}

.start__foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  max-width: 1180px;
  width: 100%;
  margin: auto auto 0;
  padding-top: 18px;
  border-top: 1px solid var(--ns-line);
  color: var(--ns-ink-3);
  font-size: 11.5px;
}

@media (max-width: 900px) {
  .start__hero {
    grid-template-columns: 1fr;
    align-items: start;
  }
  .start__flow {
    margin-top: 4px;
  }
}
@media (max-width: 640px) {
  .start__flow {
    grid-template-columns: 1fr;
    border-top: 0;
  }
  .start__flow li {
    border-right: 0;
    border-top: 1px solid var(--ns-line);
    padding: 10px 0;
  }
}
</style>

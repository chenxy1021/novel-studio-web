import { createRouter, createWebHistory } from 'vue-router'

export const TABS = [
  { name: 'overview', path: 'overview', label: '概览', glyph: '◐', hint: '这本书现在长什么样' },
  { name: 'outline', path: 'outline', label: '大纲', glyph: '≡', hint: '全书 / 卷层结构' },
  { name: 'world', path: 'world', label: '世界观', glyph: '◎', hint: '地基与惯例' },
  { name: 'characters', path: 'characters', label: '人物', glyph: '人', hint: '谁在推动故事' },
  { name: 'setup', path: 'setup', label: '设定', glyph: '⚙', hint: '硬规则与势力' },
  { name: 'foreshadow', path: 'foreshadow', label: '伏笔', glyph: '◇', hint: '埋了什么，什么时候收' },
  { name: 'detail', path: 'detail', label: '细纲', glyph: '☰', hint: '10 章一段的段落纲' },
  { name: 'progress', path: 'progress', label: '进度', glyph: '▦', hint: '写、审、存' },
  { name: 'discarded', path: 'discarded', label: '废章', glyph: '⌫', hint: '退回与作废的旧稿' },
  { name: 'settings', path: 'settings', label: '设置', glyph: '⋯', hint: '模型 · 存档 · 修复' },
] as const

export type TabName = (typeof TABS)[number]['name']

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: TABS.map((t) => ({
    path: `/${t.path}`,
    name: t.name,
    component: () => import(`../views/${t.name[0].toUpperCase()}${t.name.slice(1)}View.vue`),
  })),
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => (to.name ? true : { name: 'overview' }))

export default router

import { createRouter, createWebHistory } from 'vue-router'

export type TabGroup = '工作台' | '写作' | '规划' | '资料' | '系统'

/**
 * 页面按「一天怎么用」分组，而不是按功能平铺：
 * 今日 → 写作 → 规划 → 资料。侧栏、命令面板、快捷键说明都读这份表。
 */
export const TABS = [
  { name: 'overview', path: 'overview', label: '今日', glyph: '◐', hint: '现在该做什么', group: '工作台' as TabGroup, key: 'h' },
  { name: 'workflow', path: 'workflow', label: '开书', glyph: '✍', hint: '大纲 → 设定 → 伏笔 → 写作', group: '工作台' as TabGroup, key: 'n' },
  { name: 'style', path: 'style', label: '文风', glyph: '✎', hint: '默认写法 · 作家参照', group: '工作台' as TabGroup, key: 'w' },
  { name: 'progress', path: 'progress', label: '进度', glyph: '▦', hint: '逐章审阅、体检、存档', group: '写作' as TabGroup, key: 'p' },
  { name: 'discarded', path: 'discarded', label: '废章', glyph: '⌫', hint: '退回与作废的旧稿', group: '写作' as TabGroup, key: 'x' },
  { name: 'outline', path: 'outline', label: '大纲', glyph: '≡', hint: '结构大纲 · 世界观', group: '规划' as TabGroup, key: 'o' },
  { name: 'detail', path: 'detail', label: '细纲', glyph: '☰', hint: '按段规划 · 段落纲', group: '规划' as TabGroup, key: 'd' },
  { name: 'foreshadow', path: 'foreshadow', label: '伏笔', glyph: '◇', hint: '埋了什么，什么时候收', group: '规划' as TabGroup, key: 'f' },
  { name: 'characters', path: 'characters', label: '人物', glyph: '人', hint: '谁在推动故事', group: '资料' as TabGroup, key: 'c' },
  { name: 'memory', path: 'memory', label: '记忆', glyph: '◷', hint: '时间线 · 前情 · 回查', group: '资料' as TabGroup, key: 'm' },
  { name: 'setup', path: 'setup', label: '设定', glyph: '⚙', hint: '规则、势力与资料', group: '资料' as TabGroup, key: 's' },
  { name: 'settings', path: 'settings', label: '设置', glyph: '⋯', hint: '模型 · 存档 · 修复', group: '系统' as TabGroup, key: ',' },
] as const

export type TabName = (typeof TABS)[number]['name']
export type Tab = (typeof TABS)[number]

export const TAB_GROUPS = ['工作台', '写作', '规划', '资料', '系统'] as const

export const tabOf = (name: unknown): Tab | undefined => TABS.find((t) => t.name === name)

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    ...TABS.map((t) => ({
      path: `/${t.path}`,
      name: t.name,
      component: () => import(`../views/${t.name[0].toUpperCase()}${t.name.slice(1)}View.vue`),
    })),
    // 世界观已并进「大纲」页的第二栏；旧链接仍然可用。
    { path: '/world', redirect: { name: 'outline', query: { tab: 'world' } } },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => (to.name ? true : { name: 'overview' }))

export default router

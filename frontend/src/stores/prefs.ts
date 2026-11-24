import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

export type Theme = 'auto' | 'light' | 'dark'

// localStorage 可能被禁用：所有读写都兜底，偏好丢失不该让页面不可用。
function readLS(name: string): string | null {
  try {
    return localStorage.getItem(name)
  } catch {
    return null
  }
}
function writeLS(name: string, value: string) {
  try {
    localStorage.setItem(name, value)
  } catch {
    /* 写不进去就用内存里的值 */
  }
}

const THEME_ORDER: Theme[] = ['auto', 'light', 'dark']

/** UI 偏好：主题、侧栏、命令面板。和书稿状态分开放，清书不影响界面设置。 */
export const usePrefs = defineStore('prefs', () => {
  const stored = readLS('ns.theme')
  const theme = ref<Theme>(THEME_ORDER.includes(stored as Theme) ? (stored as Theme) : 'auto')
  const railCollapsed = ref(readLS('ns.rail') === '1')
  /** 待确认章进进度页是否自动存档。默认开，作者可以在设置里关掉。 */
  const autoArchive = ref(readLS('ns.autoArchive') === '1')
  const paletteOpen = ref(false)
  const helpOpen = ref(false)

  const themeIcon = computed(() => (theme.value === 'auto' ? '◐' : theme.value === 'light' ? '☀' : '☾'))
  const themeLabel = computed(() => (theme.value === 'auto' ? '跟随系统' : theme.value === 'light' ? '浅色' : '深色'))

  function applyTheme() {
    document.documentElement.dataset.theme = theme.value
  }

  function cycleTheme() {
    const i = THEME_ORDER.indexOf(theme.value)
    theme.value = THEME_ORDER[(i + 1) % THEME_ORDER.length]
  }

  function toggleRail() {
    railCollapsed.value = !railCollapsed.value
  }

  function openPalette() {
    paletteOpen.value = true
    helpOpen.value = false
  }

  function closePalette() {
    paletteOpen.value = false
  }

  function openHelp() {
    helpOpen.value = true
    paletteOpen.value = false
  }

  watch(theme, (t) => {
    writeLS('ns.theme', t)
    applyTheme()
  })
  watch(railCollapsed, (v) => writeLS('ns.rail', v ? '1' : '0'))
  watch(autoArchive, (v) => writeLS('ns.autoArchive', v ? '1' : '0'))

  applyTheme()

  return {
    theme,
    themeIcon,
    themeLabel,
    railCollapsed,
    autoArchive,
    paletteOpen,
    helpOpen,
    cycleTheme,
    toggleRail,
    applyTheme,
    openPalette,
    closePalette,
    openHelp,
  }
})

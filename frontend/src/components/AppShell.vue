<template>
  <div class="shell">
    <NavRail />
    <main class="shell__main">
      <TopBar />
      <div class="shell__page">
        <RouterView v-slot="{ Component }">
          <component :is="Component" :key="studio.key" />
        </RouterView>
      </div>
    </main>
    <Toasts />
  </div>
</template>

<script setup lang="ts">
import { useStudio } from '@/stores/studio'
import NavRail from './NavRail.vue'
import TopBar from './TopBar.vue'
import Toasts from './Toasts.vue'

const studio = useStudio()
</script>

<style scoped>
.shell {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: var(--ns-rail-w) minmax(0, 1fr);
  height: 100%;
}
.shell__main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.shell__page {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
@media (max-width: 820px) {
  .shell {
    grid-template-columns: 1fr;
  }
}
</style>

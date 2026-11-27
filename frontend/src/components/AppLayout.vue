<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import CommandPalette from './CommandPalette.vue'
import SyncStatus from './SyncStatus.vue'

const route = useRoute()
const nav = [
  { to: '/', icon: '◉', label: 'Today' },
  { to: '/work-items', icon: '▣', label: 'Project progress' },
  { to: '/inbox', icon: '✉', label: 'Inbox' },
  { to: '/search', icon: '⌕', label: 'Search' },
  { to: '/todos', icon: '✓', label: 'To-dos' },
  { to: '/retrospective', icon: '★', label: 'Retrospective' },
  { to: '/weekly', icon: '▤', label: 'Weekly review' },
  { to: '/learning', icon: '◇', label: 'Lessons' },
  { to: '/insights', icon: '▤', label: 'Insights' },
  { to: '/settings', icon: '⚙', label: 'Settings' },
]
const isActive = (to: string) => (to === '/' ? route.path === '/' : route.path.startsWith(to))
const year = new Date().getFullYear()
const menuOpen = ref(false)
const paletteOpen = ref(false)
const menuButton = ref<HTMLButtonElement>()
const commandButton = ref<HTMLButtonElement>()
const main = ref<HTMLElement>()

function onGlobalKey(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    paletteOpen.value = !paletteOpen.value
  }
}

onMounted(() => window.addEventListener('keydown', onGlobalKey))
onUnmounted(() => window.removeEventListener('keydown', onGlobalKey))

watch(paletteOpen, async open => {
  if (!open) {
    await nextTick()
    commandButton.value?.focus()
  }
})

async function closeMenu() {
  if (!menuOpen.value) return
  menuOpen.value = false
  await nextTick()
  menuButton.value?.focus()
}

watch(() => route.path, async () => {
  menuOpen.value = false
  await nextTick()
  main.value?.focus({ preventScroll: true })
})
</script>

<template>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="topbar-left">
        <RouterLink to="/" class="logo">
          <span class="logo-mark">▦</span>
          <span class="logo-text">Work<b>Ledger</b></span>
        </RouterLink>
      </div>
      <div class="topbar-right">
        <span class="topbar-tag">local-first work assistant</span>
        <SyncStatus />
        <button ref="commandButton" type="button" class="command-trigger" aria-label="Open command palette" @click="paletteOpen = true">
          <span aria-hidden="true">⌕</span> Quick actions <kbd>Ctrl K</kbd>
        </button>
        <button
          ref="menuButton"
          type="button"
          class="ghost-btn nav-toggle"
          aria-controls="primary-navigation"
          :aria-expanded="menuOpen"
          @click="menuOpen = !menuOpen"
          @keydown.esc.prevent="closeMenu"
        >{{ menuOpen ? 'Close menu' : 'Menu' }}</button>
      </div>
    </div>
  </header>
  <div class="layout">
    <aside class="sidebar" :class="{ 'sidebar-open': menuOpen }" @keydown.esc.prevent="closeMenu">
      <nav id="primary-navigation" class="sidebar-nav" aria-label="Main navigation">
        <RouterLink
          v-for="item in nav"
          :key="item.to"
          :to="item.to"
          class="sidebar-nav-item"
          :class="{ active: isActive(item.to) }"
          :aria-current="isActive(item.to) ? 'page' : undefined"
          @click="item.to === route.path && closeMenu()"
        >
          <span class="sidebar-nav-icon" aria-hidden="true">{{ item.icon }}</span>
          <span class="sidebar-nav-label">{{ item.label }}</span>
        </RouterLink>
      </nav>
      <div class="sidebar-foot">© {{ year }} WorkLedger</div>
    </aside>
    <main ref="main" class="container" tabindex="-1">
      <slot />
    </main>
  </div>
  <CommandPalette v-model:open="paletteOpen" />
</template>

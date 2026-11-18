<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import { nextTick, ref, watch } from 'vue'

const route = useRoute()
const nav = [
  { to: '/', icon: '◉', label: 'Today' },
  { to: '/inbox', icon: '✉', label: 'Inbox' },
  { to: '/search', icon: '⌕', label: 'Search' },
  { to: '/todos', icon: '✓', label: 'To-dos' },
  { to: '/retrospective', icon: '★', label: 'Retrospective' },
  { to: '/insights', icon: '▤', label: 'Insights' },
  { to: '/settings', icon: '⚙', label: 'Settings' },
]
const isActive = (to: string) => (to === '/' ? route.path === '/' : route.path.startsWith(to))
const year = new Date().getFullYear()
const menuOpen = ref(false)
const menuButton = ref<HTMLButtonElement>()
const main = ref<HTMLElement>()

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
</template>

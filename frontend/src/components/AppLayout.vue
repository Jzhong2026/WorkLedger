<script setup lang="ts">
import { RouterLink, useRoute } from 'vue-router'
import { computed } from 'vue'

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
const year = computed(() => new Date().getFullYear())
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
      </div>
    </div>
  </header>
  <div class="layout">
    <aside class="sidebar">
      <nav class="sidebar-nav">
        <RouterLink
          v-for="item in nav"
          :key="item.to"
          :to="item.to"
          class="sidebar-nav-item"
          :class="{ active: isActive(item.to) }"
        >
          <span class="sidebar-nav-icon">{{ item.icon }}</span>
          <span class="sidebar-nav-label">{{ item.label }}</span>
        </RouterLink>
      </nav>
      <div class="sidebar-foot">© {{ year }} WorkLedger</div>
    </aside>
    <main class="container">
      <slot />
    </main>
  </div>
</template>

<style scoped>
.sidebar-foot { margin-top: auto; padding: 16px 18px; font-size: .72rem; color: var(--text-3); border-top: 1px solid var(--border); }
.sidebar { display: flex; flex-direction: column; }
</style>
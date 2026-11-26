import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.path !== from.path) return { top: 0, behavior: 'instant' }
  },
  routes: [
    { path: '/work-items', name: 'work-items', component: () => import('@/views/WorkItemsView.vue') },
    { path: '/work-items/:id', name: 'work-item', component: () => import('@/views/WorkItemView.vue'), props: true },
    { path: '/weekly', name: 'weekly', component: () => import('@/views/WeeklyView.vue') },
    { path: '/learning', name: 'learning', component: () => import('@/views/LearningView.vue') },
    { path: '/', name: 'today', component: () => import('@/views/TodayView.vue') },
    { path: '/inbox', name: 'inbox', component: () => import('@/views/InboxView.vue') },
    { path: '/search', name: 'search', component: () => import('@/views/SearchView.vue') },
    { path: '/todos', name: 'todos', component: () => import('@/views/TodosView.vue') },
    { path: '/retrospective', name: 'retrospective', component: () => import('@/views/RetrospectiveView.vue') },
    { path: '/insights', name: 'insights', component: () => import('@/views/InsightsView.vue') },
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
    { path: '/event/:id', name: 'event', component: () => import('@/views/EventDetailView.vue'), props: true },
    { path: '/pr', name: 'pr', component: () => import('@/views/PrTimelineView.vue') },
  ],
})

export default router

<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import { workItemsApi } from '@/api/workItems'
import { useAsync } from '@/composables/useAsync'
import { useTodoActions } from '@/composables/useTodoActions'
import { useWindowFocusRefresh } from '@/composables/useWindowFocusRefresh'
import StatCard from '@/components/StatCard.vue'
import TodoCard from '@/components/TodoCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import WorkItemCard from '@/components/WorkItemCard.vue'
import { followupDate, todayWorkGroup } from '@/utils/workItems'

const { data, loading, error, run } = useAsync(() => api.todaySummary())
const {
  data: openWork, loading: workLoading, error: workError, run: reloadWork,
} = useAsync(workItemsApi.openItems)
async function reloadToday() {
  await Promise.all([run(), reloadWork()])
}
const { busy, add, complete, reopen, wait, remove } = useTodoActions(reloadToday)
const title = ref('')
const followup = ref('')
useWindowFocusRefresh(() => {
  if (!busy.value) return reloadToday()
})

const sections = [
  { key: 'overdue', label: 'Overdue' },
  { key: 'today', label: 'Due or follow up today' },
  { key: 'unscheduled', label: 'Unscheduled' },
] as const

const groups = computed(() => {
  const summary = data.value
  if (!summary) return []

  return sections
    .map(section => ({ ...section, todos: summary.groups[section.key] }))
    .filter(section => section.todos.length)
})

const workSections = [
  { key: 'decision', label: 'Needs your decision' },
  { key: 'followup', label: 'Follow up' },
  { key: 'waiting', label: 'Waiting' },
  { key: 'active', label: 'Active work' },
] as const

const workGroups = computed(() => {
  const view = openWork.value
  if (!view) return []
  return workSections.map(section => {
    const items = view.items.filter(item => todayWorkGroup(item, view.today) === section.key)
    if (section.key === 'followup') {
      items.sort((a, b) => (followupDate(a) ?? '').localeCompare(followupDate(b) ?? ''))
    }
    return { ...section, items }
  }).filter(section => section.items.length)
})

async function addTodo() {
  const text = title.value.trim()
  if (text && await add({ title: text, next_followup: followup.value || null })) {
    title.value = ''
    followup.value = ''
  }
}
</script>

<template>
  <div class="work-heading">
    <h1>Today <small v-if="data || openWork">{{ data?.today ?? openWork?.today }}</small></h1>
    <button type="button" class="ghost-btn" :disabled="loading || workLoading" @click="reloadToday">Refresh</button>
  </div>
  <form class="form-card today-entry" @submit.prevent="addTodo">
    <label class="field">
      <span class="field-label">Quick add</span>
      <input v-model="title" type="text" placeholder="What needs follow-up?" required />
    </label>
    <label class="field">
      <span class="field-label">Follow-up date</span>
      <input v-model="followup" type="date" />
    </label>
    <button type="submit" :disabled="busy">Add to-do</button>
  </form>

  <section aria-labelledby="today-work">
    <div class="work-heading">
      <h2 id="today-work">Work in progress</h2>
      <RouterLink to="/work-items">Project progress</RouterLink>
    </div>
    <div v-if="workError" class="error-banner">
      <span role="alert">Could not load work items. {{ workError }}</span>
      <button type="button" @click="reloadWork">Retry</button>
    </div>
    <div v-else-if="workLoading" class="loading" role="status">Loading work items…</div>
    <template v-else-if="workGroups.length">
      <section v-for="group in workGroups" :key="group.key" :aria-labelledby="`work-${group.key}`">
        <h3 :id="`work-${group.key}`">{{ group.label }}</h3>
        <div class="card-list">
          <WorkItemCard v-for="item in group.items" :key="item.id" :item="item" />
        </div>
      </section>
    </template>
    <EmptyState v-else message="No open work items." />
  </section>

  <h2>To-dos</h2>
  <div v-if="error" class="error-banner">
    <span role="alert">Could not load today's to-dos. {{ error }}</span>
    <button type="button" @click="run">Retry</button>
  </div>
  <div v-else-if="loading && !data" class="loading" role="status">Loading to-dos…</div>
  <template v-else-if="data">
    <div class="stat-row" aria-label="All to-dos by status">
      <StatCard :value="data.counts.pending" label="Pending" />
      <StatCard :value="data.counts.waiting" label="Waiting" tone="gold" />
      <StatCard :value="data.counts.done" label="Done" tone="green" />
    </div>

    <section v-for="group in groups" :key="group.key" :aria-labelledby="`today-${group.key}`">
      <h3 :id="`today-${group.key}`">{{ group.label }}</h3>
      <div class="card-list">
        <TodoCard
          v-for="todo in group.todos"
          :key="todo.id"
          :todo="todo"
          :today="data.today"
          :busy="busy"
          @complete="complete"
          @reopen="reopen"
          :save-waiting="wait"
          @remove="remove"
        />
      </div>
    </section>
    <EmptyState v-if="!groups.length" message="Nothing needs follow-up today." />
  </template>
</template>

<style scoped>
.work-heading { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px; }
.work-heading h2 { margin-top: .5rem; }
h3 { font-size: .95rem; margin: .9rem 0 .5rem; }
.today-entry {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 11rem) auto;
  align-items: end;
  gap: 12px;
  margin-bottom: 16px;
}

@media (max-width: 600px) {
  .today-entry { grid-template-columns: minmax(0, 1fr); }
  .today-entry button { justify-self: start; }
}
</style>

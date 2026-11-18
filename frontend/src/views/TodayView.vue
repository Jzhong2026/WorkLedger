<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import { useTodoActions } from '@/composables/useTodoActions'
import StatCard from '@/components/StatCard.vue'
import TodoCard from '@/components/TodoCard.vue'
import EmptyState from '@/components/EmptyState.vue'

const { data, loading, error, run } = useAsync(() => api.todaySummary())
const { busy, add, complete, reopen, wait, remove } = useTodoActions(run)
const title = ref('')
const followup = ref('')

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

async function addTodo() {
  const text = title.value.trim()
  if (text && await add({ title: text, next_followup: followup.value || null })) {
    title.value = ''
    followup.value = ''
  }
}
</script>

<template>
  <h1>Today <small v-if="data">{{ data.today }}</small></h1>
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
      <h2 :id="`today-${group.key}`">{{ group.label }}</h2>
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

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import { useTodoActions } from '@/composables/useTodoActions'
import TodoCard from '@/components/TodoCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { TodoStatus } from '@/types'

const route = useRoute()
const router = useRouter()
const tabs = [
  { value: '', label: 'All' },
  { value: 'pending', label: 'Pending' },
  { value: 'waiting', label: 'Waiting' },
  { value: 'done', label: 'Done' },
] as const
const status = computed(() => tabs.find(tab => tab.value === route.query.status)?.value ?? '')
const scope = computed(() => ({
  date_from: typeof route.query.date_from === 'string' ? route.query.date_from : undefined,
  date_to: typeof route.query.date_to === 'string' ? route.query.date_to : undefined,
  project_id: typeof route.query.project_id === 'string' ? route.query.project_id : undefined,
}))
const hasScope = computed(() => Object.values(scope.value).some(Boolean))
const page = computed(() => {
  const value = Number(route.query.page)
  return Number.isSafeInteger(value) && value > 0 ? value : 1
})
const { data, loading, error, run } = useAsync(
  () => api.listTodos({ ...scope.value, status: status.value, page: page.value }),
  false,
)
watch(() => route.query, () => {
  if (route.name === 'todos') void run()
}, { immediate: true })

const { busy, add, complete, reopen, wait, remove } = useTodoActions(run)
const form = reactive({
  title: '', description: '', status: 'pending' as TodoStatus, wait_target: '', due_date: '', next_followup: '',
})

function pageLink(value: number, filter = status.value, keepScope = true) {
  return {
    name: 'todos',
    query: {
      ...(keepScope ? scope.value : {}),
      status: filter || undefined,
      page: value > 1 ? value : undefined,
    },
  }
}

watch(data, result => {
  if (result && page.value > Math.max(1, result.pages)) {
    void router.replace(pageLink(Math.max(1, result.pages)))
  }
})

async function addTodo() {
  const title = form.title.trim()
  if (!title) return
  const saved = await add({
    title,
    description: form.description.trim() || null,
    status: form.status,
    wait_target: form.status === 'waiting' ? form.wait_target.trim() || null : null,
    due_date: form.due_date || null,
    next_followup: form.next_followup || null,
  })
  if (saved) {
    Object.assign(form, { title: '', description: '', wait_target: '', due_date: '', next_followup: '' })
  }
}
</script>

<template>
  <h1>To-dos <small v-if="data && !error">({{ data.total }})</small></h1>
  <p v-if="hasScope" class="meta">
    Filtered by Insights
    <template v-if="scope.date_from"> · From {{ scope.date_from }}</template>
    <template v-if="scope.date_to"> · Through {{ scope.date_to }}</template>
    <template v-if="scope.project_id === '0'"> · Unassigned</template>
    <template v-else-if="scope.project_id"> · Project #{{ scope.project_id }}</template>
    · <RouterLink :to="pageLink(1, status, false)">Clear scope</RouterLink>
  </p>
  <nav class="filter-tabs" aria-label="Filter to-dos">
    <RouterLink
      v-for="tab in tabs"
      :key="tab.value"
      :to="pageLink(1, tab.value)"
      :class="{ active: tab.value === status }"
      :aria-current="tab.value === status ? 'page' : undefined"
    >{{ tab.label }}</RouterLink>
  </nav>

  <div v-if="error" class="error-banner">
    <span role="alert">Could not load to-dos. {{ error }}</span>
    <button type="button" @click="run">Retry</button>
  </div>
  <div v-else-if="loading && !busy" class="loading" role="status">Loading to-dos…</div>
  <template v-else-if="data">
    <div v-if="data.items.length" class="card-list">
      <TodoCard
        v-for="todo in data.items"
        :key="todo.id"
        :todo="todo"
        :today="data.today"
        :busy="busy"
        :save-waiting="wait"
        @complete="complete"
        @reopen="reopen"
        @remove="remove"
      />
    </div>
    <EmptyState v-else message="No to-dos with this status. Add one below." />
    <nav v-if="data.pages > 1" class="pagination" aria-label="To-do pages">
      <RouterLink v-if="page > 1" :to="pageLink(page - 1)">Previous</RouterLink>
      <span>Page {{ page }} of {{ data.pages }}</span>
      <RouterLink v-if="page < data.pages" :to="pageLink(page + 1)">Next</RouterLink>
    </nav>
  </template>

  <h2>Add to-do</h2>
  <form class="form-card" @submit.prevent="addTodo">
    <div class="form-grid-2">
      <label class="field form-span"><span class="field-label">Title</span><input v-model="form.title" type="text" required /></label>
      <label class="field form-span"><span class="field-label">Description</span><textarea v-model="form.description" rows="2"></textarea></label>
      <label class="field">
        <span class="field-label">Status</span>
        <select v-model="form.status">
          <option value="pending">Pending</option>
          <option value="waiting">Waiting</option>
        </select>
      </label>
      <label v-if="form.status === 'waiting'" class="field">
        <span class="field-label">Waiting for</span>
        <input v-model="form.wait_target" type="text" />
      </label>
      <label class="field"><span class="field-label">Due date</span><input v-model="form.due_date" type="date" /></label>
      <label class="field"><span class="field-label">Next follow-up</span><input v-model="form.next_followup" type="date" /></label>
    </div>
    <div class="form-actions"><button type="submit" :disabled="busy">Add to-do</button></div>
  </form>
</template>

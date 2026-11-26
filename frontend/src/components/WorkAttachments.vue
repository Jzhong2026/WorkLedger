<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import type { Todo, WorkEvent } from '@/types'

const props = defineProps<{ linkedEvents: WorkEvent[]; linkedTodos: Todo[]; projectId: number | null }>()
const events = defineModel<WorkEvent[]>('events', { required: true })
const todos = defineModel<Todo[]>('todos', { required: true })
const keywords = ref('')
const eventPage = ref(1)
const todoPage = ref(1)
const eventSearch = ref('')
const eventResults = useAsync(() => api.searchEvents({
  q: eventSearch.value || undefined,
  project_id: eventSearch.value ? undefined : props.projectId ?? undefined,
  page: eventPage.value,
  page_size: 10,
}), false)
const todoResults = useAsync(() => api.listTodos({ page: todoPage.value, page_size: 10 }), false)

const eventChoices = computed(() => (eventResults.data.value?.items ?? [])
  .filter(candidate => !props.linkedEvents.some(current => current.id === candidate.id)))
const todoChoices = computed(() => (todoResults.data.value?.items ?? [])
  .filter(candidate => !props.linkedTodos.some(current => current.id === candidate.id)))

function findEvents(page = 1, useCurrentKeywords = true) {
  if (useCurrentKeywords) eventSearch.value = keywords.value.trim()
  eventPage.value = page
  return eventResults.run()
}

function findTodos(page = 1) {
  todoPage.value = page
  return todoResults.run()
}

function toggleEvent(event: WorkEvent) {
  events.value = events.value.some(entry => entry.id === event.id)
    ? events.value.filter(entry => entry.id !== event.id)
    : [...events.value, event]
}

function toggleTodo(todo: Todo) {
  todos.value = todos.value.some(entry => entry.id === todo.id)
    ? todos.value.filter(entry => entry.id !== todo.id)
    : [...todos.value, todo]
}
</script>

<template>
  <div class="attachment-fields form-grid-2">
    <div>
      <h3>Events</h3>
      <label class="field">
        <span class="field-label">Keywords</span>
        <input v-model="keywords" type="search" @keydown.enter.prevent="findEvents()" />
      </label>
      <button type="button" class="ghost-btn" :disabled="eventResults.loading.value" @click="findEvents()">Find events</button>
      <p v-if="eventResults.loading.value" class="meta" role="status">Looking up events…</p>
      <p v-else-if="eventResults.error.value" class="error-banner" role="alert">{{ eventResults.error.value }}</p>
      <template v-else-if="eventResults.data.value">
        <ul v-if="eventChoices.length" class="choices">
          <li v-for="event in eventChoices" :key="event.id">
            <label class="checkbox-field">
              <input type="checkbox" :checked="events.some(entry => entry.id === event.id)" @change="toggleEvent(event)" />
              {{ event.summary || `Event #${event.id}` }}
            </label>
          </li>
        </ul>
        <p v-else class="meta">No new events on this page.</p>
        <div v-if="eventResults.data.value.pages > 1" class="pagination">
          <button v-if="eventPage > 1" type="button" class="ghost-btn" @click="findEvents(eventPage - 1, false)">Previous</button>
          <span>Page {{ eventPage }} of {{ eventResults.data.value.pages }}</span>
          <button v-if="eventPage < eventResults.data.value.pages" type="button" class="ghost-btn" @click="findEvents(eventPage + 1, false)">Next</button>
        </div>
      </template>
    </div>
    <div>
      <h3>To-dos</h3>
      <button type="button" class="ghost-btn" :disabled="todoResults.loading.value" @click="findTodos()">Find to-dos</button>
      <p v-if="todoResults.loading.value" class="meta" role="status">Looking up to-dos…</p>
      <p v-else-if="todoResults.error.value" class="error-banner" role="alert">{{ todoResults.error.value }}</p>
      <template v-else-if="todoResults.data.value">
        <ul v-if="todoChoices.length" class="choices">
          <li v-for="todo in todoChoices" :key="todo.id">
            <label class="checkbox-field">
              <input type="checkbox" :checked="todos.some(entry => entry.id === todo.id)" @change="toggleTodo(todo)" />
              {{ todo.title }}
            </label>
          </li>
        </ul>
        <p v-else class="meta">No new to-dos on this page.</p>
        <div v-if="todoResults.data.value.pages > 1" class="pagination">
          <button v-if="todoPage > 1" type="button" class="ghost-btn" @click="findTodos(todoPage - 1)">Previous</button>
          <span>Page {{ todoPage }} of {{ todoResults.data.value.pages }}</span>
          <button v-if="todoPage < todoResults.data.value.pages" type="button" class="ghost-btn" @click="findTodos(todoPage + 1)">Next</button>
        </div>
      </template>
    </div>
  </div>
  <ul v-if="events.length || todos.length" class="attachment-selection">
    <li v-for="event in events" :key="`event-${event.id}`">
      <RouterLink :to="`/event/${event.id}`">{{ event.summary || `Event #${event.id}` }}</RouterLink>
      <button type="button" class="ghost-btn" @click="toggleEvent(event)">Remove event</button>
    </li>
    <li v-for="todo in todos" :key="`todo-${todo.id}`">
      <span>{{ todo.title }}</span>
      <button type="button" class="ghost-btn" @click="toggleTodo(todo)">Remove to-do</button>
    </li>
  </ul>
</template>

<style scoped>
.attachment-fields { margin-top: 10px; }
.attachment-fields h3 { font-size: .92rem; margin-bottom: 4px; }
.attachment-fields .field { margin-bottom: 6px; }
.choices, .attachment-selection { margin: 8px 0; list-style: none; }
.choices li, .attachment-selection li { margin: 5px 0; }
.choices label, .attachment-selection li { display: flex; align-items: baseline; gap: 8px; }
.attachment-selection li, .pagination { flex-wrap: wrap; }
</style>

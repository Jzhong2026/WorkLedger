<script setup lang="ts">
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import { useToast } from '@/stores/toast'
import StatCard from '@/components/StatCard.vue'
import TodoCard from '@/components/TodoCard.vue'
import EmptyState from '@/components/EmptyState.vue'

const toast = useToast()
const today = new Date().toISOString().slice(0, 10)
const { data: todos, loading, run } = useAsync(() => api.todayTodos())
const { data: all } = useAsync(() => api.listTodos({ page_size: 100 }))

const stats = computed(() => {
  const items = all.value?.items ?? []
  return {
    pending: items.filter(t => t.status === 'pending').length,
    waiting: items.filter(t => t.status === 'waiting').length,
    done: items.filter(t => t.status === 'done').length,
  }
})

const title = ref('')
const followup = ref('')
async function addTodo() {
  if (!title.value.trim()) return
  await api.createTodo({ title: title.value, next_followup: followup.value || null })
  title.value = ''; followup.value = ''
  toast.success('To-do added')
  run()
}
async function onComplete(id: number) { await api.updateTodo(id, { status: 'done' }); run() }
async function onReopen(id: number) { await api.updateTodo(id, { status: 'pending' }); run() }
async function onWait(id: number) {
  const target = prompt('Waiting for whom/what?')
  if (target === null) return
  await api.updateTodo(id, { status: 'waiting', wait_target: target }); run()
}
async function onRemove(id: number) {
  if (!confirm('Delete this to-do?')) return
  await api.deleteTodo(id); run()
}
</script>

<template>
  <h1>Today <small>{{ today }}</small></h1>
  <div class="stat-row">
    <StatCard :value="stats.pending" label="Pending" />
    <StatCard :value="stats.waiting" label="Waiting" tone="gold" />
    <StatCard :value="stats.done" label="Done" tone="rust" />
  </div>

  <h2>Follow-ups</h2>
  <div v-if="loading" class="loading">Loading…</div>
  <div v-else-if="todos && todos.length" class="card-list">
    <TodoCard v-for="t in todos" :key="t.id" :todo="t" @complete="onComplete" @reopen="onReopen" @wait="onWait" @remove="onRemove" />
  </div>
  <EmptyState v-else illustration message="Nothing needs follow-up today. Enjoy the clear page." />

  <h2>Quick add</h2>
  <form class="inline-form" @submit.prevent="addTodo">
    <input v-model="title" type="text" placeholder="What needs follow-up?" required />
    <input v-model="followup" type="date" title="Next follow-up date" />
    <button type="submit">Add</button>
  </form>
</template>
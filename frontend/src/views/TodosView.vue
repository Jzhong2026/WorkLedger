<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import { useToast } from '@/stores/toast'
import TodoCard from '@/components/TodoCard.vue'
import EmptyState from '@/components/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const status = ref((route.query.status as string) || '')
const { data, loading, run } = useAsync(() => api.listTodos({ status: status.value || undefined, page_size: 100 }))

const form = reactive({ title: '', description: '', status: 'pending', wait_target: '', due_date: '', next_followup: '' })
function setFilter(s: string) { status.value = s; router.replace({ query: s ? { status: s } : {} }); run() }

async function add() {
  if (!form.title.trim()) return
  await api.createTodo({
    title: form.title, description: form.description || null, status: form.status as any,
    wait_target: form.wait_target || null, due_date: form.due_date || null, next_followup: form.next_followup || null,
  })
  Object.assign(form, { title: '', description: '', wait_target: '', due_date: '', next_followup: '' })
  toast.success('To-do added'); run()
}
async function onComplete(id: number) { await api.updateTodo(id, { status: 'done' }); run() }
async function onReopen(id: number) { await api.updateTodo(id, { status: 'pending' }); run() }
async function onWait(id: number) {
  const target = prompt('Waiting for whom/what?')
  if (target === null) return
  await api.updateTodo(id, { status: 'waiting', wait_target: target }); run()
}
async function onRemove(id: number) { if (confirm('Delete this to-do?')) { await api.deleteTodo(id); run() } }
</script>

<template>
  <h1>To-dos <small>({{ data?.total ?? 0 }})</small></h1>
  <div class="filter-tabs">
    <a href="#" :class="{ active: !status }" @click.prevent="setFilter('')">All</a>
    <a href="#" :class="{ active: status === 'pending' }" @click.prevent="setFilter('pending')">Pending</a>
    <a href="#" :class="{ active: status === 'waiting' }" @click.prevent="setFilter('waiting')">Waiting</a>
    <a href="#" :class="{ active: status === 'done' }" @click.prevent="setFilter('done')">Done</a>
  </div>

  <div v-if="loading" class="loading">Loading…</div>
  <div v-else-if="data && data.items.length" class="card-list">
    <TodoCard v-for="t in data.items" :key="t.id" :todo="t" @complete="onComplete" @reopen="onReopen" @wait="onWait" @remove="onRemove" />
  </div>
  <EmptyState v-else illustration message="No to-dos with this status. Add one below." />

  <h2>Add to-do</h2>
  <form id="add-todo" @submit.prevent="add">
    <input v-model="form.title" type="text" placeholder="Title" required />
    <textarea v-model="form.description" placeholder="Description (optional)" rows="2"></textarea>
    <select v-model="form.status"><option value="pending">Pending</option><option value="waiting">Waiting</option></select>
    <input v-model="form.wait_target" type="text" placeholder="Waiting for (optional)" />
    <input v-model="form.due_date" type="date" title="Due date" />
    <input v-model="form.next_followup" type="date" title="Next follow-up" />
    <button type="submit">Add</button>
  </form>
</template>
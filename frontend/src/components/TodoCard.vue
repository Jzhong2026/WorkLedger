<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import Badge from './Badge.vue'
import type { Todo } from '@/types'

const props = defineProps<{ todo: Todo }>()
const emit = defineEmits<{ complete: [id: number]; reopen: [id: number]; wait: [id: number]; remove: [id: number] }>()

const today = new Date().toISOString().slice(0, 10)
const overdue = computed(() => !!props.todo.due_date && props.todo.due_date < today && props.todo.status !== 'done')
</script>

<template>
  <div class="card" :class="{ overdue }">
    <div class="card-header">
      <Badge :variant="todo.status" :label="todo.status" />
      <Badge v-if="overdue" variant="overdue" label="overdue" />
      <strong>{{ todo.title }}</strong>
    </div>
    <p v-if="todo.description">{{ todo.description }}</p>
    <div class="card-meta">
      <span v-if="todo.due_date">Due {{ todo.due_date }}</span>
      <span v-if="todo.next_followup">Follow-up {{ todo.next_followup }}</span>
      <span v-if="todo.wait_target">Waiting on {{ todo.wait_target }}</span>
      <RouterLink v-if="todo.event_id" :to="`/event/${todo.event_id}`">Linked event</RouterLink>
    </div>
    <div class="card-actions">
      <button v-if="todo.status !== 'done'" @click="emit('complete', todo.id)">Done</button>
      <button v-if="todo.status !== 'done'" class="danger" @click="emit('wait', todo.id)">Wait</button>
      <button v-if="todo.status === 'done'" @click="emit('reopen', todo.id)">Reopen</button>
      <button class="danger" @click="emit('remove', todo.id)">Delete</button>
    </div>
  </div>
</template>
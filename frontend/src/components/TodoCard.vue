<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Badge from './Badge.vue'
import type { Todo } from '@/types'

const props = defineProps<{
  todo: Todo
  today: string
  busy?: boolean
  saveWaiting: (id: number, target: string, date: string | null) => Promise<boolean>
}>()
const emit = defineEmits<{
  complete: [id: number]
  reopen: [id: number]
  remove: [id: number]
}>()

const overdue = computed(() => props.todo.status !== 'done'
  && [props.todo.due_date, props.todo.next_followup].some(date => date && date < props.today))

const editingWait = ref(false)
const target = ref('')
const followup = ref('')
const targetField = ref<HTMLInputElement>()
const waitButton = ref<HTMLButtonElement>()

async function openWait() {
  target.value = props.todo.wait_target ?? ''
  followup.value = props.todo.next_followup ?? ''
  editingWait.value = true
  await nextTick()
  targetField.value?.focus()
}

async function cancelWait() {
  editingWait.value = false
  await nextTick()
  waitButton.value?.focus()
}

async function saveWait() {
  if (await props.saveWaiting(props.todo.id, target.value.trim(), followup.value || null)) {
    await cancelWait()
  }
}
</script>

<template>
  <article class="card" :class="{ overdue }">
    <div class="card-header">
      <Badge :variant="todo.status" :label="todo.status" />
      <Badge v-if="overdue" variant="overdue" label="overdue" />
      <strong>{{ todo.title }}</strong>
    </div>
    <p v-if="todo.description">{{ todo.description }}</p>
    <div class="card-meta">
      <span v-if="todo.due_date">Due {{ todo.due_date }}</span>
      <span v-if="todo.next_followup">Follow-up {{ todo.next_followup }}</span>
      <span v-if="todo.wait_target && todo.status === 'waiting'">Waiting on {{ todo.wait_target }}</span>
      <RouterLink v-if="todo.event_id" :to="`/event/${todo.event_id}`">Linked event</RouterLink>
    </div>

    <form v-if="editingWait" class="wait-form" @submit.prevent="saveWait">
      <div class="form-grid-2">
        <label class="field">
          <span class="field-label">Waiting for</span>
          <input ref="targetField" v-model="target" type="text" />
        </label>
        <label class="field">
          <span class="field-label">Follow-up date</span>
          <input v-model="followup" type="date" />
        </label>
      </div>
      <div class="card-actions">
        <button type="submit" :disabled="busy">Save waiting details</button>
        <button type="button" class="ghost-btn" :disabled="busy" @click="cancelWait">Cancel</button>
      </div>
    </form>

    <div v-else class="card-actions">
      <button v-if="todo.status !== 'done'" type="button" :disabled="busy" @click="emit('complete', todo.id)">Done</button>
      <button
        v-if="todo.status !== 'done'"
        ref="waitButton"
        type="button"
        class="ghost-btn"
        :disabled="busy"
        @click="openWait"
      >{{ todo.status === 'waiting' ? 'Edit waiting details' : 'Wait' }}</button>
      <button v-if="todo.status !== 'pending'" type="button" class="ghost-btn" :disabled="busy" @click="emit('reopen', todo.id)">
        {{ todo.status === 'done' ? 'Reopen' : 'Mark pending' }}
      </button>
      <button type="button" class="danger" :disabled="busy" @click="emit('remove', todo.id)">Delete</button>
    </div>
  </article>
</template>

<style scoped>
.wait-form { margin-top: 12px; }
</style>

<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError, errorMessage } from '@/api/client'
import { workItemsApi } from '@/api/workItems'
import { useWindowFocusRefresh } from '@/composables/useWindowFocusRefresh'
import Badge from '@/components/Badge.vue'
import EventCard from '@/components/EventCard.vue'
import WorkAttachments from '@/components/WorkAttachments.vue'
import WorkStateFields from '@/components/WorkStateFields.vue'
import {
  currentWorkState, displayWorkTimestamp, isStale, normalizedWorkState, stageInfo, submissionSourceKey,
} from '@/utils/workItems'
import type { Todo, WorkEvent } from '@/types'
import type { WorkHandoff, WorkItemContext, WorkItemState } from '@/types/workItems'

const props = defineProps<{ id: string }>()
const id = computed(() => Number(props.id))
const detail = ref<WorkItemContext>()
const loading = ref(false)
const readError = ref('')
const saving = ref(false)
const conflict = ref(false)
const saveError = ref('')
const status = ref('')
const summary = ref('')
const initial = ref(currentWorkState())
const state = ref(currentWorkState())
const expectedVersion = ref(0)
const selectedEvents = ref<WorkEvent[]>([])
const selectedTodos = ref<Todo[]>([])
const addTodo = ref(false)
const todoTitle = ref('')
const todoDescription = ref('')
const dueDate = ref('')
const followupDate = ref('')

const handoffKey = submissionSourceKey('work-handoff')
let pendingSave: { key: string; fingerprint: string } | undefined
let contextRequest = 0
onScopeDispose(() => { contextRequest++ })

function changedState(): Partial<WorkItemState> {
  const values = normalizedWorkState(state.value)
  const fields = Object.keys(values) as Array<keyof WorkItemState>
  return Object.fromEntries(fields
    .filter(field => values[field] !== initial.value[field])
    .map(field => [field, values[field]]))
}

function draftHasChanges() {
  return Boolean(summary.value.trim() || selectedEvents.value.length || selectedTodos.value.length
    || (addTodo.value && (todoTitle.value.trim() || todoDescription.value.trim() || dueDate.value || followupDate.value))
    || Object.keys(changedState()).length)
}

function adopt(item: WorkItemContext['item'], keep: Partial<WorkItemState> = {}) {
  expectedVersion.value = item.version
  initial.value = normalizedWorkState(currentWorkState(item))
  state.value = { ...initial.value, ...keep }
  conflict.value = false
}

function clearHandoff() {
  summary.value = ''
  selectedEvents.value = []
  selectedTodos.value = []
  addTodo.value = false
  todoTitle.value = ''
  todoDescription.value = ''
  dueDate.value = ''
  followupDate.value = ''
  saveError.value = ''
  pendingSave = undefined
}

async function loadContext(rebase = false) {
  const current = ++contextRequest
  const itemId = id.value
  if (!Number.isSafeInteger(itemId) || itemId < 1) {
    readError.value = 'Work item not found.'
    return
  }
  loading.value = true
  readError.value = ''
  try {
    const result = await workItemsApi.context(itemId)
    if (current !== contextRequest) return
    const priorSave = pendingSave
    const savedEarlier = priorSave && result.history.some(entry => entry.source_key === priorSave.key)
    const sameDraft = savedEarlier && JSON.stringify(handoffPayload()) === priorSave.fingerprint
    const hasDraft = detail.value && draftHasChanges()
    if (sameDraft) {
      adopt(result.item)
      clearHandoff()
      status.value = 'Handoff already saved. The latest progress is loaded.'
    } else if (!hasDraft || rebase) {
      const edits = rebase && hasDraft ? changedState() : {}
      adopt(result.item, edits)
      if (rebase) {
        saveError.value = ''
        status.value = `Latest version ${result.item.version} loaded. Review your draft before saving.`
      }
    } else if (expectedVersion.value !== result.item.version) {
      conflict.value = true
      status.value = ''
    }
    if (savedEarlier) pendingSave = undefined
    detail.value = result
  } catch (error) {
    if (current === contextRequest) readError.value = errorMessage(error)
  } finally {
    if (current === contextRequest) loading.value = false
  }
}

watch(id, () => {
  detail.value = undefined
  status.value = ''
  conflict.value = false
  saving.value = false
  clearHandoff()
  void loadContext()
}, { immediate: true })
useWindowFocusRefresh(() => {
  if (!loading.value && !saving.value) return loadContext()
})

function handoffPayload(): WorkHandoff {
  const payload: WorkHandoff = {
    expected_version: expectedVersion.value,
    summary: summary.value.trim(),
    ...changedState(),
  }
  if (selectedEvents.value.length) payload.event_ids = selectedEvents.value.map(event => event.id).sort((a, b) => a - b)
  if (selectedTodos.value.length) payload.todo_ids = selectedTodos.value.map(todo => todo.id).sort((a, b) => a - b)
  if (addTodo.value) {
    payload.todo = {
      title: todoTitle.value.trim(),
      description: todoDescription.value.trim() || null,
      due_date: dueDate.value || null,
      next_followup: followupDate.value || null,
    }
  }
  return payload
}

async function save() {
  if (!detail.value || saving.value || conflict.value || !summary.value.trim()) return
  if (addTodo.value && !todoTitle.value.trim()) return
  const itemId = detail.value.item.id
  const payload = handoffPayload()
  const sourceKey = handoffKey({ itemId, ...payload })
  pendingSave = { key: sourceKey, fingerprint: JSON.stringify(payload) }
  saving.value = true
  saveError.value = ''
  status.value = ''
  const request = ++contextRequest
  loading.value = false
  try {
    const result = await workItemsApi.handoff(itemId, { ...payload, source_key: sourceKey })
    if (request !== contextRequest) return
    detail.value = result
    adopt(result.item)
    clearHandoff()
    status.value = 'Handoff saved.'
  } catch (error) {
    if (request !== contextRequest) return
    if (error instanceof ApiError && error.status === 409) {
      conflict.value = true
      pendingSave = undefined
    } else {
      saveError.value = errorMessage(error)
    }
  } finally {
    if (request === contextRequest) saving.value = false
  }
}

const item = computed(() => detail.value?.item)
const stage = computed(() => item.value && stageInfo(item.value.stage))
const history = computed(() => [...(detail.value?.history ?? [])].sort((a, b) => b.version - a.version))
const lessons = computed(() => detail.value?.related_lessons ?? [])
const progressLink = computed(() => ({
  path: '/work-items', query: item.value?.project_id ? { project_id: item.value.project_id } : {},
}))
const learningLink = computed(() => ({
  path: '/learning',
  query: { work_item_id: item.value?.id, q: item.value?.title },
}))

function timelineEvent(id: number) {
  return detail.value?.events.find(event => event.id === id)
    ?? (detail.value?.source_event?.id === id ? detail.value.source_event : undefined)
}

function timelineTodo(id: number) {
  return detail.value?.todos.find(todo => todo.id === id)
}
</script>

<template>
  <div class="detail-actions">
    <RouterLink :to="progressLink">Project progress</RouterLink>
    <button type="button" class="ghost-btn" :disabled="loading || saving" @click="loadContext()">Refresh</button>
  </div>
  <div v-if="readError" class="error-banner">
    <span role="alert">{{ readError }}</span>
    <button type="button" :disabled="loading || saving" @click="loadContext()">Retry</button>
  </div>
  <div v-if="loading && !detail" class="loading" role="status">Loading work item…</div>

  <template v-if="item && detail && stage">
    <h1>{{ item.title }}</h1>
    <div class="event-head">
      <Badge :variant="stage.badge" :label="stage.label" />
      <Badge v-if="item.jira_key" variant="type" :label="item.jira_key" />
      <Badge v-if="item.needs_decision" variant="warn" label="Decision needed" />
      <Badge v-if="isStale(item)" variant="warn" label="7+ days without an update" />
    </div>
    <div class="detail-grid work-status">
      <dl>
        <template v-if="item.goal"><dt>Goal</dt><dd>{{ item.goal }}</dd></template>
        <dt>Next owner</dt><dd>{{ item.owner || 'Unassigned' }}</dd>
        <dt>Last verified</dt><dd>{{ item.last_verified_result || 'No verified result recorded' }}</dd>
        <template v-if="item.blocker"><dt>Blocker</dt><dd>{{ item.blocker }}</dd></template>
        <template v-if="item.next_step"><dt>Next step</dt><dd>{{ item.next_step }}</dd></template>
        <template v-if="item.followup_date"><dt>Follow up</dt><dd>{{ item.followup_date }}</dd></template>
        <template v-if="item.linked_followup_date"><dt>Linked to-do due</dt><dd>{{ item.linked_followup_date }}</dd></template>
        <dt>Updated</dt><dd>{{ displayWorkTimestamp(item.updated_at) }} · Version {{ item.version }}</dd>
      </dl>
    </div>

    <section aria-labelledby="handoff-title">
      <h2 id="handoff-title">Record a handoff</h2>
      <form class="form-card handoff" @submit.prevent="save">
        <fieldset class="plain-fieldset" :disabled="saving">
          <label class="field handoff-summary">
            <span class="field-label">What changed</span>
            <textarea v-model="summary" rows="3" required></textarea>
          </label>
          <WorkStateFields v-model="state" />

          <details class="handoff-options">
            <summary>Link existing events and to-dos</summary>
            <WorkAttachments
              v-model:events="selectedEvents"
              v-model:todos="selectedTodos"
              :linked-events="detail.events"
              :linked-todos="detail.todos"
              :project-id="item.project_id"
            />
          </details>

          <label class="field checkbox-field handoff-options">
            <input v-model="addTodo" type="checkbox" />
            <span class="field-label">Create a follow-up to-do</span>
          </label>
          <div v-if="addTodo" class="form-grid-2 todo-fields">
            <label class="field form-span">
              <span class="field-label">To-do title</span>
              <input v-model="todoTitle" type="text" required />
            </label>
            <label class="field form-span">
              <span class="field-label">To-do description</span>
              <textarea v-model="todoDescription" rows="2"></textarea>
            </label>
            <label class="field">
              <span class="field-label">To-do due date</span>
              <input v-model="dueDate" type="date" />
            </label>
            <label class="field">
              <span class="field-label">To-do follow-up date</span>
              <input v-model="followupDate" type="date" />
            </label>
          </div>

          <div v-if="conflict" class="error-banner" role="alert">
            <p>The item has a newer version. Load it to keep your draft and review the current progress.</p>
            <button type="button" :disabled="loading" @click="loadContext(true)">Load latest and keep draft</button>
          </div>
          <p v-else-if="saveError" class="error-banner" role="alert">
            {{ saveError }} Your draft is still here. Retry Save handoff.
          </p>
          <p v-if="status" class="meta save-message" role="status">{{ status }}</p>
          <div class="form-actions">
            <button type="submit" :disabled="conflict">{{ saving ? 'Saving…' : 'Save handoff' }}</button>
          </div>
        </fieldset>
      </form>
    </section>

    <section aria-labelledby="timeline-title">
      <h2 id="timeline-title">Handoff timeline</h2>
      <ol v-if="history.length" class="card-list timeline-list">
        <li v-for="entry in history" :key="entry.id" class="card">
          <div class="card-header">
            <strong>{{ entry.summary }}</strong>
            <Badge :variant="stageInfo(entry.stage).badge" :label="stageInfo(entry.stage).label" />
          </div>
          <div class="card-meta">
            <span>Version {{ entry.version }}</span>
            <span>{{ displayWorkTimestamp(entry.created_at) }}</span>
            <span v-if="entry.actor">{{ entry.actor }}</span>
            <span v-if="entry.previous_stage && entry.previous_stage !== entry.stage">
              {{ stageInfo(entry.previous_stage).label }} → {{ stageInfo(entry.stage).label }}
            </span>
          </div>
          <p v-if="entry.owner"><strong>Next owner</strong> {{ entry.owner }}</p>
          <p v-if="entry.last_verified_result"><strong>Last verified</strong> {{ entry.last_verified_result }}</p>
          <p v-if="entry.blocker"><strong>Blocker</strong> {{ entry.blocker }}</p>
          <p v-if="entry.next_step"><strong>Next step</strong> {{ entry.next_step }}</p>
          <p v-if="entry.followup_date"><strong>Follow up</strong> {{ entry.followup_date }}</p>
          <div class="card-meta">
            <RouterLink
              v-for="eventId in new Set([...(entry.linked_event_ids ?? []), ...(entry.event_id ? [entry.event_id] : [])])"
              :key="eventId"
              :to="`/event/${eventId}`"
            >{{ timelineEvent(eventId)?.summary || `Event #${eventId}` }}</RouterLink>
            <a
              v-for="todoId in new Set([...(entry.linked_todo_ids ?? []), ...(entry.todo_id ? [entry.todo_id] : [])])"
              :key="todoId"
              :href="`#linked-todo-${todoId}`"
            >{{ timelineTodo(todoId)?.title || `To-do #${todoId}` }}</a>
          </div>
        </li>
      </ol>
      <p v-else class="meta">No handoffs recorded yet.</p>
    </section>

    <section aria-labelledby="sources-title">
      <h2 id="sources-title">Source and Jira hierarchy</h2>
      <div v-if="detail.source_event || detail.parent_event || detail.child_events.length" class="card-list">
        <template v-if="detail.source_event">
          <h3>Source record</h3>
          <EventCard :event="detail.source_event" />
        </template>
        <template v-if="detail.parent_event">
          <h3>Parent issue</h3>
          <EventCard :event="detail.parent_event" />
        </template>
        <template v-if="detail.child_events.length">
          <h3>Subtasks</h3>
          <EventCard v-for="event in detail.child_events" :key="event.id" :event="event" />
        </template>
      </div>
      <p v-else class="meta">
        No Jira source is linked.
        <RouterLink :to="{ path: '/search', query: { jira_key: item.jira_key } }">Search local records</RouterLink>
      </p>
    </section>

    <section aria-labelledby="linked-events-title">
      <h2 id="linked-events-title">Linked events and evidence</h2>
      <div v-if="detail.events.length" class="card-list">
        <EventCard v-for="event in detail.events" :key="event.id" :event="event" />
      </div>
      <p v-else class="meta">No linked events yet.</p>
    </section>
    <section aria-labelledby="linked-todos-title">
      <h2 id="linked-todos-title">Linked to-dos</h2>
      <ul v-if="detail.todos.length" class="card-list timeline-list">
        <li v-for="todo in detail.todos" :id="`linked-todo-${todo.id}`" :key="todo.id" class="card">
          <div class="card-header"><strong>{{ todo.title }}</strong><Badge :variant="todo.status" :label="todo.status" /></div>
          <p v-if="todo.description">{{ todo.description }}</p>
          <div class="card-meta">
            <span v-if="todo.due_date">Due {{ todo.due_date }}</span>
            <span v-if="todo.next_followup">Follow up {{ todo.next_followup }}</span>
            <span v-if="todo.wait_target">Waiting on {{ todo.wait_target }}</span>
          </div>
        </li>
      </ul>
      <p v-else class="meta">No linked to-dos yet.</p>
      <RouterLink to="/todos">Manage to-dos</RouterLink>
    </section>

    <section aria-labelledby="lessons-title">
      <div class="section-heading">
        <h2 id="lessons-title">Related lessons</h2>
        <RouterLink :to="learningLink">Open Learning</RouterLink>
      </div>
      <div v-if="detail.related_lessons_error" class="error-banner">
        <span role="alert">Could not load lessons. {{ detail.related_lessons_error }}</span>
        <button type="button" :disabled="loading || saving" @click="loadContext()">Retry lessons</button>
      </div>
      <div v-if="lessons.length" class="card-list">
        <article v-for="lesson in lessons" :key="lesson.id" class="card">
          <div class="card-header">
            <RouterLink :to="{ path: '/learning', query: { lesson_id: lesson.id, work_item_id: item.id } }">
              <strong>{{ lesson.title }}</strong>
            </RouterLink>
          </div>
          <p v-if="lesson.trigger"><strong>When to use</strong> {{ lesson.trigger }}</p>
          <p v-if="lesson.first_step"><strong>First step</strong> {{ lesson.first_step }}</p>
          <p v-if="lesson.limits"><strong>Limits</strong> {{ lesson.limits }}</p>
          <p v-if="lesson.reasons?.length">{{ lesson.reasons.join(' · ') }}</p>
          <div class="card-meta">
            <RouterLink v-if="lesson.source_work_item_id" :to="`/work-items/${lesson.source_work_item_id}`">
              {{ lesson.source_work_item_title || `Work item #${lesson.source_work_item_id}` }}
            </RouterLink>
            <RouterLink v-if="lesson.source_event_id" :to="`/event/${lesson.source_event_id}`">
              {{ lesson.source_event_summary || `Event #${lesson.source_event_id}` }}
            </RouterLink>
            <a v-if="lesson.evidence_url" :href="lesson.evidence_url" rel="noopener" target="_blank">Lesson evidence</a>
          </div>
        </article>
      </div>
      <p v-else-if="!detail.related_lessons_error" class="meta">No reviewed lessons match this item yet.</p>
    </section>
  </template>
</template>

<style scoped>
.detail-actions, .section-heading { display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline; justify-content: space-between; }
.detail-actions { margin-bottom: 12px; }
.work-status { margin-top: 14px; }
.work-status dd { white-space: pre-wrap; }
.plain-fieldset { border: 0; min-width: 0; }
.handoff-summary { margin-bottom: 14px; }
.handoff-options, .handoff .error-banner, .save-message { margin-top: 12px; }
.handoff-options summary { cursor: pointer; font-weight: 600; }
.todo-fields { margin: 8px 0 12px; }
.timeline-list { list-style: none; }
.timeline-list li { scroll-margin-top: calc(var(--topbar-h) + 12px); }
h3 { font-size: .9rem; margin-top: 6px; }
</style>

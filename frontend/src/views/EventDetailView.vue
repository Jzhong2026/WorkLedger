<script setup lang="ts">
import { computed, ref, reactive, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError, api, errorMessage } from '@/api/client'
import { useToast } from '@/stores/toast'
import Badge from '@/components/Badge.vue'
import { displayType } from '@/utils/eventDisplay'
import type { WorkEvent } from '@/types'

const props = defineProps<{ id: string }>()
const toast = useToast()
const event = ref<WorkEvent | null>(null)
const occurredLabel = computed(() => {
  if (event.value?.source_agent !== 'jira-import') return 'Occurred'
  try {
    if (JSON.parse(event.value.extra_json ?? '{}')?.occurred_at_basis === 'jira_created') return 'Created in Jira'
  } catch { /* Legacy records may lack structured metadata. */ }
  return 'Imported (source date unavailable)'
})
const parent = ref<WorkEvent | null>(null)
const children = ref<WorkEvent[]>([])
const loading = ref(true)
const relatedLoading = ref(false)
const loadError = ref('')
const relatedError = ref('')
const snapBusy = ref(false)
const saveBusy = ref(false)
let requestId = 0

const form = reactive({
  summary: '', detail: '', evidence_url: '', root_cause: '', root_cause_confirmed: false,
  verification_result: '', verification_done: false,
})

function updateForm(record: WorkEvent) {
  Object.assign(form, {
    summary: record.summary,
    detail: record.detail ?? '',
    evidence_url: record.evidence_url ?? '',
    root_cause: record.root_cause ?? '',
    root_cause_confirmed: record.root_cause_confirmed,
    verification_result: record.verification_result ?? '',
    verification_done: record.verification_done,
  })
}

async function loadRelated(record: WorkEvent, request = requestId) {
  relatedLoading.value = true
  relatedError.value = ''
  const [parentResult, childResult] = await Promise.allSettled([
    record.parent_event_id ? api.getEvent(record.parent_event_id) : Promise.resolve(null),
    api.getChildren(record.id),
  ])
  if (request !== requestId) return
  if (parentResult.status === 'fulfilled') parent.value = parentResult.value
  if (childResult.status === 'fulfilled') children.value = childResult.value
  if (parentResult.status === 'rejected' || childResult.status === 'rejected') {
    relatedError.value = 'Some related events could not be loaded.'
  }
  relatedLoading.value = false
}

async function load() {
  const request = ++requestId
  loading.value = true
  relatedLoading.value = false
  snapBusy.value = false
  saveBusy.value = false
  loadError.value = ''
  relatedError.value = ''
  event.value = null
  parent.value = null
  children.value = []
  try {
    const record = await api.getEvent(Number(props.id))
    if (request !== requestId) return
    event.value = record
    updateForm(record)
    void loadRelated(record, request)
  } catch (error) {
    if (request !== requestId) return
    loadError.value = error instanceof ApiError && error.status === 404 ? 'Event not found.' : errorMessage(error)
  } finally {
    if (request === requestId) loading.value = false
  }
}
watch(() => props.id, load, { immediate: true })

async function save() {
  if (!event.value || saveBusy.value || snapBusy.value) return
  const request = requestId
  const record = event.value
  saveBusy.value = true
  try {
    const changes = {
      summary: form.summary.trim(),
      detail: form.detail.trim() || null,
      evidence_url: form.evidence_url.trim() || null,
      root_cause: form.root_cause.trim() || null,
      root_cause_confirmed: form.root_cause.trim() || !record.root_cause ? form.root_cause_confirmed : false,
      verification_result: form.verification_result.trim() || null,
      verification_done: form.verification_result.trim() || !record.verification_result ? form.verification_done : false,
    }
    const patch = Object.fromEntries(
      (Object.keys(changes) as Array<keyof typeof changes>)
        .filter(field => typeof changes[field] === 'boolean'
          ? changes[field] !== record[field]
          : form[field] !== (record[field] ?? ''))
        .map(field => [field, changes[field]]),
    )
    if (!Object.keys(patch).length) return
    const updated = await api.updateEvent(record.id, patch)
    if (request !== requestId) return
    event.value = updated
    updateForm(updated)
    toast.success('Saved')
  } catch (error) {
    if (request === requestId) toast.error(errorMessage(error))
  } finally {
    if (request === requestId) saveBusy.value = false
  }
}

async function snapshot() {
  if (!event.value || snapBusy.value || saveBusy.value) return
  const request = requestId
  const id = event.value.id
  snapBusy.value = true
  try {
    const result = await api.snapshotEvent(id)
    if (request !== requestId) return
    if (result.snapshot_status === 'captured') toast.success('Evidence snapshot captured')
    else toast.error(result.error || 'Evidence could not be captured. Check the URL and retry.')
    const record = await api.getEvent(id)
    if (request === requestId) event.value = record
  } catch (error) {
    if (request === requestId) toast.error(errorMessage(error))
  } finally {
    if (request === requestId) snapBusy.value = false
  }
}
</script>

<template>
  <div v-if="loading" class="loading">Loading…</div>
  <template v-else-if="event">
    <div class="event-head">
      <Badge :variant="displayType(event).variant" :label="displayType(event).label" />
      <Badge v-if="event.jira_key" variant="type" :label="event.jira_key" />
      <Badge v-if="event.user_edited" variant="warn" label="edited" />
    </div>
    <h1>{{ event.summary || 'Event detail' }}</h1>
    <div class="card-actions event-actions">
      <RouterLink
        :to="{ name: 'work-items', query: {
          discover: '1', source_event_id: event.id, project_id: event.project_id || undefined,
        } }"
      >Track as work item</RouterLink>
      <RouterLink :to="{ name: 'retrospective', query: { event: event.id, entry: 'accomplishment' } }">Create accomplishment</RouterLink>
      <RouterLink :to="{ name: 'retrospective', query: { event: event.id, entry: 'case' } }">Create case</RouterLink>
    </div>

    <p v-if="relatedLoading" class="meta">Loading related events…</p>
    <p v-else-if="relatedError" role="status">
      {{ relatedError }} <button class="ghost-btn" @click="loadRelated(event)">Retry related events</button>
    </p>
    <div v-if="parent" class="hierarchy-parent">
      <span class="hierarchy-label">Part of story</span>
      <RouterLink :to="`/event/${parent.id}`">{{ parent.jira_key || '' }} {{ parent.summary }}</RouterLink>
    </div>

    <div class="detail-grid">
      <dl>
        <dt>{{ occurredLabel }}</dt><dd>{{ event.occurred_at }}</dd>
        <dt>Recorded</dt><dd>{{ event.recorded_at }}</dd>
        <template v-if="event.repo"><dt>Repo / PR</dt><dd>
          <RouterLink v-if="event.pr_number" :to="{ name: 'pr', query: { repo: event.repo, pr_number: event.pr_number } }">{{ event.repo }}#{{ event.pr_number }}</RouterLink>
          <span v-else>{{ event.repo }}</span>
        </dd></template>
        <template v-if="event.comment_id"><dt>Comment</dt><dd>{{ event.comment_id }}</dd></template>
        <template v-if="event.source_agent"><dt>Source</dt><dd>{{ event.source_agent }}</dd></template>
        <template v-if="event.evidence_url"><dt>Evidence</dt><dd><a :href="event.evidence_url" target="_blank" rel="noopener">{{ event.evidence_url }}</a></dd></template>
        <template v-if="event.reply_status"><dt>Reply status</dt><dd>{{ event.reply_status }}</dd></template>
      </dl>

      <template v-if="event.detail"><h2>Detail</h2><pre class="detail-text">{{ event.detail }}</pre></template>
      <template v-if="event.root_cause">
        <h2>Root cause <Badge v-if="!event.root_cause_confirmed" variant="warn" label="unconfirmed" /></h2>
        <p>{{ event.root_cause }}</p>
      </template>
      <template v-if="event.verification_result">
        <h2>Verification <Badge v-if="!event.verification_done" variant="warn" label="pending" /></h2>
        <p>{{ event.verification_result }}</p>
      </template>

      <div v-if="event.evidence_url || event.evidence_snapshot || event.snapshot_status" class="snapshot-box">
        <h2>Evidence snapshot <Badge v-if="event.snapshot_status" :variant="event.snapshot_status === 'captured' ? 'ok' : 'warn'" :label="event.snapshot_status" /></h2>
        <template v-if="event.evidence_url">
          <p class="meta">Capturing requests the evidence page from the server and stores its text locally.</p>
          <div class="card-actions">
            <button :disabled="snapBusy || saveBusy" @click="snapshot">{{ snapBusy ? 'Capturing…' : (event.snapshot_status ? 'Retry capture' : 'Capture snapshot') }}</button>
          </div>
        </template>
        <p v-if="event.snapshot_error" role="status">Last attempt {{ event.snapshot_attempt_at }} · {{ event.snapshot_error }}</p>
        <template v-if="event.evidence_snapshot">
          <p class="meta">Last successful capture {{ event.snapshot_at }} · {{ event.evidence_snapshot.length }} chars
            <template v-if="event.snapshot_source_url"> · {{ event.snapshot_source_url }}</template></p>
          <div class="snapshot-text">{{ event.evidence_snapshot }}</div>
        </template>
      </div>
    </div>

    <template v-if="children.length">
      <h2>Sub-tasks ({{ children.length }})</h2>
      <div class="card-list">
        <div v-for="c in children" :key="c.id" class="card subtask-card">
          <div class="card-header">
            <Badge :variant="displayType(c).variant" :label="displayType(c).label" />
            <Badge v-if="c.jira_key" variant="type" :label="c.jira_key" />
            <RouterLink :to="`/event/${c.id}`"><strong>{{ c.summary }}</strong></RouterLink>
          </div>
        </div>
      </div>
    </template>

    <h2>Edit</h2>
    <form class="edit-form" @submit.prevent="save">
      <label class="full">Summary <input v-model="form.summary" type="text" :readonly="saveBusy" /></label>
      <label class="full">Detail <textarea v-model="form.detail" rows="6" :readonly="saveBusy"></textarea></label>
      <label>Evidence URL <input v-model="form.evidence_url" type="url" :readonly="saveBusy" /></label>
      <label>Root cause <input v-model="form.root_cause" type="text" :readonly="saveBusy" /></label>
      <label class="checkbox full"><input v-model="form.root_cause_confirmed" type="checkbox" :disabled="saveBusy" /> Root cause confirmed</label>
      <label class="full">Verification<textarea v-model="form.verification_result" rows="2" :readonly="saveBusy"></textarea></label>
      <label class="checkbox full"><input v-model="form.verification_done" type="checkbox" :disabled="saveBusy" /> Verification completed</label>
      <button type="submit" :disabled="saveBusy || snapBusy">{{ saveBusy ? 'Saving…' : 'Save changes' }}</button>
    </form>
  </template>
  <div v-else class="empty" role="alert">{{ loadError }} <button class="ghost-btn" @click="load">Retry</button></div>
</template>

<style scoped>
.event-actions { gap: 14px; margin-bottom: 1rem; }
.snapshot-box { overflow-wrap: anywhere; }
</style>

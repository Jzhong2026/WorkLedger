<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import { useToast } from '@/stores/toast'
import Badge from '@/components/Badge.vue'
import { displayType } from '@/utils/eventDisplay'
import type { WorkEvent } from '@/types'

const props = defineProps<{ id: string }>()
const toast = useToast()
const event = ref<WorkEvent | null>(null)
const parent = ref<WorkEvent | null>(null)
const children = ref<WorkEvent[]>([])
const loading = ref(true)
const snapBusy = ref(false)

const form = reactive({ summary: '', detail: '', evidence_url: '', root_cause: '', root_cause_confirmed: false })

async function load() {
  loading.value = true
  try {
    const eid = Number(props.id)
    event.value = await api.getEvent(eid)
    children.value = await api.getChildren(eid)
    parent.value = event.value.parent_event_id ? await api.getEvent(event.value.parent_event_id) : null
    Object.assign(form, {
      summary: event.value.summary, detail: event.value.detail || '',
      evidence_url: event.value.evidence_url || '', root_cause: event.value.root_cause || '',
      root_cause_confirmed: event.value.root_cause_confirmed,
    })
  } catch (e) { toast.error(String(e)) } finally { loading.value = false }
}
watch(() => props.id, load, { immediate: true })

async function save() {
  if (!event.value) return
  await api.updateEvent(event.value.id, {
    summary: form.summary, detail: form.detail || null, evidence_url: form.evidence_url || null,
    root_cause: form.root_cause || null, root_cause_confirmed: form.root_cause_confirmed,
  })
  toast.success('Saved'); load()
}
async function snapshot() {
  if (!event.value) return
  snapBusy.value = true
  try { const r = await api.snapshotEvent(event.value.id); toast.success(`Snapshot ${r.snapshot_status} (${r.chars} chars)`); load() }
  catch { /* toast */ } finally { snapBusy.value = false }
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

    <div v-if="parent" class="hierarchy-parent">
      <span class="hierarchy-label">Part of story</span>
      <RouterLink :to="`/event/${parent.id}`">{{ parent.jira_key || '' }} {{ parent.summary }}</RouterLink>
    </div>

    <div class="detail-grid">
      <dl>
        <dt>Occurred</dt><dd>{{ event.occurred_at }}</dd>
        <dt>Recorded</dt><dd>{{ event.recorded_at }}</dd>
        <template v-if="event.repo"><dt>Repo / PR</dt><dd><RouterLink :to="`/pr?repo=${event.repo}&pr_number=${event.pr_number}`">{{ event.repo }}#{{ event.pr_number }}</RouterLink></dd></template>
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

      <div v-if="event.evidence_url" class="snapshot-box">
        <h2>Evidence snapshot <Badge v-if="event.snapshot_status" :variant="event.snapshot_status === 'captured' ? 'ok' : 'warn'" :label="event.snapshot_status" /></h2>
        <div class="card-actions">
          <button :disabled="snapBusy" @click="snapshot">{{ snapBusy ? 'Capturing…' : (event.snapshot_status ? 'Re-capture' : 'Capture snapshot') }}</button>
        </div>
        <template v-if="event.evidence_snapshot">
          <p class="meta">Captured {{ event.snapshot_at }} · {{ event.evidence_snapshot.length }} chars</p>
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
      <label class="full">Summary <input v-model="form.summary" type="text" /></label>
      <label class="full">Detail <textarea v-model="form.detail" rows="6"></textarea></label>
      <label>Evidence URL <input v-model="form.evidence_url" type="url" /></label>
      <label>Root cause <input v-model="form.root_cause" type="text" /></label>
      <label class="checkbox full"><input v-model="form.root_cause_confirmed" type="checkbox" /> Root cause confirmed</label>
      <button type="submit">Save changes</button>
    </form>
  </template>
  <div v-else class="empty">Event not found.</div>
</template>
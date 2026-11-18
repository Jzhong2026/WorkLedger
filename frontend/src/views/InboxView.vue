<script setup lang="ts">
import { ref } from 'vue'
import { api } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import { useToast } from '@/stores/toast'
import Badge from '@/components/Badge.vue'
import EmptyState from '@/components/EmptyState.vue'

const toast = useToast()
const { data: notes, run: reloadNotes } = useAsync(() => api.listInbox())
const { data: drafts, run: reloadDrafts } = useAsync(() => api.listDrafts())
const raw = ref('')
const busy = ref<number | null>(null)

function reload() { reloadNotes(); reloadDrafts() }

async function capture() {
  if (!raw.value.trim()) return
  await api.captureNote(raw.value)
  raw.value = ''
  toast.success('Note captured')
  reload()
}
async function structure(id: number) {
  busy.value = id
  try {
    await api.structureNote(id)
    toast.success('Structured into drafts')
    reload()
  } catch { /* toast shown by caller */ } finally { busy.value = null }
}
async function confirm(id: number) { await api.confirmDraft(id); toast.success('Draft committed'); reload() }
async function discardDraft(id: number) { await api.discardDraft(id); reload() }
async function discardNote(id: number) { await api.discardNote(id); reload() }
const noteVariant = (s: string) => s === 'committed' ? 'done' : s === 'structured' ? 'waiting' : 'pending'
</script>

<template>
  <h1>Inbox <small>capture first, organize later</small></h1>
  <form class="inline-form" @submit.prevent="capture">
    <input v-model="raw" type="text" placeholder="Dump a work note… e.g. fixed null check in PR 42, reviewer agreed" required />
    <button type="submit">Capture</button>
  </form>

  <h2>Pending drafts</h2>
  <div v-if="drafts && drafts.length" class="card-list">
    <div v-for="d in drafts" :key="d.id" class="card highlight">
      <div class="card-header">
        <Badge :variant="d.draft.event_type" :label="d.draft.event_type" />
        <strong>{{ d.draft.summary }}</strong>
      </div>
      <div class="card-meta">
        <span v-if="d.draft.repo">{{ d.draft.repo }}<template v-if="d.draft.pr_number">#{{ d.draft.pr_number }}</template></span>
        <span v-if="d.draft.root_cause">Cause: {{ d.draft.root_cause }}</span>
        <span>from note #{{ d.note_id }}</span>
      </div>
      <div class="card-actions">
        <button @click="confirm(d.id)">Confirm</button>
        <button class="danger" @click="discardDraft(d.id)">Discard</button>
      </div>
    </div>
  </div>
  <EmptyState v-else message="No drafts awaiting review." />

  <h2>Notes</h2>
  <div v-if="notes && notes.length" class="card-list">
    <div v-for="n in notes" :key="n.id" class="card">
      <div class="card-header">
        <Badge :variant="noteVariant(n.status)" :label="n.status" />
        <strong>{{ n.raw_text }}</strong>
      </div>
      <div class="card-meta"><span>{{ n.created_at }}</span></div>
      <div v-if="n.status === 'raw'" class="card-actions">
        <button :disabled="busy === n.id" @click="structure(n.id)">{{ busy === n.id ? 'Structuring…' : 'Structure with agent' }}</button>
        <button class="danger" @click="discardNote(n.id)">Discard</button>
      </div>
    </div>
  </div>
  <EmptyState v-else illustration message="Inbox is empty. Capture a note above to get started." />
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api, errorMessage } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import { useToast } from '@/stores/toast'
import Badge from '@/components/Badge.vue'
import DraftEditor from '@/components/DraftEditor.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { DraftEdit, InboxNote, WorkEvent } from '@/types'

const toast = useToast()
const { data: notes, loading: notesLoading, error: notesError, run: reloadNotes } = useAsync(() => api.listInbox())
const { data: drafts, loading: draftsLoading, error: draftsError, run: reloadDrafts } = useAsync(() => api.listDrafts())
const { data: agent } = useAsync(() => api.agentStatus())
const notesById = computed(() => new Map(notes.value?.map(note => [note.id, note])))
const agentReady = computed(() => !!(agent.value?.enabled && agent.value.key_configured && agent.value.cli_available))
const raw = ref('')
const captureBusy = ref(false)
const busy = ref(false)
const editingDraft = ref<number | null>(null)
const manualNote = ref<number | null>(null)
const entry = ref<WorkEvent | null>(null)

async function reload() {
  await Promise.all([reloadNotes(), reloadDrafts()])
}

async function capture() {
  const text = raw.value.trim()
  if (!text || captureBusy.value) return
  captureBusy.value = true
  try {
    await api.captureNote(text)
    if (raw.value.trim() === text) raw.value = ''
    await reloadNotes()
    toast.success('Note captured')
  } catch (error) {
    toast.error(errorMessage(error))
  } finally {
    captureBusy.value = false
  }
}

async function change(action: () => Promise<unknown>, success: string) {
  if (busy.value) return
  busy.value = true
  try {
    await action()
    await reload()
    toast.success(success)
  } catch (error) {
    toast.error(errorMessage(error))
  } finally {
    busy.value = false
  }
}

function startManual(note: InboxNote) {
  entry.value = null
  editingDraft.value = null
  manualNote.value = note.id
}

function structure(noteId: number) {
  void change(async () => {
    await api.structureNote(noteId)
    manualNote.value = null
  }, 'Drafts ready for review')
}

function saveDraft(id: number, data: DraftEdit) {
  void change(() => api.updateDraft(id, data), 'Draft saved')
}

function confirmDraft(id: number, data: DraftEdit) {
  void change(async () => {
    entry.value = (await api.confirmDraft(id, data)).event
    editingDraft.value = null
  }, 'Event recorded')
}

function commitNote(id: number, data: DraftEdit) {
  void change(async () => {
    entry.value = (await api.commitNote(id, data)).event
    manualNote.value = null
  }, 'Event recorded')
}

function discardDraft(id: number) {
  void change(async () => {
    await api.discardDraft(id)
    if (editingDraft.value === id) editingDraft.value = null
  }, 'Draft discarded')
}

function discardNote(note: InboxNote) {
  if (!window.confirm('Discard this note?')) return
  void change(async () => {
    await api.discardNote(note.id)
    if (manualNote.value === note.id) manualNote.value = null
  }, 'Note discarded')
}

function manualDraft(note: InboxNote): DraftEdit {
  return { event_type: 'manual', summary: note.raw_text.split(/\r?\n/, 1)[0], detail: note.raw_text }
}
</script>

<template>
  <h1>Inbox</h1>
  <form class="form-card capture-form" @submit.prevent="capture">
    <label class="field">Work note
      <textarea v-model="raw" rows="3" placeholder="What happened? Add evidence links or follow-up details if you have them." required></textarea>
    </label>
    <div class="form-actions">
      <button type="submit" :disabled="captureBusy || !raw.trim()">{{ captureBusy ? 'Capturing…' : 'Capture note' }}</button>
    </div>
  </form>

  <p class="meta" v-if="agentReady">AI drafting sends the selected work note to CodeBuddy. Manual entry stays local.</p>
  <p class="meta" v-else>Record notes manually. AI drafting becomes available when CodeBuddy is configured and enabled.</p>
  <p v-if="entry" role="status">Event recorded. <RouterLink :to="`/event/${entry.id}`">Open {{ entry.summary }}</RouterLink></p>

  <h2>Pending drafts</h2>
  <p v-if="draftsLoading && !drafts" class="loading">Loading drafts…</p>
  <p v-if="draftsError" role="alert">{{ draftsError }} <button class="ghost-btn" @click="reloadDrafts">Retry drafts</button></p>
  <div v-if="drafts?.length" class="card-list">
    <article v-for="d in drafts" :key="d.id" class="card">
      <div class="card-header">
        <Badge :variant="d.draft.event_type" :label="d.draft.event_type" />
        <strong>{{ d.draft.summary || 'Untitled draft' }}</strong>
      </div>
      <div class="card-meta">
        <span>Note #{{ d.note_id }}</span>
        <span v-if="d.draft.jira_key">{{ d.draft.jira_key }}</span>
      </div>
      <div class="card-actions">
        <button v-if="editingDraft !== d.id" :disabled="busy" @click="editingDraft = d.id; manualNote = null">Review draft</button>
        <button class="danger" :disabled="busy" @click="discardDraft(d.id)">Discard draft</button>
      </div>
      <div v-if="editingDraft === d.id">
        <h3>Original note</h3>
        <p class="raw-note">{{ notesById.get(d.note_id)?.raw_text ?? 'Original note unavailable. You can still review the draft.' }}</p>
        <DraftEditor :key="d.id" :draft="d.draft" :busy="busy" @save="saveDraft(d.id, $event)"
          @confirm="confirmDraft(d.id, $event)" @cancel="editingDraft = null" />
      </div>
    </article>
  </div>
  <EmptyState v-else-if="drafts && !draftsError" message="No drafts awaiting review." />

  <h2>Notes</h2>
  <p v-if="notesLoading && !notes" class="loading">Loading notes…</p>
  <p v-if="notesError" role="alert">{{ notesError }} <button class="ghost-btn" @click="reloadNotes">Retry notes</button></p>
  <div v-if="notes?.length" class="card-list">
    <article v-for="note in notes" :key="note.id" class="card">
      <div class="card-header">
        <Badge :variant="note.status === 'committed' ? 'done' : note.status === 'structured' ? 'waiting' : 'pending'" :label="note.status" />
        <strong class="raw-note">{{ note.raw_text }}</strong>
      </div>
      <div class="card-meta"><span>Note #{{ note.id }}</span><span>{{ note.created_at }}</span></div>
      <div v-if="note.status === 'raw'" class="card-actions">
        <button v-if="manualNote !== note.id" :disabled="busy" @click="startManual(note)">Record manually</button>
        <button v-if="agentReady" class="ghost-btn" :disabled="busy" @click="structure(note.id)">Draft with AI</button>
        <button class="danger" :disabled="busy" @click="discardNote(note)">Discard note</button>
      </div>
      <DraftEditor v-if="manualNote === note.id && note.status === 'raw'" :key="note.id" :draft="manualDraft(note)"
        :busy="busy" manual @confirm="commitNote(note.id, $event)" @cancel="manualNote = null" />
    </article>
  </div>
  <EmptyState v-else-if="notes && !notesError" message="Capture a note to start your work history." />
</template>

<style scoped>
.capture-form { margin-bottom: 1rem; }
.raw-note { white-space: pre-wrap; overflow-wrap: anywhere; min-width: 0; }
</style>

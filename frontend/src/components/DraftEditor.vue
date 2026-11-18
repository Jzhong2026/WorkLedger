<script setup lang="ts">
import { reactive } from 'vue'
import { eventTypes, type DraftEdit } from '@/types'

const props = defineProps<{ draft: DraftEdit; busy: boolean; manual?: boolean }>()
const emit = defineEmits<{ confirm: [data: DraftEdit]; save: [data: DraftEdit]; cancel: [] }>()

const form = reactive({
  event_type: props.draft.event_type ?? 'manual',
  summary: props.draft.summary ?? '',
  occurred_at: props.draft.occurred_at?.replace(' ', 'T').slice(0, 16) ?? '',
  detail: props.draft.detail ?? '',
  repo: props.draft.repo ?? '',
  pr_number: props.draft.pr_number?.toString() ?? '',
  jira_key: props.draft.jira_key ?? '',
  comment_id: props.draft.comment_id ?? '',
  evidence_url: props.draft.evidence_url ?? '',
  root_cause: props.draft.root_cause ?? '',
  root_cause_confirmed: props.draft.root_cause_confirmed ?? false,
  verification_result: props.draft.verification_result ?? '',
  verification_done: props.draft.verification_done ?? false,
  reply_status: props.draft.reply_status ?? '',
})

function payload(): DraftEdit {
  const originalDate = props.draft.occurred_at?.replace(' ', 'T').slice(0, 16) ?? ''
  return {
    event_type: form.event_type,
    summary: form.summary.trim(),
    ...(form.occurred_at !== originalDate ? { occurred_at: form.occurred_at || null } : {}),
    detail: form.detail.trim() || null,
    repo: form.repo.trim() || null,
    pr_number: form.pr_number ? Number(form.pr_number) : null,
    jira_key: form.jira_key.trim() || null,
    comment_id: form.comment_id.trim() || null,
    evidence_url: form.evidence_url.trim() || null,
    root_cause: form.root_cause.trim() || null,
    root_cause_confirmed: Boolean(form.root_cause.trim()) && form.root_cause_confirmed,
    verification_result: form.verification_result.trim() || null,
    verification_done: Boolean(form.verification_result.trim()) && form.verification_done,
    reply_status: form.reply_status || null,
  }
}

function submit(event: SubmitEvent) {
  if (!form.summary.trim()) return
  if ((event.submitter as HTMLButtonElement | null)?.value === 'save') {
    emit('save', payload())
  } else {
    emit('confirm', payload())
  }
}
</script>

<template>
  <form class="form-card draft-editor" @submit.prevent="submit">
    <div class="form-grid-2">
      <label class="field form-span">Summary<input v-model="form.summary" required /></label>
      <label class="field">Event type
        <select v-model="form.event_type">
          <option v-for="type in eventTypes" :key="type" :value="type">{{ type.replaceAll('_', ' ') }}</option>
        </select>
      </label>
      <label class="field">Occurred at<input v-model="form.occurred_at" type="datetime-local" /></label>
      <label class="field form-span">Details<textarea v-model="form.detail" rows="3"></textarea></label>
      <label class="field form-span">Evidence URL<input v-model="form.evidence_url" type="url" /></label>
      <label class="field">Repository<input v-model="form.repo" /></label>
      <label class="field">PR number<input v-model="form.pr_number" type="number" min="1" step="1" /></label>
      <label class="field">Jira key<input v-model="form.jira_key" /></label>
      <label class="field">Comment ID<input v-model="form.comment_id" /></label>
      <label class="field">Root cause<input v-model="form.root_cause" /></label>
      <label class="field">Verification<textarea v-model="form.verification_result" rows="2"></textarea></label>
      <label class="checkbox-field"><input v-model="form.root_cause_confirmed" type="checkbox" :disabled="!form.root_cause.trim()" /> Root cause confirmed</label>
      <label class="checkbox-field"><input v-model="form.verification_done" type="checkbox" :disabled="!form.verification_result.trim()" /> Verification completed</label>
      <label class="field">Reply status
        <select v-model="form.reply_status">
          <option value="">Unspecified</option><option value="draft">Draft</option><option value="published">Published</option>
        </select>
      </label>
    </div>
    <div class="form-actions">
      <button type="submit" :disabled="busy || !form.summary.trim()">{{ manual ? 'Record event' : 'Confirm and record' }}</button>
      <button v-if="!manual" type="submit" class="ghost-btn" value="save" :disabled="busy || !form.summary.trim()">Save draft</button>
      <button type="button" class="ghost-btn" :disabled="busy" @click="emit('cancel')">Cancel</button>
    </div>
  </form>
</template>

<style scoped>
.draft-editor { margin-top: 14px; }
.form-actions { flex-wrap: wrap; }
</style>

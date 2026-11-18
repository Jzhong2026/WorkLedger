<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { api, errorMessage } from '@/api/client'
import type { WorkEvent } from '@/types'

const props = defineProps<{ kind: 'accomplishment' | 'case'; source: WorkEvent | null; defaultDate: string }>()
const emit = defineEmits<{ saved: [date: string]; cancel: [] }>()
const busy = ref(false)
const failure = ref('')
const form = reactive({
  title: props.source?.summary ?? '',
  occurred_at: props.source?.occurred_at.slice(0, 10) ?? props.defaultDate,
  evidence_url: props.source?.evidence_url ?? '',
  description: props.source?.detail ?? '',
  phenomenon: props.source?.detail || props.source?.summary || '',
  impact: '',
  is_highlight: false,
  root_cause: props.source?.root_cause ?? '',
  root_cause_confirmed: props.source?.root_cause_confirmed ?? false,
  solution: '',
  verification: props.source?.verification_result ?? '',
  verification_done: props.source?.verification_done ?? false,
})
watch(() => props.defaultDate, day => {
  if (!form.occurred_at) form.occurred_at = day
})

async function save() {
  if (busy.value || !form.title.trim() || !form.occurred_at) return
  busy.value = true
  failure.value = ''
  const common = {
    title: form.title.trim(),
    occurred_at: form.occurred_at + 'T00:00:00',
    event_id: props.source?.id ?? null,
  }
  try {
    if (props.kind === 'case') {
      await api.createCase({
        ...common,
        phenomenon: form.phenomenon.trim(),
        evidence_url: form.evidence_url.trim() || null,
        root_cause: form.root_cause.trim() || null,
        root_cause_confirmed: Boolean(form.root_cause.trim()) && form.root_cause_confirmed,
        solution: form.solution.trim() || null,
        verification: form.verification.trim() || null,
        verification_done: Boolean(form.verification.trim()) && form.verification_done,
      })
    } else {
      await api.createAccomplishment({
        ...common,
        description: form.description.trim() || null,
        impact: form.impact.trim() || null,
        impact_evidence_url: form.evidence_url.trim() || null,
        is_highlight: form.is_highlight,
      })
    }
    emit('saved', common.occurred_at.slice(0, 10))
  } catch (error) {
    failure.value = errorMessage(error)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <form class="form-card entry-form" @submit.prevent="save">
    <h2>{{ kind === 'case' ? 'New case' : 'New accomplishment' }}</h2>
    <p v-if="source" class="meta">Source event <RouterLink :to="`/event/${source.id}`">{{ source.summary }}</RouterLink></p>
    <div class="form-grid-2">
      <label class="field">Title<input v-model="form.title" required /></label>
      <label class="field">Date<input v-model="form.occurred_at" type="date" required /></label>
      <template v-if="kind === 'case'">
        <label class="field form-span">What happened?<textarea v-model="form.phenomenon" rows="3" required></textarea></label>
        <label class="field">Root cause<input v-model="form.root_cause" /></label>
        <label class="checkbox-field"><input v-model="form.root_cause_confirmed" type="checkbox" :disabled="!form.root_cause.trim()" /> Root cause confirmed</label>
        <label class="field form-span">Solution<textarea v-model="form.solution" rows="2"></textarea></label>
        <label class="field">Verification<textarea v-model="form.verification" rows="2"></textarea></label>
        <label class="checkbox-field"><input v-model="form.verification_done" type="checkbox" :disabled="!form.verification.trim()" /> Verification completed</label>
      </template>
      <template v-else>
        <label class="field form-span">Description<textarea v-model="form.description" rows="3"></textarea></label>
        <label class="field form-span">Impact<input v-model="form.impact" placeholder="What improved or changed?" /></label>
        <label class="checkbox-field form-span"><input v-model="form.is_highlight" type="checkbox" /> Mark as highlight</label>
      </template>
      <label class="field form-span">Evidence URL<input v-model="form.evidence_url" type="url" /></label>
    </div>
    <p v-if="failure" role="alert">{{ failure }}</p>
    <div class="form-actions">
      <button type="button" class="ghost-btn" :disabled="busy" @click="emit('cancel')">Cancel</button>
      <button type="submit" :disabled="busy || !form.title.trim()">{{ busy ? 'Saving…' : (kind === 'case' ? 'Save case' : 'Save accomplishment') }}</button>
    </div>
  </form>
</template>

<style scoped>
.entry-form { margin-bottom: 1rem; }
.entry-form h2 { margin-top: 0; }
</style>

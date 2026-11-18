<script setup lang="ts">
import { ref, reactive } from 'vue'
import { api } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import { useToast } from '@/stores/toast'
import Badge from '@/components/Badge.vue'
import EmptyState from '@/components/EmptyState.vue'

const toast = useToast()
const period = ref('year')
const { data, loading, run } = useAsync(() => api.retrospective(period.value))
const narrative = ref('')
const narrativeBusy = ref(false)

function setPeriod(p: string) { period.value = p; narrative.value = ''; run() }
async function download() {
  const md = await api.exportMarkdown(period.value)
  const blob = new Blob([md], { type: 'text/markdown' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `workledger-${period.value}.md`
  a.click()
  URL.revokeObjectURL(a.href)
  toast.success('Markdown exported')
}
async function synthesize() {
  narrativeBusy.value = true
  try { const res = await api.exportNarrative(period.value); narrative.value = res.narrative }
  catch { /* toast */ } finally { narrativeBusy.value = false }
}

const form = reactive({ title: '', occurred_at: '', impact: '', impact_evidence_url: '', is_highlight: false })
async function addAcc() {
  if (!form.title.trim() || !form.occurred_at) return
  await api.createAccomplishment({
    title: form.title, occurred_at: form.occurred_at + 'T00:00:00',
    impact: form.impact || null, impact_evidence_url: form.impact_evidence_url || null, is_highlight: form.is_highlight,
  })
  Object.assign(form, { title: '', occurred_at: '', impact: '', impact_evidence_url: '', is_highlight: false })
  toast.success('Accomplishment added'); run()
}
</script>

<template>
  <h1>Retrospective</h1>
  <div class="period-tabs">
    <a href="#" :class="{ active: period === 'month' }" @click.prevent="setPeriod('month')">Month</a>
    <a href="#" :class="{ active: period === 'quarter' }" @click.prevent="setPeriod('quarter')">Quarter</a>
    <a href="#" :class="{ active: period === 'year' }" @click.prevent="setPeriod('year')">Year</a>
  </div>
  <p v-if="data" class="meta">{{ data.date_from }} — {{ data.date_to }}</p>
  <div class="card-actions" style="margin-bottom:1rem">
    <button @click="download">Export Markdown</button>
    <button @click="synthesize" :disabled="narrativeBusy">{{ narrativeBusy ? 'Synthesizing…' : 'Synthesize narrative' }}</button>
  </div>
  <div v-if="narrative" class="card highlight" style="margin-bottom:1rem">
    <div class="card-header"><strong>Narrative</strong></div>
    <p style="white-space:pre-wrap">{{ narrative }}</p>
  </div>

  <div v-if="loading" class="loading">Loading…</div>
  <template v-else-if="data">
    <h2>Accomplishments ({{ data.accomplishments.length }})</h2>
    <div v-if="data.accomplishments.length" class="card-list">
      <div v-for="a in data.accomplishments" :key="a.id" class="card" :class="{ highlight: a.is_highlight }">
        <div class="card-header">
          <Badge v-if="a.is_highlight" variant="highlight" label="Highlight" />
          <strong>{{ a.title }}</strong>
        </div>
        <p v-if="a.description">{{ a.description }}</p>
        <div class="card-meta">
          <span>{{ a.occurred_at.slice(0, 10) }}</span>
          <span v-if="a.impact">Impact: {{ a.impact }}</span>
          <a v-if="a.impact_evidence_url" :href="a.impact_evidence_url" target="_blank" rel="noopener">Evidence</a>
        </div>
      </div>
    </div>
    <EmptyState v-else message="No accomplishments in this period." />

    <h2>Cases &amp; Lessons ({{ data.cases.length }})</h2>
    <div v-if="data.cases.length" class="card-list">
      <div v-for="c in data.cases" :key="c.id" class="card">
        <div class="card-header"><strong>{{ c.title }}</strong></div>
        <p>{{ c.phenomenon }}</p>
        <div class="card-meta">
          <span>{{ c.occurred_at.slice(0, 10) }}</span>
          <span v-if="c.root_cause">Cause: {{ c.root_cause }}</span>
          <Badge :variant="c.verification_done ? 'ok' : 'warn'" :label="c.verification_done ? 'verified' : 'unverified'" />
        </div>
      </div>
    </div>
    <EmptyState v-else message="No cases in this period." />
  </template>

  <h2>Manual entry</h2>
  <form class="form-card" @submit.prevent="addAcc">
    <div class="form-card-title">New accomplishment</div>
    <div class="form-grid-2">
      <label class="field form-span"><span class="field-label">Title</span><input v-model="form.title" type="text" placeholder="What did you achieve?" required /></label>
      <label class="field"><span class="field-label">Date</span><input v-model="form.occurred_at" type="date" required /></label>
      <label class="field"><span class="field-label">Impact</span><input v-model="form.impact" type="text" placeholder="Outcome / impact (optional)" /></label>
      <label class="field form-span"><span class="field-label">Evidence URL</span><input v-model="form.impact_evidence_url" type="url" placeholder="Link to proof (optional)" /></label>
      <label class="field checkbox-field form-span"><input v-model="form.is_highlight" type="checkbox" /> Mark as highlight</label>
    </div>
    <div class="form-actions"><button type="submit">Add accomplishment</button></div>
  </form>
</template>
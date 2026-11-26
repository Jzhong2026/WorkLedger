<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import { useToast } from '@/stores/toast'
import Badge from '@/components/Badge.vue'
import EmptyState from '@/components/EmptyState.vue'
import EventCard from '@/components/EventCard.vue'
import RetrospectiveEntryForm from '@/components/RetrospectiveEntryForm.vue'
import type { Narrative, WorkEvent } from '@/types'
import type { LessonOutcome } from '@/types/learning'

const route = useRoute()
const router = useRouter()
const toast = useToast()
const periods = ['month', 'quarter', 'year', 'all'] as const
type Period = typeof periods[number]
const period = ref<Period>('year')
const page = ref(1)
const pageSize = 20
const { data, loading, error, run } = useAsync(() => api.retrospective(period.value, page.value, pageSize))
const { data: agent } = useAsync(() => api.agentStatus())
const agentReady = computed(() => !!(agent.value?.enabled && agent.value.key_configured && agent.value.cli_available))
const narrative = ref<Narrative | null>(null)
const narrativeBusy = ref(false)
const exportBusy = ref(false)
let narrativeRequest = 0
const kind = computed(() => route.query.entry === 'case' || route.query.entry === 'accomplishment' ? route.query.entry : null)
const sourceId = computed(() => typeof route.query.event === 'string' ? Number(route.query.event) : null)
const source = ref<WorkEvent | null>(null)
const sourceLoading = ref(false)
const sourceError = ref('')
let sourceRequest = 0
const pageCount = computed(() => data.value?.pages ?? 0)
const lessonOutcomes: Record<LessonOutcome, string> = {
  applied: 'Applied',
  helped: 'Helped',
  did_not_help: 'Did not help',
}

async function loadSource() {
  const request = ++sourceRequest
  source.value = null
  sourceError.value = ''
  sourceLoading.value = false
  if (!kind.value || sourceId.value === null) return
  if (!Number.isSafeInteger(sourceId.value) || sourceId.value <= 0) {
    sourceError.value = 'Source event could not be identified.'
    return
  }
  sourceLoading.value = true
  try {
    const record = await api.getEvent(sourceId.value)
    if (request === sourceRequest) source.value = record
  } catch (error) {
    if (request === sourceRequest) sourceError.value = errorMessage(error)
  } finally {
    if (request === sourceRequest) sourceLoading.value = false
  }
}
watch([kind, sourceId], loadSource, { immediate: true })

function setPeriod(value: Period) {
  if (period.value === value) return
  period.value = value
  page.value = 1
  narrative.value = null
  narrativeBusy.value = false
  narrativeRequest++
  void run()
}

function goToPage(value: number) {
  page.value = value
  void run()
}

async function closeForm() {
  await router.replace({ name: 'retrospective' })
}

async function onSaved(occurredOn: string) {
  toast.success(kind.value === 'case' ? 'Case saved' : 'Accomplishment saved')
  await closeForm()
  if (data.value && occurredOn < data.value.date_from) {
    setPeriod('all')
    return
  }
  goToPage(1)
}

async function download() {
  if (exportBusy.value) return
  exportBusy.value = true
  const selection = period.value
  try {
    const markdown = await api.exportMarkdown(selection)
    const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `workledger-${selection}.md`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 0)
    toast.success('Markdown exported')
  } catch (error) {
    toast.error(errorMessage(error))
  } finally {
    exportBusy.value = false
  }
}

async function synthesize() {
  if (!agentReady.value || narrativeBusy.value) return
  narrativeBusy.value = true
  const request = ++narrativeRequest
  try {
    const result = await api.exportNarrative(period.value)
    if (request === narrativeRequest) narrative.value = result
  } catch (error) {
    if (request === narrativeRequest) toast.error(errorMessage(error))
  } finally {
    if (request === narrativeRequest) narrativeBusy.value = false
  }
}
</script>

<template>
  <h1>Retrospective</h1>
  <div class="card-actions"><RouterLink to="/weekly">Prepare weekly report</RouterLink><RouterLink to="/learning">Find lessons</RouterLink></div>

  <div v-if="sourceLoading" class="loading">Loading source event…</div>
  <div v-else-if="sourceError" class="card" role="alert">
    <p>{{ sourceError }}</p>
    <div class="card-actions">
      <button class="ghost-btn" @click="loadSource">Retry source</button>
      <RouterLink :to="{ name: 'retrospective', query: { entry: kind } }">Continue without source</RouterLink>
      <button class="ghost-btn" @click="closeForm">Cancel</button>
    </div>
  </div>
  <RetrospectiveEntryForm v-else-if="kind" :key="`${kind}-${sourceId}`" :kind="kind" :source="source"
    :default-date="data?.date_to || ''" @saved="onSaved" @cancel="closeForm" />
  <div v-else class="card-actions entry-actions">
    <RouterLink :to="{ name: 'retrospective', query: { entry: 'accomplishment' } }">Add accomplishment</RouterLink>
    <RouterLink :to="{ name: 'retrospective', query: { entry: 'case' } }">Add case</RouterLink>
  </div>

  <div class="card-actions" aria-label="Review period">
    <button v-for="value in periods" :key="value" type="button" :class="{ 'ghost-btn': period !== value }"
      :aria-pressed="period === value" @click="setPeriod(value)">{{ value === 'all' ? 'All time' : value }}</button>
  </div>
  <p v-if="data && !loading && !error" class="meta">{{ data.date_from }} — {{ data.date_to }}</p>
  <div class="card-actions">
    <button :disabled="exportBusy" @click="download">{{ exportBusy ? 'Exporting…' : 'Export Markdown' }}</button>
    <button v-if="agentReady" class="ghost-btn" :disabled="narrativeBusy" @click="synthesize">{{ narrativeBusy ? 'Synthesizing…' : 'Synthesize narrative' }}</button>
  </div>
  <p class="meta" v-if="agentReady">Narrative generation sends a selection of records from this period to CodeBuddy. Markdown export stays local.</p>
  <p class="meta" v-else>Markdown export stays local. AI narrative generation requires an enabled CodeBuddy configuration.</p>
  <div v-if="narrative" class="card highlight narrative">
    <strong>Narrative</strong>
    <p class="meta">
      Records sent · {{ narrative.coverage.included.accomplishments }}/{{ narrative.coverage.totals.accomplishments }} accomplishments ·
      {{ narrative.coverage.included.cases }}/{{ narrative.coverage.totals.cases }} cases ·
      <template v-if="narrative.coverage.totals.lessons">
        {{ narrative.coverage.included.lessons }}/{{ narrative.coverage.totals.lessons }} confirmed lessons ·
      </template>
      <template v-if="narrative.coverage.totals.lesson_uses">
        {{ narrative.coverage.included.lesson_uses }}/{{ narrative.coverage.totals.lesson_uses }} lesson application records ·
      </template>
      {{ narrative.coverage.included.events }}/{{ narrative.coverage.totals.events }} work events
    </p>
    <p class="narrative-text">{{ narrative.narrative }}</p>
  </div>

  <div v-if="loading" class="loading">Loading retrospective…</div>
  <div v-else-if="error" role="alert">{{ error }} <button class="ghost-btn" @click="run">Retry retrospective</button></div>
  <template v-else-if="data">
    <h2>Accomplishments ({{ data.totals.accomplishments }})</h2>
    <div v-if="data.accomplishments.length" class="card-list">
      <article v-for="a in data.accomplishments" :key="a.id" class="card" :class="{ highlight: a.is_highlight }">
        <div class="card-header">
          <Badge v-if="a.is_highlight" variant="highlight" label="Highlight" />
          <strong>{{ a.title }}</strong>
        </div>
        <p v-if="a.description">{{ a.description }}</p>
        <div class="card-meta">
          <span>{{ a.occurred_at.slice(0, 10) }}</span>
          <span v-if="a.impact">Impact: {{ a.impact }}</span>
          <RouterLink v-if="a.event_id" :to="`/event/${a.event_id}`">Source event</RouterLink>
          <a v-if="a.impact_evidence_url" :href="a.impact_evidence_url" target="_blank" rel="noopener">Evidence</a>
        </div>
      </article>
    </div>
    <EmptyState v-else :message="data.totals.accomplishments ? 'No accomplishments on this page.' : 'No accomplishments in this period.'" />

    <h2>Cases &amp; Lessons ({{ data.totals.cases }})</h2>
    <div v-if="data.cases.length" class="card-list">
      <article v-for="c in data.cases" :key="c.id" class="card">
        <div class="card-header"><strong>{{ c.title }}</strong></div>
        <p>{{ c.phenomenon }}</p>
        <p v-if="c.root_cause">Root cause: {{ c.root_cause }} <Badge :variant="c.root_cause_confirmed ? 'ok' : 'warn'" :label="c.root_cause_confirmed ? 'Confirmed' : 'Unconfirmed'" /></p>
        <p v-if="c.solution">Solution: {{ c.solution }}</p>
        <p v-if="c.verification">Verification: {{ c.verification }} <Badge :variant="c.verification_done ? 'ok' : 'warn'" :label="c.verification_done ? 'Completed' : 'Pending'" /></p>
        <div class="card-meta">
          <span>{{ c.occurred_at.slice(0, 10) }}</span>
          <RouterLink v-if="c.event_id" :to="`/event/${c.event_id}`">Source event</RouterLink>
          <a v-if="c.evidence_url" :href="c.evidence_url" target="_blank" rel="noopener">Evidence</a>
        </div>
      </article>
    </div>
    <EmptyState v-else :message="data.totals.cases ? 'No cases on this page.' : 'No cases in this period.'" />

    <template v-if="data.totals.lessons">
      <h2>Confirmed skills &amp; process lessons ({{ data.totals.lessons }})</h2>
      <div v-if="data.lessons.length" class="card-list">
        <article v-for="lesson in data.lessons" :key="lesson.id" class="card">
          <div class="card-header">
            <Badge variant="type" :label="lesson.kind === 'skill' ? 'Skill' : 'Process improvement'" />
            <RouterLink :to="{ name: 'learning', query: { lesson_id: lesson.id } }">{{ lesson.title }}</RouterLink>
          </div>
          <p><strong>Trigger:</strong> {{ lesson.trigger }}</p>
          <p><strong>First step:</strong> {{ lesson.first_step }}</p>
          <p v-if="lesson.limits"><strong>Limits:</strong> {{ lesson.limits }}</p>
          <div class="card-meta">
            <span>Confirmed {{ lesson.reviewed_on }}</span>
            <RouterLink :to="{ name: 'work-item', params: { id: lesson.source_work_item_id } }">{{ lesson.source_work_item_title }}</RouterLink>
            <RouterLink v-if="lesson.source_event_id" :to="{ name: 'event', params: { id: lesson.source_event_id } }">Source event</RouterLink>
            <a v-if="lesson.evidence_url" :href="lesson.evidence_url" target="_blank" rel="noopener noreferrer">Evidence</a>
            <a v-if="lesson.source_event_url && lesson.source_event_url !== lesson.evidence_url"
              :href="lesson.source_event_url" target="_blank" rel="noopener noreferrer">Source evidence</a>
          </div>
        </article>
      </div>
      <EmptyState v-else message="No confirmed lessons on this page." />
    </template>

    <template v-if="data.totals.lesson_uses">
      <h2>Lesson applications &amp; outcomes ({{ data.totals.lesson_uses }})</h2>
      <div v-if="data.lesson_uses.length" class="card-list">
        <article v-for="entry in data.lesson_uses" :key="entry.id" class="card">
          <div class="card-header">
            <Badge :variant="entry.outcome === 'helped' ? 'ok' : entry.outcome === 'did_not_help' ? 'warn' : 'type'"
              :label="lessonOutcomes[entry.outcome]" />
            <RouterLink :to="{ name: 'learning', query: { lesson_id: entry.lesson_id, work_item_id: entry.work_item_id } }">{{ entry.title }}</RouterLink>
          </div>
          <p v-if="entry.detail">{{ entry.detail }}</p>
          <div class="card-meta">
            <span>{{ entry.recorded_on }}</span>
            <span>Applied in <RouterLink :to="{ name: 'work-item', params: { id: entry.work_item_id } }">{{ entry.work_item_title }}</RouterLink></span>
            <RouterLink v-if="entry.source_event_id" :to="{ name: 'event', params: { id: entry.source_event_id } }">Lesson source event</RouterLink>
            <a v-if="entry.evidence_url" :href="entry.evidence_url" target="_blank" rel="noopener noreferrer">Lesson evidence</a>
            <a v-if="entry.source_event_url && entry.source_event_url !== entry.evidence_url"
              :href="entry.source_event_url" target="_blank" rel="noopener noreferrer">Source evidence</a>
          </div>
        </article>
      </div>
      <EmptyState v-else message="No lesson application records on this page." />
    </template>

    <h2>Work events ({{ data.totals.events }})</h2>
    <div v-if="data.events.length" class="card-list">
      <EventCard v-for="event in data.events" :key="event.id" :event="event" />
    </div>
    <EmptyState v-else :message="data.totals.events ? 'No work events on this page.' : 'No work events in this period.'" />

    <div v-if="pageCount > 1" class="card-actions pages">
      <button class="ghost-btn" :disabled="page <= 1" @click="goToPage(page - 1)">Previous page</button>
      <span>Page {{ page }} of {{ pageCount }}</span>
      <button class="ghost-btn" :disabled="page >= pageCount" @click="goToPage(page + 1)">Next page</button>
    </div>
  </template>
</template>

<style scoped>
.entry-actions, .narrative { margin-bottom: 1rem; }
.narrative-text { white-space: pre-wrap; }
[aria-label="Review period"] button { text-transform: capitalize; }
.pages { margin-top: 1rem; }
</style>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, errorMessage, get, post, qs } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import { useToast } from '@/stores/toast'
import type { Accomplishment, Case } from '@/types'

interface Evidence {
  id: number; summary: string; occurred_at: string; event_type: string; evidence_url: string | null
  actor: string | null; source_agent: string | null; verification_result: string | null; verification_done: boolean
  source?: string
}
interface Group { title: string; item_id: number | null; events: Evidence[] }
interface Weekly {
  start: string; end: string; groups: Group[]; accomplishments: Accomplishment[]; cases: Case[]
  lessons: {id: number; kind: string; title: string; trigger: string; first_step: string; limits: string | null; source_work_item_id: number; item_title: string}[]
  reuse: {id: number; lesson_id: number; title: string; work_item_id: number; item_title: string; outcome: string; detail: string | null}[]
}
interface Suggestion {text: string; source_ids: number[]}
interface Candidates {suggestions: Suggestion[]; coverage: {included: number; total: number}}

const toast = useToast()
function localDate(date: Date) {
  return [date.getFullYear(), String(date.getMonth()+1).padStart(2,'0'), String(date.getDate()).padStart(2,'0')].join('-')
}
const day = ref(localDate(new Date()))
const project = ref<number | ''>('')
const route = useRoute()
const mine = ref(route.query.scope === 'mine')
watch(() => route.query.scope, value => { mine.value = value === 'mine' })
const { data: projects } = useAsync(() => api.listProjects(true))
const { data: status } = useAsync(() => api.agentStatus())
const ready = computed(() => status.value?.enabled && status.value.key_configured && status.value.cli_available)
const scope = computed(() => ({day: day.value || undefined, project_id: project.value || undefined, scope: mine.value ? 'mine' : 'all'}))
const { data, error, loading, run } = useAsync(() => get<Weekly>('/work-review/weekly' + qs(scope.value)))
const candidates = ref<Candidates | null>(null)
const drafting = ref(false)
let generation = 0
const editor = ref<{title: string; impact: string; primary: number; source_ids: number[]} | null>(null)
const saving = ref(false)
const contributionInput = ref<HTMLTextAreaElement | null>(null)
const eventMap = computed(() => new Map(data.value?.groups.flatMap(g => g.events.map(e => [e.id, e] as const))))
watch(scope, () => {
  generation++
  candidates.value = null
  drafting.value = false
  editor.value = null
  void run()
})

function moveWeek(days: number) {
  const date = new Date((day.value || localDate(new Date())) + 'T12:00:00')
  date.setDate(date.getDate() + days)
  day.value = localDate(date)
}
async function draft() {
  const request = ++generation
  drafting.value = true
  try {
    const result = await post<Candidates>('/work-review/weekly/candidates', scope.value)
    if (request === generation) candidates.value = result
  } catch (err) {
    if (request === generation) toast.error(errorMessage(err))
  } finally {
    if (request === generation) drafting.value = false
  }
}
async function review(title: string, source_ids: number[]) {
  const primary = source_ids.find(id => eventMap.value.get(id)?.verification_done) ?? source_ids[0]
  editor.value = {title, source_ids, primary, impact: ''}
  await nextTick()
  contributionInput.value?.focus()
}
async function saveHighlight() {
  const form = editor.value
  const source = form && eventMap.value.get(form.primary)
  if (!form || !source || !data.value || saving.value || !form.title.trim()) return
  const request = generation
  saving.value = true
  try {
    await api.createAccomplishment({
      title: form.title.trim(), event_id: source.id, occurred_at: source.occurred_at,
      impact: form.impact.trim() || null, impact_evidence_url: source.evidence_url,
      description: 'Source events: ' + form.source_ids.map(id => '#' + id).join(', '),
      is_highlight: true, source_key: 'weekly:' + data.value.start + ':' + [...form.source_ids].sort((a,b) => a-b).join(',') + ':' + form.title.trim(),
    })
    if (request === generation) { editor.value = null; await run() }
    toast.success('Highlight saved to your retrospective')
  } catch (err) { toast.error(errorMessage(err)) }
  finally { saving.value = false }
}

function download() {
  const report = data.value
  if (!report) return
  const lines = ['# Weekly review', '', report.start + ' – ' + report.end, '', '## Highlights']
  for (const a of report.accomplishments) {
    lines.push('- ' + a.title + (a.impact ? ' — ' + a.impact : ''))
    if (a.description) lines.push('  ' + a.description)
    if (a.impact_evidence_url) lines.push('  ' + a.impact_evidence_url)
  }
  lines.push('', '## Cases and lessons')
  for (const c of report.cases) {
    lines.push('- ' + c.title + ' — ' + c.phenomenon)
    if (c.root_cause) lines.push('  Root cause (' + (c.root_cause_confirmed ? 'confirmed' : 'unconfirmed') + '): ' + c.root_cause)
    if (c.solution) lines.push('  Solution: ' + c.solution)
    if (c.evidence_url) lines.push('  ' + c.evidence_url)
  }
  for (const lesson of report.lessons) {
    lines.push('- ' + lesson.title + ' (' + lesson.kind + ')', '  When: ' + lesson.trigger, '  First step: ' + lesson.first_step)
    if (lesson.limits) lines.push('  Limits: ' + lesson.limits)
    lines.push('  Source: Work item #' + lesson.source_work_item_id + ' ' + lesson.item_title)
  }
  for (const u of report.reuse) lines.push('- ' + u.title + ' → ' + u.item_title + ' (' + u.outcome + ')' + (u.detail ? ' — ' + u.detail : ''))
  lines.push('', '## Recorded activity')
  for (const g of report.groups) {
    lines.push('', '### ' + g.title)
    for (const e of g.events) {
      lines.push('- ' + e.occurred_at.slice(0,10) + ' · #' + e.id + ' ' + e.summary + (e.source ? ' [' + e.source + ']' : ''))
      if (e.verification_result) lines.push('  Verification (' + (e.verification_done ? 'confirmed' : 'pending') + '): ' + e.verification_result)
      if (e.evidence_url) lines.push('  ' + e.evidence_url)
    }
  }
  const href = URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/markdown;charset=utf-8'}))
  const a = document.createElement('a')
  a.href = href
  a.download = 'workledger-week-' + report.start + '.md'
  a.click()
  setTimeout(() => URL.revokeObjectURL(href), 0)
}
</script>

<template>
  <h1>Weekly review</h1>
  <div class="form-card">
    <div class="form-grid-3">
      <label class="field">Week containing<input v-model="day" type="date" /></label>
      <label class="field">Project<select v-model="project"><option value="">All projects</option>
        <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select></label>
      <label class="field">Scope<select v-model="mine"><option :value="false">All activity</option><option :value="true">Mine only</option></select></label>
    </div>
    <div class="card-actions">
      <button class="ghost-btn" @click="moveWeek(-7)">Previous week</button>
      <button class="ghost-btn" @click="moveWeek(7)">Next week</button>
    </div>
  </div>
  <p v-if="loading" role="status">Loading weekly review…</p>
  <p v-else-if="error" role="alert">{{ error }} <button @click="run">Retry</button></p>
  <template v-else-if="data">
    <h2>{{ data.start }} – {{ data.end }}</h2>
    <div class="card-actions">
      <button @click="download">Export weekly Markdown</button>
      <button v-if="ready" class="ghost-btn" :disabled="drafting || !data.groups.length" @click="draft">{{ drafting ? 'Drafting…' : 'Suggest highlights with AI' }}</button>
    </div>
    <p class="meta">{{ ready ? 'AI suggestions send selected activity from this week to CodeBuddy.' : 'You can review and save highlights locally. Enable CodeBuddy in configuration to generate suggestions.' }}</p>
    <section v-if="candidates">
      <h2>Suggested highlights</h2>
      <p class="meta">Based on {{ candidates.coverage.included }} of {{ candidates.coverage.total }} event records.</p>
      <p v-if="!candidates.suggestions.length">The selected records did not yield a supported highlight.</p>
      <article v-for="(s, index) in candidates.suggestions" :key="index" class="card">
        <p>{{ s.text }}</p><div class="card-actions">
          <RouterLink v-for="id in s.source_ids" :key="id" :to="'/event/'+id">Event #{{ id }}</RouterLink>
          <button @click="review(s.text,s.source_ids)">Review highlight</button>
        </div>
      </article>
    </section>
    <form v-if="editor" class="form-card" @submit.prevent="saveHighlight">
      <h2>Review highlight</h2>
      <label class="field">Contribution<textarea ref="contributionInput" v-model="editor.title" required /></label>
      <label class="field">Observed impact<input v-model="editor.impact" /></label>
      <label class="field">Primary evidence<select v-model="editor.primary">
        <option v-for="id in editor.source_ids" :key="id" :value="id">#{{ id }} · {{ eventMap.get(id)?.summary }}</option>
      </select></label>
      <div class="card-actions">
        <RouterLink v-for="id in editor.source_ids" :key="id" :to="'/event/'+id">Event #{{id}}</RouterLink>
        <button :disabled="saving || !editor.title.trim()">Save highlight</button>
        <button type="button" class="ghost-btn" @click="editor=null">Cancel</button>
      </div>
    </form>
    <h2>Highlights and accomplishments</h2>
    <p v-if="!data.accomplishments.length" class="meta">No accomplishments recorded for this week.</p>
    <article v-for="a in data.accomplishments" :key="a.id" class="card">
      <strong>{{a.title}}</strong><p v-if="a.impact">{{a.impact}}</p>
      <RouterLink v-if="a.event_id" :to="'/event/'+a.event_id">Source event</RouterLink>
    </article>
    <h2>Cases and lessons</h2>
    <p v-if="!data.cases.length && !data.lessons.length && !data.reuse.length" class="meta">No cases, confirmed lessons or applications recorded this week.</p>
    <article v-for="c in data.cases" :key="c.id" class="card"><strong>{{c.title}}</strong>
      <p>{{ c.phenomenon }}</p><p v-if="c.solution">{{c.solution}}</p>
      <RouterLink v-if="c.event_id" :to="'/event/'+c.event_id">Source event</RouterLink>
    </article>
    <article v-for="l in data.lessons" :key="l.id" class="card">
      <strong>{{ l.title }}</strong> · {{ l.kind }}
      <p>When · {{ l.trigger }}</p><p>First step · {{ l.first_step }}</p><p v-if="l.limits">Limits · {{ l.limits }}</p>
      <RouterLink :to="'/work-items/'+l.source_work_item_id">{{ l.item_title }}</RouterLink>
    </article>
    <article v-for="u in data.reuse" :key="u.id" class="card">
      <strong>{{u.title}}</strong> · {{u.outcome.replaceAll('_',' ')}}
      <p v-if="u.detail">{{u.detail}}</p><RouterLink :to="'/work-items/'+u.work_item_id">{{u.item_title}}</RouterLink>
    </article>
    <h2>Recorded activity</h2>
    <p v-if="!data.groups.length" class="meta">No events recorded for this selection.</p>
    <article v-for="g in data.groups" :key="g.events[0].id" class="card">
      <h3><RouterLink v-if="g.item_id" :to="'/work-items/'+g.item_id">{{g.title}}</RouterLink><template v-else>{{g.title}}</template></h3>
      <ul><li v-for="e in g.events" :key="e.id">
        <RouterLink :to="'/event/'+e.id">{{e.summary || 'Event #'+e.id}}</RouterLink>
        <span v-if="e.source" class="source-badge" :class="`src-${e.source}`">{{ e.source }}</span>
        <span class="meta"> · {{e.occurred_at.slice(0,10)}} · {{e.actor || e.source_agent || e.event_type}}</span>
        <p v-if="e.verification_result">{{e.verification_done ? 'Verified' : 'Pending verification'}} · {{e.verification_result}}</p>
      </li></ul>
      <button class="ghost-btn" @click="review(g.events[0].summary,g.events.map(e=>e.id))">Prepare highlight</button>
    </article>
  </template>
</template>

<style scoped>
.card, .form-card { margin-block: .75rem; overflow-wrap:anywhere; }
.card h3 { margin-top:0; }
li { margin-block:.5rem; }
.source-badge { font-size: .68rem; padding: 1px 6px; border-radius: 999px; margin-right: 4px; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-3); }
.src-jira { color: #2563eb; }
.src-bitbucket { color: #059669; }
</style>

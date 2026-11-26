<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '@/api/client'
import { workItemsApi } from '@/api/workItems'
import { useAsync } from '@/composables/useAsync'
import { useWindowFocusRefresh } from '@/composables/useWindowFocusRefresh'
import WorkItemCard from '@/components/WorkItemCard.vue'
import WorkStateFields from '@/components/WorkStateFields.vue'
import { workStages, type WorkBriefing, type WorkItemCreate } from '@/types/workItems'
import { currentWorkState, normalizedWorkState, submissionSourceKey } from '@/utils/workItems'
import type { WorkEvent } from '@/types'

const route = useRoute()
const router = useRouter()
const project = computed(() => {
  if (typeof route.query.project_id !== 'string') return undefined
  const id = Number(route.query.project_id)
  return Number.isSafeInteger(id) && id > 0 ? id : undefined
})
const { data: projects, error: catalogError, run: reloadProjects } = useAsync(() => api.listProjects(true))

const boards = workStages.map(stage => {
  const page = ref(1)
  const read = useAsync(() => workItemsApi.list({
    project_id: project.value,
    stage: stage.value,
    page: page.value,
    page_size: 8,
  }), false)
  watch(project, () => { page.value = 1 })
  watch([project, page], read.run, { immediate: true })
  return { ...stage, page, ...read }
})

async function reloadBoards() {
  await Promise.all(boards.map(board => board.run()))
}
useWindowFocusRefresh(reloadBoards)

function selectProject(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  return router.push({ path: '/work-items', query: value ? { project_id: value } : {} })
}

const title = ref('')
const goal = ref('')
const jira = ref('')
const createProject = ref<number | null>(project.value ?? null)
const selectedSource = ref<WorkEvent>()
const initialState = ref(currentWorkState())
const saving = ref(false)
const createError = ref('')
const sourceLinkError = ref('')
const createKey = submissionSourceKey('work-item')
const discoverFromLink = computed(() => route.query.discover === '1' || !!route.query.source_event_id)
watch(project, projectId => {
  if (!title.value.trim() && !selectedSource.value) createProject.value = projectId ?? null
})

const sourcePage = ref(1)
const sourceFilters = ref<{ project_id?: number; jira_key?: string }>({})
const {
  data: sources, loading: sourcesLoading, error: sourcesError, run: reloadSources,
} = useAsync(() => workItemsApi.discover({
  ...sourceFilters.value,
  page: sourcePage.value,
  page_size: 10,
}), false)

function searchSources() {
  sourcePage.value = 1
  sourceFilters.value = {
    project_id: createProject.value ?? undefined,
    jira_key: jira.value.trim().toUpperCase() || undefined,
  }
  return reloadSources()
}

function sourceResultsPage(page: number) {
  sourcePage.value = page
  return reloadSources()
}

function chooseSource(event: WorkEvent) {
  selectedSource.value = event
  if (!title.value.trim()) title.value = event.summary
  if (!jira.value.trim() && event.jira_key) jira.value = event.jira_key
  if (event.project_id !== null) createProject.value = event.project_id
}

let mounted = true
onScopeDispose(() => { mounted = false })
watch(() => route.query.source_event_id, async rawId => {
  sourceLinkError.value = ''
  if (typeof rawId !== 'string') {
    if (route.query.discover === '1') void searchSources()
    return
  }
  const id = Number(rawId)
  if (!Number.isSafeInteger(id) || id < 1) return
  try {
    const event = await api.getEvent(id)
    if (mounted && route.query.source_event_id === rawId && !selectedSource.value) chooseSource(event)
  } catch (error) {
    if (mounted && route.query.source_event_id === rawId) sourceLinkError.value = errorMessage(error)
  }
}, { immediate: true })

async function addWork() {
  if (saving.value || !title.value.trim()) return
  saving.value = true
  createError.value = ''
  const payload: WorkItemCreate = {
    title: title.value.trim(),
    goal: goal.value.trim() || null,
    jira_key: jira.value.trim() || null,
    project_id: createProject.value,
    source_event_id: selectedSource.value?.id ?? null,
    ...normalizedWorkState(initialState.value),
  }
  try {
    const item = await workItemsApi.create({ ...payload, source_key: createKey(payload) })
    if (mounted) await router.push(`/work-items/${item.id}`)
  } catch (error) {
    createError.value = errorMessage(error)
  } finally {
    saving.value = false
  }
}

const question = ref('')
const agent = ref<Awaited<ReturnType<typeof api.agentStatus>>>()
const agentError = ref('')
const agentLoading = ref(false)
const agentUnavailable = computed(() => {
  if (agentLoading.value) return 'Checking CodeBuddy availability…'
  if (agentError.value) return agentError.value
  if (!agent.value?.enabled) return 'CodeBuddy is disabled.'
  if (!agent.value.cli_available) return 'The CodeBuddy CLI is unavailable.'
  if (!agent.value.key_configured) return 'The CodeBuddy API key is missing.'
  return ''
})

async function loadAgentStatus() {
  agentLoading.value = true
  agentError.value = ''
  try {
    agent.value = await api.agentStatus()
  } catch {
    agentError.value = 'Could not check CodeBuddy availability.'
  } finally {
    agentLoading.value = false
  }
}
void loadAgentStatus()

const summary = ref<WorkBriefing>()
const briefingBusy = ref(false)
const briefingError = ref('')
let briefingRequest = 0
watch(project, () => {
  briefingRequest++
  summary.value = undefined
  briefingError.value = ''
  briefingBusy.value = false
})
onScopeDispose(() => { briefingRequest++ })

async function summarize() {
  if (briefingBusy.value || agentUnavailable.value) return
  const current = ++briefingRequest
  briefingBusy.value = true
  briefingError.value = ''
  summary.value = undefined
  try {
    const result = await workItemsApi.briefing({
      project_id: project.value,
      question: question.value.trim() || undefined,
    })
    if (current === briefingRequest) summary.value = result
  } catch (error) {
    if (current === briefingRequest) briefingError.value = errorMessage(error)
  } finally {
    if (current === briefingRequest) briefingBusy.value = false
  }
}
</script>

<template>
  <div class="progress-heading">
    <h1>Project progress</h1>
    <div class="progress-actions">
      <RouterLink to="/weekly">Weekly reports</RouterLink>
      <RouterLink to="/learning">Learning</RouterLink>
      <button type="button" class="ghost-btn" @click="reloadBoards">Refresh</button>
    </div>
  </div>
  <label class="field project-select">
    <span class="field-label">Project</span>
    <select :value="project ?? ''" @change="selectProject">
      <option value="">All projects</option>
      <option v-if="project && !projects?.some(entry => entry.id === project)" :value="project">Project #{{ project }}</option>
      <option v-for="entry in projects ?? []" :key="entry.id" :value="entry.id">
        {{ entry.name }}{{ entry.is_archived ? ' (archived)' : '' }}
      </option>
    </select>
  </label>
  <div v-if="catalogError" class="error-banner">
    <span role="alert">Could not load project names. The work items can still be opened.</span>
    <button type="button" @click="reloadProjects">Retry projects</button>
  </div>

  <details class="form-card progress-panel" :open="discoverFromLink">
    <summary>New work item</summary>
    <form @submit.prevent="addWork">
      <fieldset :disabled="saving" class="plain-fieldset">
        <div class="form-grid-2">
          <label class="field form-span"><span class="field-label">Title</span><input v-model="title" type="text" required /></label>
          <label class="field form-span"><span class="field-label">Goal</span><textarea v-model="goal" rows="2"></textarea></label>
          <label class="field">
            <span class="field-label">Project</span>
            <select v-model="createProject">
              <option :value="null">No project</option>
              <option
                v-if="createProject && !projects?.some(entry => entry.id === createProject)"
                :value="createProject"
              >Project #{{ createProject }}</option>
              <option v-for="entry in projects ?? []" :key="entry.id" :value="entry.id">{{ entry.name }}</option>
            </select>
          </label>
          <label class="field"><span class="field-label">Jira key</span><input v-model="jira" type="text" /></label>
        </div>

        <details class="nested-panel">
          <summary>Initial progress</summary>
          <WorkStateFields v-model="initialState" />
        </details>

        <details class="nested-panel" :open="discoverFromLink">
          <summary>Link a Jira issue or an existing event</summary>
          <p class="meta">Uses the project and Jira key entered above to find local records.</p>
          <p v-if="selectedSource" class="source-selection">
            <RouterLink :to="`/event/${selectedSource.id}`">
              {{ selectedSource.jira_key || `Event #${selectedSource.id}` }} · {{ selectedSource.summary }}
            </RouterLink>
            <button type="button" class="ghost-btn" @click="selectedSource = undefined">Remove source</button>
          </p>
          <button type="button" class="ghost-btn" :disabled="sourcesLoading" @click="searchSources">
            {{ sourcesLoading ? 'Looking up…' : 'Find source records' }}
          </button>
          <p v-if="sourcesError" class="error-banner" role="alert">Source lookup failed. {{ sourcesError }}</p>
          <p v-else-if="sourceLinkError" class="error-banner" role="alert">The linked source could not be opened. {{ sourceLinkError }}</p>
          <ul v-else-if="sources?.items.length" class="source-results">
            <li v-for="source in sources.items" :key="source.id">
              <button
                type="button"
                class="ghost-btn"
                :aria-pressed="selectedSource?.id === source.id"
                @click="chooseSource(source)"
              >{{ source.jira_key || `Event #${source.id}` }} · {{ source.summary }}</button>
            </li>
          </ul>
          <p v-else-if="sources" class="meta">No local source records match.</p>
          <nav v-if="sources && sources.pages > 1 && !sourcesError" class="pagination" aria-label="Source records pages">
            <button v-if="sourcePage > 1" type="button" class="ghost-btn" :disabled="sourcesLoading" @click="sourceResultsPage(sourcePage - 1)">Previous</button>
            <span>Page {{ sourcePage }} of {{ sources.pages }}</span>
            <button v-if="sourcePage < sources.pages" type="button" class="ghost-btn" :disabled="sourcesLoading" @click="sourceResultsPage(sourcePage + 1)">Next</button>
          </nav>
        </details>
        <p v-if="createError" class="error-banner" role="alert">{{ createError }} Your entry is still here.</p>
        <div class="form-actions">
          <button type="submit">{{ saving ? 'Creating…' : 'Create work item' }}</button>
        </div>
      </fieldset>
    </form>
  </details>

  <div class="stage-board">
    <section v-for="board in boards" :key="board.value" :aria-labelledby="`stage-${board.value}`">
      <h2 :id="`stage-${board.value}`">
        {{ board.label }}
        <small v-if="board.data.value && !board.loading.value && !board.error.value">{{ board.data.value.total }}</small>
      </h2>
      <div v-if="board.loading.value" class="loading" role="status">Loading {{ board.label.toLowerCase() }} items…</div>
      <div v-else-if="board.error.value" class="error-banner">
        <span role="alert">{{ board.error.value }}</span>
        <button type="button" @click="board.run">Retry</button>
      </div>
      <template v-else-if="board.data.value?.items.length">
        <div class="card-list">
          <WorkItemCard v-for="item in board.data.value.items" :key="item.id" :item="item" />
        </div>
        <nav v-if="board.data.value.pages > 1" class="pagination" :aria-label="`${board.label} work item pages`">
          <button v-if="board.page.value > 1" type="button" class="ghost-btn" @click="board.page.value--">Previous</button>
          <span>Page {{ board.page.value }} of {{ board.data.value.pages }}</span>
          <button
            v-if="board.page.value < board.data.value.pages"
            type="button"
            class="ghost-btn"
            @click="board.page.value++"
          >Next</button>
        </nav>
      </template>
      <p v-else class="empty stage-empty">No {{ board.label.toLowerCase() }} items.</p>
    </section>
  </div>

  <details class="form-card progress-panel briefing-panel">
    <summary>
      Ask the assistant about progress
      <small v-if="agentUnavailable && !agentLoading">· Unavailable</small>
    </summary>
    <div v-if="agentUnavailable" class="briefing-availability">
      <p role="status">{{ agentUnavailable }}</p>
      <button v-if="agentError" type="button" class="ghost-btn" @click="loadAgentStatus">Check again</button>
      <RouterLink v-else-if="!agentLoading" to="/settings">Open settings</RouterLink>
    </div>
    <form @submit.prevent="summarize">
      <p class="meta" id="briefing-disclosure">
        WorkLedger sends the question and a selection of work item progress to CodeBuddy. The response links to its local sources.
      </p>
      <label class="field">
        <span class="field-label">Question (optional)</span>
        <input
          v-model="question"
          type="text"
          maxlength="800"
          aria-describedby="briefing-disclosure"
          placeholder="What needs my attention?"
          :disabled="!!agentUnavailable || briefingBusy"
        />
      </label>
      <div class="form-actions">
        <button type="submit" :disabled="!!agentUnavailable || briefingBusy">
          {{ briefingBusy ? 'Preparing briefing…' : 'Get briefing' }}
        </button>
      </div>
    </form>
    <p v-if="briefingError" class="error-banner" role="alert">{{ briefingError }} Progress above remains available.</p>
    <div v-if="summary" class="briefing-result">
      <p class="briefing-text">{{ summary.text }}</p>
      <p>Work items included: {{ summary.coverage.included }} of {{ summary.coverage.total }}.</p>
      <ul v-if="summary.sources.length">
        <li v-for="source in summary.sources" :key="source.item_id">
          <RouterLink :to="`/work-items/${source.item_id}`">{{ source.title }}</RouterLink>
        </li>
      </ul>
    </div>
  </details>
</template>

<style scoped>
.progress-heading, .source-selection { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px; }
.progress-actions, .briefing-availability { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.project-select { max-width: 24rem; margin-bottom: 16px; }
.progress-panel summary, .nested-panel summary { cursor: pointer; font-weight: 600; }
.progress-panel form { margin-top: 14px; }
.plain-fieldset { border: 0; min-width: 0; }
.nested-panel { margin-top: 14px; border-top: 1px solid var(--border); padding-top: 8px; }
.nested-panel .form-grid-2, .nested-panel .meta { margin-top: 10px; }
.source-results { display: grid; gap: 6px; list-style: none; margin-top: 8px; }
.source-results button { text-align: left; white-space: normal; }
.source-results button[aria-pressed="true"] { border-color: var(--brand-500); }
.stage-board { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.stage-board h2 small { color: var(--text-3); font-weight: 500; font-variant-numeric: tabular-nums; }
.stage-empty { padding: 16px; text-align: left; border-width: 1px; }
.briefing-panel { margin-top: 24px; }
.briefing-availability { margin-top: 8px; color: var(--text-2); font-size: .85rem; }
.briefing-panel summary small { color: var(--text-2); font-weight: 500; }
.briefing-result { margin-top: 12px; display: grid; gap: 6px; }
.briefing-text { white-space: pre-wrap; }
.briefing-result ul { padding-left: 20px; }
@media (max-width: 700px) {
  .stage-board { grid-template-columns: minmax(0, 1fr); }
  .progress-heading h1 { margin-bottom: 0; }
  .progress-heading { margin-bottom: 16px; }
}
</style>

<script setup lang="ts">
import { computed, onScopeDispose, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter, type LocationQuery } from 'vue-router'
import { api } from '@/api/client'
import EventCard from '@/components/EventCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { ExpandedSearch, Paginated, Project, WorkEvent } from '@/types'

const route = useRoute()
const router = useRouter()

function queryText(query: LocationQuery, key: string) {
  const value = query[key]
  if (typeof value === 'string') return value
  return value?.[0] ?? null
}

function readFilters(query: LocationQuery) {
  return {
    q: queryText(query, 'q') ?? '',
    date_from: queryText(query, 'date_from') ?? '',
    date_to: queryText(query, 'date_to') ?? '',
    repo: queryText(query, 'repo'),
    pr_number: queryText(query, 'pr_number') ?? '',
    jira_key: queryText(query, 'jira_key') ?? '',
    project_id: queryText(query, 'project_id') ?? '',
    event_type: queryText(query, 'event_type') ?? '',
    root_cause: queryText(query, 'root_cause') ?? '',
  }
}

const filters = reactive(readFilters(route.query))
const advanced = ref(false)
const question = ref('')
const results = ref<Paginated<WorkEvent>>()
const expanded = ref<ExpandedSearch>()
const repos = ref<string[]>([])
const projects = ref<Project[]>([])
const catalogError = ref('')
const loading = ref<'local' | 'ai' | null>(null)
const localError = ref('')
const aiError = ref('')
let request = 0
onScopeDispose(() => { request++ })

const displayed = computed(() => expanded.value ?? results.value)
const eventTypes = {
  pr_created: 'Pull request created',
  review_finding: 'Review finding',
  comment_analysis: 'Comment analysis',
  fix: 'Fix',
  verification: 'Verification',
  reply_drafted: 'Reply drafted',
  reply_published: 'Reply published',
  manual: 'Manual / imported',
}

function activePage(query: LocationQuery) {
  const page = Number(queryText(query, 'page'))
  return Number.isSafeInteger(page) && page >= 1 ? page : 1
}

async function loadCatalogs() {
  const [repoList, projectList] = await Promise.allSettled([api.listRepos(), api.listProjects(true)])
  if (repoList.status === 'fulfilled') repos.value = repoList.value.filter(Boolean)
  if (projectList.status === 'fulfilled') projects.value = projectList.value

  catalogError.value = repoList.status === 'rejected' || projectList.status === 'rejected'
    ? 'Some filter options could not be loaded. You can still search by keyword or date.'
    : ''
}
void loadCatalogs()

async function loadLocal() {
  const current = ++request
  expanded.value = undefined
  localError.value = ''
  aiError.value = ''
  loading.value = 'local'
  try {
    const result = await api.searchEvents({ ...readFilters(route.query), page: activePage(route.query) })
    if (current === request) results.value = result
  } catch (error) {
    if (current !== request) return
    results.value = undefined
    localError.value = error instanceof Error ? error.message : 'Could not search work history.'
  } finally {
    if (current === request) loading.value = null
  }
}

watch(() => route.query, query => {
  if (route.name !== 'search') return
  const applied = readFilters(query)
  Object.assign(filters, applied)
  advanced.value ||= applied.repo !== null || Boolean(
    applied.project_id || applied.pr_number || applied.jira_key || applied.event_type || applied.root_cause,
  )
  void loadLocal()
}, { immediate: true })

async function search() {
  const query = {
    q: filters.q.trim() || undefined,
    date_from: filters.date_from || undefined,
    date_to: filters.date_to || undefined,
    repo: filters.repo ?? undefined,
    pr_number: filters.pr_number || undefined,
    jira_key: filters.jira_key.trim() || undefined,
    event_type: filters.event_type || undefined,
    project_id: filters.project_id || undefined,
    root_cause: filters.root_cause.trim() || undefined,
  }
  const target = { name: 'search', query }
  if (router.resolve(target).fullPath === route.fullPath) {
    await loadLocal()
  } else {
    await router.push(target)
  }
}

async function resetFilters() {
  Object.assign(filters, readFilters({}))
  advanced.value = false
  await search()
}

async function loadAiResults(load: () => Promise<ExpandedSearch>, fallback: string) {
  const current = ++request
  aiError.value = ''
  loading.value = 'ai'
  try {
    const result = await load()
    if (current === request) expanded.value = result
  } catch (error) {
    if (current !== request) return
    aiError.value = error instanceof Error ? error.message : fallback
  } finally {
    if (current === request) loading.value = null
  }
}

function searchWithAgent() {
  const text = question.value.trim()
  if (text) {
    return loadAiResults(() => api.searchSemantic(text), 'AI search could not complete.')
  }
}

function loadExpandedPage(page: number) {
  const expansion = expanded.value?.expansion
  if (expansion) {
    return loadAiResults(() => api.searchExpanded(expansion, page), 'Could not load this page.')
  }
}

function pageLink(page: number) {
  return { name: 'search', query: { ...route.query, page: page > 1 ? page : undefined } }
}
</script>

<template>
  <h1>Search work history</h1>
  <form class="form-card search-box" @submit.prevent="search">
    <label class="field">
      <span class="field-label">Keywords</span>
      <input v-model="filters.q" name="q" type="search" placeholder="Search in Chinese or English" />
    </label>
    <div class="form-grid-2">
      <label class="field">
        <span class="field-label">Start date</span>
        <input v-model="filters.date_from" :max="filters.date_to || undefined" type="date" />
      </label>
      <label class="field">
        <span class="field-label">End date</span>
        <input v-model="filters.date_to" :min="filters.date_from || undefined" type="date" />
      </label>
    </div>
    <button
      type="button"
      class="ghost-btn advanced-toggle"
      :aria-expanded="advanced"
      aria-controls="work-history-filters"
      @click="advanced = !advanced"
    >{{ advanced ? 'Hide advanced filters' : 'Advanced filters' }}</button>

    <div id="work-history-filters" v-show="advanced" class="form-grid-2 advanced-filters">
      <div v-if="catalogError" class="form-span error-banner">
        <span role="alert">{{ catalogError }}</span>
        <button type="button" @click="loadCatalogs">Retry</button>
      </div>
      <label class="field">
        <span class="field-label">Repository</span>
        <select v-model="filters.repo">
          <option :value="null">All repositories</option>
          <option value="">Without repository</option>
          <option v-if="filters.repo && !repos.includes(filters.repo)" :value="filters.repo">{{ filters.repo }}</option>
          <option v-for="repo in repos" :key="repo" :value="repo">{{ repo }}</option>
        </select>
      </label>
      <label class="field">
        <span class="field-label">Project</span>
        <select v-model="filters.project_id">
          <option value="">All projects</option>
          <option value="0">Unassigned</option>
          <option
            v-if="filters.project_id && filters.project_id !== '0' && !projects.some(project => String(project.id) === filters.project_id)"
            :value="filters.project_id"
          >Project #{{ filters.project_id }}</option>
          <option v-for="project in projects" :key="project.id" :value="String(project.id)">{{ project.name }}</option>
        </select>
      </label>
      <label class="field">
        <span class="field-label">PR number</span>
        <input v-model="filters.pr_number" type="text" inputmode="numeric" pattern="[0-9]+" />
      </label>
      <label class="field">
        <span class="field-label">Jira key</span>
        <input v-model="filters.jira_key" type="text" placeholder="RW-…" />
      </label>
      <label class="field">
        <span class="field-label">Event type</span>
        <select v-model="filters.event_type">
          <option value="">All event types</option>
          <option v-for="(label, type) in eventTypes" :key="type" :value="type">{{ label }}</option>
        </select>
      </label>
      <label class="field">
        <span class="field-label">Exact root cause</span>
        <input v-model="filters.root_cause" type="text" />
      </label>
    </div>
    <div class="form-actions">
      <button type="button" class="ghost-btn" @click="resetFilters">Clear filters</button>
      <button type="submit">Search</button>
    </div>
  </form>

  <details class="form-card ai-search">
    <summary>Search with AI</summary>
    <form @submit.prevent="searchWithAgent">
      <p class="meta" id="ai-search-disclosure">
        WorkLedger sends the question to CodeBuddy to generate keywords, then searches the local ledger.
      </p>
      <div class="form-actions">
        <label class="field">
          <span class="field-label">Question</span>
          <input v-model="question" type="search" required aria-describedby="ai-search-disclosure" />
        </label>
        <button type="submit" :disabled="loading === 'ai'">{{ loading === 'ai' ? 'Searching…' : 'Search with AI' }}</button>
      </div>
    </form>
  </details>
  <p v-if="aiError" class="error-banner" role="alert">{{ aiError }} You can retry or use keyword search.</p>
  <div v-if="localError && !expanded" class="error-banner">
    <span role="alert">{{ localError }}</span>
    <button type="button" @click="loadLocal">Retry</button>
  </div>

  <div v-if="loading" class="loading" role="status">Searching…</div>
  <template v-else-if="displayed">
    <div v-if="expanded" class="expanded-summary">
      <p>AI keywords: <strong>{{ expanded.expansion.keywords || '(none)' }}</strong></p>
      <button class="ghost-btn" type="button" @click="loadLocal">Return to keyword search</button>
    </div>
    <p class="result-count" aria-live="polite">{{ displayed.total }} result{{ displayed.total === 1 ? '' : 's' }}</p>
    <div v-if="displayed.items.length" class="card-list">
      <EventCard v-for="event in displayed.items" :key="event.id" :event="event" />
    </div>
    <EmptyState v-else message="No matching records. Try broader keywords or fewer filters." />
    <nav v-if="displayed.pages > 1" class="pagination" aria-label="Search results pages">
      <template v-if="displayed.page > 1">
        <button v-if="expanded" type="button" class="ghost-btn" @click="loadExpandedPage(displayed.page - 1)">Previous</button>
        <RouterLink v-else :to="pageLink(displayed.page - 1)">Previous</RouterLink>
      </template>
      <span>Page {{ displayed.page }} of {{ displayed.pages }}</span>
      <template v-if="displayed.page < displayed.pages">
        <button v-if="expanded" type="button" class="ghost-btn" @click="loadExpandedPage(displayed.page + 1)">Next</button>
        <RouterLink v-else :to="pageLink(displayed.page + 1)">Next</RouterLink>
      </template>
    </nav>
  </template>
</template>

<style scoped>
.search-box { display: grid; gap: 12px; margin-bottom: 12px; }
.search-box .form-actions { margin: 0; }
.advanced-toggle { justify-self: start; }
.ai-search { margin-bottom: 16px; }
.ai-search summary { cursor: pointer; font-weight: 600; }
.ai-search .meta { margin: 12px 0 0; }
.ai-search .form-actions { justify-content: flex-start; align-items: end; flex-wrap: wrap; }
.ai-search .field { flex: 1 1 220px; }
.expanded-summary { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
</style>

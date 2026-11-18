<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useToast } from '@/stores/toast'
import EventCard from '@/components/EventCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { WorkEvent } from '@/types'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const filters = reactive({
  q: (route.query.q as string) || '',
  repo: (route.query.repo as string) || '',
  pr_number: (route.query.pr_number as string) || '',
  jira_key: (route.query.jira_key as string) || '',
  event_type: (route.query.event_type as string) || '',
  date_from: (route.query.date_from as string) || '',
  date_to: (route.query.date_to as string) || '',
})
const page = ref(Number(route.query.page) || 1)
const items = ref<WorkEvent[]>([])
const total = ref(0)
const pages = ref(0)
const loading = ref(false)
const repos = ref<string[]>([])
const semanticQ = ref('')
const semanticBusy = ref(false)

const eventTypes = ['pr_created', 'review_finding', 'comment_analysis', 'fix', 'verification', 'reply_drafted', 'reply_published', 'manual']

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: 20 }
    for (const [k, v] of Object.entries(filters)) if (v) params[k] = v
    const res = await api.searchEvents(params)
    items.value = res.items; total.value = res.total; pages.value = res.pages
  } catch (e) { toast.error(String(e)) } finally { loading.value = false }
}
function submit() {
  page.value = 1
  router.replace({ query: { ...filters, page: 1 } })
  load()
}
function goto(p: number) { page.value = p; load() }
async function semantic() {
  if (!semanticQ.value.trim()) return
  semanticBusy.value = true
  try {
    const res = await api.searchSemantic(semanticQ.value)
    items.value = res.items; total.value = res.total; pages.value = 1
    toast.success(`Expanded to: ${res.expansion.keywords}`)
  } catch { /* toast */ } finally { semanticBusy.value = false }
}

api.listRepos().then(r => repos.value = r)
watch(() => route.query, () => {
  Object.assign(filters, {
    q: (route.query.q as string) || '', repo: (route.query.repo as string) || '',
    pr_number: (route.query.pr_number as string) || '', jira_key: (route.query.jira_key as string) || '',
    event_type: (route.query.event_type as string) || '', date_from: (route.query.date_from as string) || '',
    date_to: (route.query.date_to as string) || '',
  })
  page.value = Number(route.query.page) || 1
  load()
})
load()
</script>

<template>
  <h1>Search work history</h1>
  <form class="search-form" @submit.prevent="submit">
    <input v-model="filters.q" type="text" placeholder="Keywords (Chinese or English)" />
    <select v-model="filters.repo">
      <option value="">All repos</option>
      <option v-for="r in repos" :key="r" :value="r">{{ r }}</option>
    </select>
    <input v-model="filters.pr_number" type="number" placeholder="PR #" />
    <input v-model="filters.jira_key" type="text" placeholder="Jira key (RW-…)" />
    <select v-model="filters.event_type">
      <option value="">All types</option>
      <option v-for="t in eventTypes" :key="t" :value="t">{{ t }}</option>
    </select>
    <input v-model="filters.date_from" type="date" title="From" />
    <input v-model="filters.date_to" type="date" title="To" />
    <button type="submit">Search</button>
  </form>

  <form class="inline-form" style="margin-bottom:1rem" @submit.prevent="semantic">
    <input v-model="semanticQ" type="text" placeholder="Ask a question… e.g. what did I do about authentication?" />
    <button type="submit" :disabled="semanticBusy">{{ semanticBusy ? 'Thinking…' : 'Semantic search' }}</button>
  </form>

  <p class="result-count">{{ total }} result{{ total === 1 ? '' : 's' }}</p>
  <div v-if="loading" class="loading">Searching…</div>
  <div v-else-if="items.length" class="card-list">
    <EventCard v-for="ev in items" :key="ev.id" :event="ev" />
  </div>
  <EmptyState v-else illustration message="No matching records. Try broader keywords or fewer filters." />

  <div v-if="pages > 1" class="pagination">
    <a v-if="page > 1" href="#" @click.prevent="goto(page - 1)">« Prev</a>
    <span>Page {{ page }} / {{ pages }}</span>
    <a v-if="page < pages" href="#" @click.prevent="goto(page + 1)">Next »</a>
  </div>
</template>
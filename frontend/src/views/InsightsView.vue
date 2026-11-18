<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import StatCard from '@/components/StatCard.vue'
import ChartBox from '@/components/ChartBox.vue'
import Badge from '@/components/Badge.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { LabelValue } from '@/types'

const route = useRoute()
const router = useRouter()
const { data: projects, error: projectsError, run: loadProjects } = useAsync(() => api.listProjects(true))

function filtersFromRoute() {
  const { date_from, date_to, project_id } = route.query
  return {
    date_from: typeof date_from === 'string' ? date_from : '',
    date_to: typeof date_to === 'string' ? date_to : '',
    project_id: typeof project_id === 'string' ? project_id : '',
  }
}

const filters = reactive(filtersFromRoute())
const applied = computed(filtersFromRoute)
const { data, loading, error, run } = useAsync(() => api.insights(applied.value), false)
watch(() => route.query, () => {
  if (route.name !== 'insights') return
  Object.assign(filters, applied.value)
  void run()
}, { immediate: true })

async function apply() {
  const query = {
    date_from: filters.date_from || undefined,
    date_to: filters.date_to || undefined,
    project_id: filters.project_id || undefined,
  }
  const target = { name: 'insights', query }
  if (router.resolve(target).fullPath === route.fullPath) {
    await run()
  } else {
    await router.push(target)
  }
}

function localDate(date: Date) {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

async function setPeriod(period: 'all' | 'month' | 'quarter' | 'year') {
  const today = new Date()
  const month = today.getMonth()
  const firstMonth = { month, quarter: Math.floor(month / 3) * 3, year: 0 }
  filters.date_from = period === 'all' ? '' : localDate(new Date(today.getFullYear(), firstMonth[period], 1))
  filters.date_to = period === 'all' ? '' : localDate(today)
  await apply()
}

function eventLink(row: LabelValue) {
  if (row.filters) return { name: 'search', query: row.filters }
}

function todoLink(row: LabelValue) {
  const { date_from, date_to, project_id } = applied.value
  return {
    name: 'todos',
    query: {
      status: row.label,
      date_from: date_from || undefined,
      date_to: date_to || undefined,
      project_id: project_id || undefined,
    },
  }
}
</script>

<template>
  <h1>Insights</h1>
  <form class="form-card insight-filters" @submit.prevent="apply">
    <div class="period-actions" aria-label="Quick date ranges">
      <button type="button" class="ghost-btn" @click="setPeriod('all')">All time</button>
      <button type="button" class="ghost-btn" @click="setPeriod('month')">This month</button>
      <button type="button" class="ghost-btn" @click="setPeriod('quarter')">This quarter</button>
      <button type="button" class="ghost-btn" @click="setPeriod('year')">This year</button>
    </div>
    <div class="form-grid-3">
      <label class="field">
        <span class="field-label">Start date</span>
        <input v-model="filters.date_from" :max="filters.date_to || undefined" type="date" />
      </label>
      <label class="field">
        <span class="field-label">End date</span>
        <input v-model="filters.date_to" :min="filters.date_from || undefined" type="date" />
      </label>
      <label class="field">
        <span class="field-label">Project</span>
        <select v-model="filters.project_id">
          <option value="">All projects</option>
          <option value="0">Unassigned</option>
          <option
            v-if="filters.project_id && filters.project_id !== '0' && !projects?.some(project => String(project.id) === filters.project_id)"
            :value="filters.project_id"
          >Project #{{ filters.project_id }}</option>
          <option v-for="project in projects ?? []" :key="project.id" :value="String(project.id)">{{ project.name }}</option>
        </select>
      </label>
    </div>
    <div v-if="projectsError" class="error-banner">
      <span role="alert">Could not load project names. Date filtering is still available.</span>
      <button type="button" @click="loadProjects">Retry projects</button>
    </div>
    <div class="form-actions"><button type="submit">Apply filters</button></div>
  </form>

  <div v-if="loading" class="loading" role="status">Loading insights…</div>
  <div v-else-if="error" class="error-banner">
    <span role="alert">Could not load insights. {{ error }}</span>
    <button type="button" @click="run">Retry</button>
  </div>
  <template v-else-if="data">
    <div class="stat-row">
      <StatCard :value="data.totals.events" label="Work events" />
      <StatCard :value="data.totals.accomplishments" label="Accomplishments" tone="gold" />
      <StatCard :value="data.totals.cases" label="Cases" />
      <StatCard :value="data.totals.highlights" label="Highlights" tone="gold" />
      <StatCard :value="data.totals.todos" label="To-dos" />
      <StatCard :value="data.totals.snapshots" label="Evidence snapshots" tone="green" />
    </div>

    <div class="chart-grid">
      <section class="card chart-card">
        <h2>Work events over time</h2>
        <ChartBox type="bar" :rows="data.by_month" :link-for="eventLink" />
      </section>
      <section class="card chart-card">
        <h2>By event type</h2>
        <ChartBox type="doughnut" :rows="data.by_type" :link-for="eventLink" />
      </section>
      <section class="card chart-card">
        <h2>By repository</h2>
        <ChartBox type="bar" :rows="data.by_repo" horizontal :link-for="eventLink" />
      </section>
      <section class="card chart-card">
        <h2>By project</h2>
        <ChartBox type="bar" :rows="data.by_project" horizontal :link-for="eventLink" />
      </section>
      <section class="card chart-card">
        <h2>To-do status</h2>
        <ChartBox type="doughnut" :rows="data.todo_status" :link-for="todoLink" />
      </section>
    </div>

    <h2>Common root causes</h2>
    <div v-if="data.root_causes.length" class="card-list">
      <div v-for="row in data.root_causes" :key="row.label" class="card">
        <div class="card-header">
          <Badge variant="warn" :label="`${row.value}×`" />
          <RouterLink v-if="row.filters" :to="{ name: 'search', query: row.filters }"><strong>{{ row.label }}</strong></RouterLink>
          <strong v-else>{{ row.label }}</strong>
        </div>
      </div>
    </div>
    <EmptyState v-else message="No root causes recorded for this selection." />
    <p class="meta root-confirmations">
      Root causes confirmed: {{ data.root_cause_confirmation.confirmed }} of {{ data.root_cause_confirmation.with_cause }}
    </p>
  </template>
</template>

<style scoped>
.insight-filters { display: grid; gap: 12px; }
.period-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.root-confirmations { margin-top: 12px; }
</style>

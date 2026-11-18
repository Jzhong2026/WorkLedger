<script setup lang="ts">
import { api } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import StatCard from '@/components/StatCard.vue'
import ChartBox from '@/components/ChartBox.vue'
import Badge from '@/components/Badge.vue'
import EmptyState from '@/components/EmptyState.vue'

const { data, loading } = useAsync(() => api.insights())
</script>

<template>
  <h1>Insights <small>where your work goes</small></h1>
  <div v-if="loading" class="loading">Loading…</div>
  <template v-else-if="data">
    <div class="stat-row">
      <StatCard :value="data.totals.events" label="Events" />
      <StatCard :value="data.totals.accomplishments" label="Accomplishments" tone="gold" />
      <StatCard :value="data.totals.cases" label="Cases" tone="rust" />
    </div>
    <div class="stat-row">
      <StatCard :value="data.totals.highlights" label="Highlights" />
      <StatCard :value="data.totals.todos" label="To-dos" tone="gold" />
      <StatCard :value="data.totals.snapshots" label="Snapshots" tone="rust" />
    </div>

    <div class="chart-grid">
      <div class="card chart-card"><h2>Events over time</h2><ChartBox type="bar" :rows="data.by_month" /></div>
      <div class="card chart-card"><h2>By type</h2><ChartBox type="doughnut" :rows="data.by_type" /></div>
      <div class="card chart-card"><h2>By repository</h2><ChartBox type="bar" :rows="data.by_repo" horizontal /></div>
      <div class="card chart-card"><h2>To-do status</h2><ChartBox type="doughnut" :rows="data.todo_status" /></div>
    </div>

    <h2>Common root causes</h2>
    <div v-if="data.root_causes.length" class="card-list">
      <div v-for="rc in data.root_causes" :key="rc.label" class="card">
        <div class="card-header"><Badge variant="warn" :label="`${rc.value}×`" /><strong>{{ rc.label }}</strong></div>
      </div>
    </div>
    <EmptyState v-else message="No root causes recorded yet." />
    <p class="meta">Root cause confirmation: {{ data.root_cause_confirmation.confirmed }} / {{ data.root_cause_confirmation.with_cause }} confirmed</p>
  </template>
</template>
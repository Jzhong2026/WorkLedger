<script setup lang="ts">
import { RouterLink } from 'vue-router'
import Badge from './Badge.vue'
import type { WorkEvent } from '@/types'

defineProps<{ event: WorkEvent }>()
</script>

<template>
  <div class="card">
    <div class="card-header">
      <Badge :variant="event.event_type" :label="event.event_type" />
      <Badge v-if="event.jira_key" variant="type" :label="event.jira_key" />
      <RouterLink :to="`/event/${event.id}`"><strong>{{ event.summary || '(no summary)' }}</strong></RouterLink>
    </div>
    <div class="card-meta">
      <span>{{ event.occurred_at.slice(0, 10) }}</span>
      <RouterLink v-if="event.repo" :to="`/pr?repo=${event.repo}&pr_number=${event.pr_number}`">{{ event.repo }}#{{ event.pr_number }}</RouterLink>
      <a v-if="event.evidence_url" :href="event.evidence_url" target="_blank" rel="noopener">Evidence</a>
      <Badge v-if="event.snapshot_status === 'captured'" variant="ok" label="snapshot" />
    </div>
  </div>
</template>
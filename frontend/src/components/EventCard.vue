<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import Badge from './Badge.vue'
import { displayType } from '@/utils/eventDisplay'
import type { WorkEvent } from '@/types'

const props = defineProps<{ event: WorkEvent }>()
const dt = computed(() => displayType(props.event))
</script>

<template>
  <div class="card">
    <div class="card-header">
      <Badge :variant="dt.variant" :label="dt.label" />
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
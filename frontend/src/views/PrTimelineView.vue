<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, RouterLink } from 'vue-router'
import { api } from '@/api/client'
import { useToast } from '@/stores/toast'
import Badge from '@/components/Badge.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { WorkEvent } from '@/types'

const route = useRoute()
const toast = useToast()
const timeline = ref<WorkEvent[]>([])
const loading = ref(true)
const repo = ref('')
const pr = ref(0)

async function load() {
  repo.value = (route.query.repo as string) || ''
  pr.value = Number(route.query.pr_number) || 0
  if (!repo.value || !pr.value) { loading.value = false; return }
  loading.value = true
  try { timeline.value = await api.prTimeline(repo.value, pr.value) }
  catch (e) { toast.error(String(e)) } finally { loading.value = false }
}
watch(() => route.query, load, { immediate: true })
</script>

<template>
  <h1>{{ repo }} <small>PR #{{ pr }}</small></h1>
  <div v-if="loading" class="loading">Loading…</div>
  <div v-else-if="timeline.length" class="timeline">
    <div v-for="ev in timeline" :key="ev.id" class="timeline-item">
      <div class="timeline-dot"></div>
      <div class="card">
        <div class="card-header">
          <Badge :variant="ev.event_type" :label="ev.event_type" />
          <RouterLink :to="`/event/${ev.id}`"><strong>{{ ev.summary || '(no summary)' }}</strong></RouterLink>
        </div>
        <div class="card-meta">
          <span>{{ ev.occurred_at }}</span>
          <span v-if="ev.comment_id">Comment {{ ev.comment_id }}</span>
          <a v-if="ev.evidence_url" :href="ev.evidence_url" target="_blank" rel="noopener">Evidence</a>
          <Badge v-if="ev.reply_status" variant="type" :label="ev.reply_status" />
        </div>
        <p v-if="ev.detail">{{ ev.detail.slice(0, 200) }}</p>
      </div>
    </div>
  </div>
  <EmptyState v-else illustration message="No events recorded for this PR." />
</template>
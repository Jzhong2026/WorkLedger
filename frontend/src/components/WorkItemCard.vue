<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import Badge from '@/components/Badge.vue'
import { displayWorkTimestamp, followupDate, isStale, stageInfo } from '@/utils/workItems'
import type { WorkItem } from '@/types/workItems'

const props = defineProps<{ item: WorkItem }>()
const stage = computed(() => stageInfo(props.item.stage))
</script>

<template>
  <article class="card work-summary">
    <div class="card-header">
      <RouterLink :to="`/work-items/${item.id}`"><strong>{{ item.title }}</strong></RouterLink>
      <Badge :variant="stage.badge" :label="stage.label" />
      <Badge v-if="item.needs_decision" variant="warn" label="Decision needed" />
      <Badge v-if="isStale(item)" variant="warn" label="7+ days without an update" />
    </div>
    <div class="card-meta">
      <span v-if="item.jira_key">{{ item.jira_key }}</span>
      <span>Next owner {{ item.owner || 'unassigned' }}</span>
      <span>Updated {{ displayWorkTimestamp(item.updated_at) }}</span>
      <span v-if="followupDate(item)">Follow up {{ followupDate(item) }}</span>
    </div>
    <p v-if="item.last_verified_result"><strong>Last verified</strong> {{ item.last_verified_result }}</p>
    <p v-if="item.blocker"><strong>Blocker</strong> {{ item.blocker }}</p>
    <p v-if="item.next_step"><strong>Next step</strong> {{ item.next_step }}</p>
  </article>
</template>

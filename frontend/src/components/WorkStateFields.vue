<script setup lang="ts">
import { workStages, type WorkItemState } from '@/types/workItems'

const state = defineModel<WorkItemState>({ required: true })
</script>

<template>
  <div class="form-grid-2">
    <label class="field">
      <span class="field-label">Stage</span>
      <select v-model="state.stage">
        <option v-for="stage in workStages" :key="stage.value" :value="stage.value">{{ stage.label }}</option>
      </select>
    </label>
    <label class="field">
      <span class="field-label">Next owner</span>
      <input v-model="state.owner" type="text" />
    </label>
    <label class="field">
      <span class="field-label">Follow-up date</span>
      <input v-model="state.followup_date" type="date" />
    </label>
    <label class="field checkbox-field">
      <input v-model="state.needs_decision" type="checkbox" />
      <span class="field-label">Needs a decision</span>
    </label>
    <label class="field form-span">
      <span class="field-label">Last verified result</span>
      <textarea v-model="state.last_verified_result" rows="2"></textarea>
    </label>
    <label class="field">
      <span class="field-label">Blocker</span>
      <textarea v-model="state.blocker" rows="2"></textarea>
    </label>
    <label class="field">
      <span class="field-label">Next step</span>
      <textarea v-model="state.next_step" rows="2"></textarea>
    </label>
  </div>
</template>

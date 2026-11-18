<script setup lang="ts">
import emptyImg from '@/assets/img/empty-ledger.png'
defineProps<{ message: string; illustration?: boolean }>()
</script>

<template>
  <div class="empty">
    <img v-if="illustration" class="empty-illustration" :src="emptyImg" alt="Empty ledger" />
    <slot>{{ message }}</slot>
  </div>
</template>
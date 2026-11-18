<script setup lang="ts">
defineProps<{ value: number | string; label: string; tone?: 'brand' | 'gold' | 'rust' }>()
</script>

<template>
  <div class="stat" :class="tone">
    <div class="stat-num">{{ value }}</div>
    <div class="stat-label">{{ label }}</div>
  </div>
</template>
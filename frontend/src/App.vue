<script setup lang="ts">
import AppLayout from '@/components/AppLayout.vue'
import ToastHost from '@/components/ToastHost.vue'
</script>

<template>
  <AppLayout>
    <RouterView />
  </AppLayout>
  <ToastHost />
</template>
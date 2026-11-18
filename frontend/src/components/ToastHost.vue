<script setup lang="ts">
import { useToast } from '@/stores/toast'
const toast = useToast()
</script>

<template>
  <Teleport to="body">
    <div id="toast">
      <div v-for="t in toast.toasts" :key="t.id" class="toast" :class="t.kind">
        <span class="toast-msg">{{ t.message }}</span>
        <button class="toast-close" @click="toast.dismiss(t.id)">×</button>
      </div>
    </div>
  </Teleport>
</template>
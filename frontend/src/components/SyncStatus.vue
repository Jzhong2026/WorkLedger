<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, errorMessage } from '@/api/client'
import { useToast } from '@/stores/toast'
import type { SyncStatusMap } from '@/types'

const toast = useToast()
const states = ref<SyncStatusMap | null>(null)
const open = ref(false)
const syncing = ref(false)
const root = ref<HTMLElement | null>(null)
let timer: ReturnType<typeof setInterval> | undefined

const rows = computed(() => Object.values(states.value ?? {}))
const tone = computed(() => {
  if (!rows.value.length) return 'idle'
  if (rows.value.some(r => r.last_error)) return 'error'
  if (rows.value.some(r => r.stale)) return 'stale'
  return 'ok'
})
const label = computed(() => ({ ok: 'Sync fresh', stale: 'Sync stale', error: 'Sync error', idle: 'Sync' }[tone.value]))

function shortName(source: string) {
  return source.startsWith('bitbucket:') ? source.split('/').pop() ?? source : source
}
function relative(iso: string | null) {
  if (!iso) return 'never'
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  return hours < 48 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`
}
async function refresh() {
  try { states.value = await api.syncStatus() } catch { /* chip stays idle on failure */ }
}
async function syncNow() {
  if (syncing.value) return
  syncing.value = true
  try {
    await api.syncAll()
    toast.success('Sync complete')
  } catch (err) {
    toast.error(errorMessage(err))
  } finally {
    syncing.value = false
    await refresh()
  }
}
function onDocClick(event: MouseEvent) {
  if (open.value && root.value && !root.value.contains(event.target as Node)) open.value = false
}
function onFocus() { void refresh() }
onMounted(() => {
  void refresh()
  timer = setInterval(refresh, 60000)
  document.addEventListener('click', onDocClick)
  window.addEventListener('focus', onFocus)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('focus', onFocus)
})
</script>

<template>
  <div ref="root" class="sync-status">
    <button type="button" class="sync-chip" :class="`tone-${tone}`" :aria-expanded="open" @click="open = !open">
      <span class="sync-dot" aria-hidden="true"></span>{{ label }}
    </button>
    <div v-if="open" class="sync-panel" role="dialog" aria-label="Sync status">
      <p v-if="!rows.length" class="meta">No sync sources recorded yet.</p>
      <div v-for="r in rows" :key="r.source" class="sync-row">
        <div class="sync-row-head">
          <strong>{{ shortName(r.source) }}</strong>
          <span v-if="r.stale" class="sync-badge stale">stale</span>
          <span v-if="r.last_error" class="sync-badge error">error</span>
        </div>
        <span class="meta">Last success: {{ relative(r.last_success_at) }}</span>
        <p v-if="r.last_error" class="sync-error">{{ r.last_error }}</p>
      </div>
      <button type="button" class="ghost-btn sync-now" :disabled="syncing" @click="syncNow">
        {{ syncing ? 'Syncing…' : 'Sync now' }}
      </button>
    </div>
  </div>
</template>
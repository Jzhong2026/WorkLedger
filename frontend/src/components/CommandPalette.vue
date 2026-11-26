<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api, errorMessage } from '@/api/client'
import { useToast } from '@/stores/toast'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()
const router = useRouter()
const toast = useToast()

interface Command {
  id: string
  title: string
  icon: string
  category: 'Navigate' | 'Action' | 'Search'
  run: () => unknown
}

const query = ref('')
const index = ref(0)
const input = ref<HTMLInputElement>()
const captureInput = ref<HTMLTextAreaElement>()
const captureText = ref('')
const capturing = ref(false)
const mode = ref<'commands' | 'capture'>('commands')

const navigation = [
  ['/', '◉', 'Today'],
  ['/work-items', '▣', 'Project progress'],
  ['/inbox', '✉', 'Inbox'],
  ['/search', '⌕', 'Search'],
  ['/todos', '✓', 'To-dos'],
  ['/retrospective', '★', 'Retrospective'],
  ['/weekly', '▤', 'Weekly review'],
  ['/learning', '◇', 'Lessons'],
  ['/insights', '▤', 'Insights'],
  ['/settings', '⚙', 'Settings'],
] as const

const commands = computed<Command[]>(() => {
  const items: Command[] = navigation.map(([to, icon, title]) => ({
    id: `nav:${to}`, title, icon, category: 'Navigate',
    run: () => router.push(to),
  }))
  items.push(
    { id: 'action:capture', title: 'Capture a work note', icon: '✎', category: 'Action', run: startCapture },
    { id: 'action:todo', title: 'Add a to-do', icon: '+', category: 'Action', run: () => router.push('/todos') },
  )
  const term = query.value.trim()
  if (term.length >= 2) {
    items.unshift({
      id: 'search:query', title: `Search work history for “${term}”`, icon: '⌕', category: 'Search',
      run: () => router.push({ path: '/search', query: { q: term } }),
    })
  }
  return items
})

const filtered = computed(() => {
  const term = query.value.trim().toLowerCase()
  if (!term) return commands.value
  return commands.value.filter(c => c.title.toLowerCase().includes(term))
})

function startCapture() {
  mode.value = 'capture'
  query.value = ''
  captureText.value = ''
  nextTick(() => captureInput.value?.focus())
}

async function capture() {
  const text = captureText.value.trim()
  if (!text || capturing.value) return
  capturing.value = true
  try {
    await api.captureNote(text)
    toast.success('Note captured in Inbox')
    close()
    await router.push('/inbox')
  } catch (error) {
    toast.error(errorMessage(error))
  } finally {
    capturing.value = false
  }
}

function choose(command?: Command) {
  if (!command) return
  void command.run()
  if (mode.value !== 'capture') close()
}

function close() {
  emit('update:open', false)
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); close(); return }
  if (mode.value === 'capture') {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); void capture() }
    return
  }
  if (event.key === 'ArrowDown') { event.preventDefault(); index.value = (index.value + 1) % Math.max(filtered.value.length, 1) }
  if (event.key === 'ArrowUp') { event.preventDefault(); index.value = (index.value - 1 + filtered.value.length) % Math.max(filtered.value.length, 1) }
  if (event.key === 'Enter') { event.preventDefault(); choose(filtered.value[index.value]) }
}

watch(() => props.open, async open => {
  if (open) {
    query.value = ''; index.value = 0; mode.value = 'commands'; captureText.value = ''
    document.body.style.overflow = 'hidden'
    await nextTick()
    input.value?.focus()
  } else {
    document.body.style.overflow = ''
  }
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="palette-overlay" @click.self="close">
      <section class="command-palette" role="dialog" aria-modal="true" aria-label="Command palette" @keydown="onKey">
        <div v-if="mode === 'commands'" class="palette-input-wrap">
          <span class="palette-search-icon" aria-hidden="true">⌕</span>
          <input ref="input" v-model="query" type="text" placeholder="Navigate, search, or capture a note…" @input="index = 0" />
          <kbd class="palette-esc">esc</kbd>
        </div>
        <div v-else class="palette-mode-title">
          <span aria-hidden="true">✎</span><strong>Capture a work note</strong><kbd class="palette-esc">esc</kbd>
        </div>

        <div v-if="mode === 'capture'" class="palette-capture">
          <label class="field"><span class="field-label">Work note</span>
            <textarea ref="captureInput" v-model="captureText" rows="5" placeholder="What happened? Add evidence or follow-up details if you have them."></textarea>
          </label>
          <div class="form-actions">
            <button type="button" class="ghost-btn" @click="mode = 'commands'; query = ''; nextTick(() => input?.focus())">Back</button>
            <button type="button" :disabled="capturing || !captureText.trim()" @click="capture">{{ capturing ? 'Capturing…' : 'Capture note' }}</button>
            <span class="meta">Ctrl + Enter to capture</span>
          </div>
        </div>

        <div v-else class="palette-list">
          <button v-for="(command, i) in filtered" :key="command.id" type="button" class="palette-item" :class="{ active: i === index }" @click="choose(command)" @mouseenter="index = i">
            <span class="palette-item-icon" aria-hidden="true">{{ command.icon }}</span>
            <span class="palette-item-title">{{ command.title }}</span>
            <span class="palette-item-category">{{ command.category }}</span>
          </button>
          <p v-if="!filtered.length" class="palette-empty">No matching commands. Try a different word.</p>
        </div>

        <footer class="palette-footer">
          <template v-if="mode === 'capture'">
            <span><kbd>Ctrl</kbd> + <kbd>↵</kbd> capture</span>
            <span><kbd>esc</kbd> close</span>
            <span class="palette-footer-right">Saved to Inbox</span>
          </template>
          <template v-else>
            <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
            <span><kbd>↵</kbd> select</span>
            <span class="palette-footer-right">Ctrl K to toggle</span>
          </template>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.palette-overlay { position: fixed; inset: 0; z-index: 1100; background: rgba(15,23,42,.45); backdrop-filter: blur(5px); display: flex; align-items: flex-start; justify-content: center; padding-top: 12vh; animation: paletteFade .15s ease-out; }
.command-palette { width: min(620px, 92vw); max-height: 70vh; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: var(--sh-lg); overflow: hidden; animation: palettePop .2s cubic-bezier(.34,1.2,.64,1); }
.palette-input-wrap { display: flex; align-items: center; gap: 10px; padding: 16px 18px; border-bottom: 1px solid var(--border); }
.palette-mode-title { display: flex; align-items: center; gap: 10px; padding: 16px 18px; border-bottom: 1px solid var(--border); font-size: .95rem; }
.palette-mode-title > span { color: var(--brand-500); font-size: 1.1rem; }
.palette-mode-title strong { flex: 1; font-weight: 600; }
.palette-search-icon { font-size: 1.2rem; color: var(--text-3); }
.palette-input-wrap input { flex: 1; border: none; outline: none; background: transparent; font-size: 1rem; color: var(--text); box-shadow: none; }
.palette-esc { font-family: var(--font-mono); font-size: .68rem; padding: 3px 7px; border: 1px solid var(--border); border-radius: 5px; color: var(--text-3); background: var(--surface-3); }
.palette-list { flex: 1; overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 2px; }
.palette-item { width: 100%; height: auto; display: flex; align-items: center; gap: 10px; padding: 11px 12px; border: none; border-radius: 9px; background: transparent; color: var(--text); font-size: .9rem; text-align: left; box-shadow: none; }
.palette-item:hover, .palette-item.active { background: var(--brand-soft); color: var(--brand-700); }
.palette-item-icon { width: 22px; text-align: center; color: var(--text-3); font-size: 1rem; }
.palette-item.active .palette-item-icon { color: var(--brand-500); }
.palette-item-title { flex: 1; font-weight: 500; }
.palette-item-category { font-size: .66rem; font-weight: 600; color: var(--text-3); background: var(--surface-3); border-radius: 999px; padding: 3px 8px; }
.palette-item.active .palette-item-category { color: var(--brand-600); background: var(--surface); }
.palette-empty { padding: 28px; text-align: center; color: var(--text-3); font-size: .88rem; }
.palette-capture { padding: 18px; }
.palette-capture .form-actions { justify-content: flex-start; flex-wrap: wrap; }
.palette-capture .meta { margin: 0; }
.palette-footer { display: flex; align-items: center; gap: 16px; padding: 10px 16px; border-top: 1px solid var(--border); background: var(--surface-2); font-size: .72rem; color: var(--text-3); }
.palette-footer kbd { font-family: var(--font-mono); padding: 1px 5px; border: 1px solid var(--border); border-radius: 4px; background: var(--surface); margin-right: 3px; }
.palette-footer-right { margin-left: auto; opacity: .75; }
@keyframes paletteFade { from { opacity: 0; } to { opacity: 1; } }
@keyframes palettePop { from { opacity: 0; transform: translateY(-10px) scale(.98); } to { opacity: 1; transform: translateY(0) scale(1); } }
</style>
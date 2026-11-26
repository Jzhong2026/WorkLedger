<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, errorMessage } from '@/api/client'
import { learningApi } from '@/api/learning'
import { workItemsApi } from '@/api/workItems'
import { useAsync } from '@/composables/useAsync'
import { useToast } from '@/stores/toast'
import type { Lesson, LessonFields, LessonKind, LessonOutcome, LessonStatus } from '@/types/learning'
import type { WorkEvent } from '@/types'

const route = useRoute()
const router = useRouter()
const toast = useToast()

function queryId(key: string) {
  const value = Number(route.query[key])
  return Number.isSafeInteger(value) && value > 0 ? value : null
}

const contextId = computed(() => queryId('work_item_id'))
const selectedId = computed(() => queryId('lesson_id'))
const initialQuery = computed(() => typeof route.query.q === 'string' ? route.query.q : '')
const query = ref(initialQuery.value)
const searchedQuery = ref(initialQuery.value)
const filters = reactive<{ q: string; status: LessonStatus | ''; page: number }>({
  q: '', status: '', page: 1,
})
const filterInput = ref('')

const { data: shelf, loading: shelfLoading, error: shelfError, run: loadShelf } = useAsync(
  () => learningApi.list({ ...filters, status: filters.status || undefined }),
)
const { data: workContext, error: contextError, run: loadContext } = useAsync(
  () => contextId.value ? workItemsApi.context(contextId.value) : Promise.resolve(null), false,
)
const { data: recommendations, loading: recallLoading, error: recallError, run: loadRecall } = useAsync(
  () => searchedQuery.value.trim()
    ? learningApi.recall(searchedQuery.value.trim(), workContext.value?.item.project_id ?? queryId('project_id'), 5, contextId.value)
    : Promise.resolve([]),
  false,
)
const { data: selected, loading: detailLoading, error: detailError, run: loadDetail } = useAsync(
  () => selectedId.value ? learningApi.get(selectedId.value) : Promise.resolve(null),
  false,
)
const { data: availableItems, loading: itemsLoading, error: itemsError, run: loadItems } = useAsync(async () => {
  const first = await workItemsApi.list({ page_size: 100 })
  const items = [...first.items]
  for (let page = 2; page <= first.pages; page++) {
    const response = await workItemsApi.list({ page, page_size: 100 })
    items.push(...response.items)
  }
  return items
}, false)
const { data: agentStatus } = useAsync(api.agentStatus)
const agentReady = computed(() =>
  !!(agentStatus.value?.enabled && agentStatus.value.cli_available && agentStatus.value.key_configured),
)

watch([contextId, initialQuery], async ([id, initial]) => {
  query.value = initial
  await loadContext()
  if (id !== contextId.value || initial !== initialQuery.value) return
  const item = workContext.value?.item
  if (!query.value && item && item.id === id) {
    query.value = [item.title, item.goal].filter(Boolean).join(' ').slice(0, 3000)
  }
  findLessons()
}, { immediate: true })
watch(selectedId, loadDetail, { immediate: true })

const editorOpen = ref(false)
const editing = ref<Lesson | null>(null)
const form = reactive({
  kind: 'process' as LessonKind, title: '', trigger: '', first_step: '', limits: '',
  tags: '', source_work_item_id: null as number | null, source_event_id: null as number | null, evidence_url: '',
})
const { data: source, loading: sourceLoading, error: sourceError, run: loadSource } = useAsync(
  () => form.source_work_item_id ? workItemsApi.context(form.source_work_item_id) : Promise.resolve(null),
  false,
)
watch(() => form.source_work_item_id, loadSource)
const evidenceEvents = computed(() => {
  if (!source.value || source.value.item.id !== form.source_work_item_id) return []
  const candidates = [source.value.source_event, ...source.value.events].filter((event): event is WorkEvent => !!event)
  return [...new Map(candidates.map(event => [event.id, event])).values()]
})
const editorError = ref('')
const detailActionError = ref('')
const busy = ref(false)
const useItem = ref<number | null>(contextId.value)
const outcome = ref<LessonOutcome>('applied')
const useDetail = ref('')
watch([selected, useItem], () => {
  const existing = selected.value?.uses.find(use => use.work_item_id === useItem.value)
  outcome.value = existing?.outcome ?? 'applied'
  useDetail.value = existing?.detail ?? ''
})
watch(contextId, value => { useItem.value = value })

function openLesson(lessonId: number | null) {
  detailActionError.value = ''
  return router.replace({ query: { ...route.query, lesson_id: lessonId ?? undefined } })
}

function ensureItems() {
  if (!availableItems.value && !itemsLoading.value) void loadItems()
}

watch(selectedId, value => { if (value) ensureItems() }, { immediate: true })

function openEditor(lesson?: Lesson) {
  editing.value = lesson ?? null
  editorError.value = ''
  ensureItems()
  Object.assign(form, {
    kind: lesson?.kind ?? 'process', title: lesson?.title ?? '', trigger: lesson?.trigger ?? '',
    first_step: lesson?.first_step ?? '', limits: lesson?.limits ?? '', tags: lesson?.tags.join(', ') ?? '',
    source_work_item_id: lesson?.source_work_item_id ?? contextId.value,
    source_event_id: lesson?.source_event_id ?? null,
    evidence_url: lesson?.evidence_url_override ?? '',
  })
  editorOpen.value = true
}

function lessonFields(): LessonFields {
  return {
    kind: form.kind, title: form.title.trim(), trigger: form.trigger.trim(),
    first_step: form.first_step.trim(), limits: form.limits.trim() || null,
    tags: form.tags.split(/[,，、]/).map(tag => tag.trim()).filter(Boolean),
    source_event_id: form.source_event_id, evidence_url: form.evidence_url.trim() || null,
  }
}

async function changeLesson(action: () => Promise<void>, errorTarget = detailActionError) {
  if (busy.value) return
  busy.value = true
  errorTarget.value = ''
  try {
    await action()
    await Promise.all([loadDetail(), loadShelf(), loadRecall()])
    toast.success('Learning record saved')
  } catch (error) {
    errorTarget.value = errorMessage(error)
  } finally {
    busy.value = false
  }
}

function saveLesson() {
  const sourceId = form.source_work_item_id
  if (!sourceId) return
  return changeLesson(async () => {
    const fields = lessonFields()
    const saved = editing.value
      ? await learningApi.update(editing.value.id, fields)
      : await learningApi.create({ source_work_item_id: sourceId, ...fields })
    editorOpen.value = false
    await openLesson(saved.id)
  }, editorError)
}

function draftLesson() {
  const itemId = form.source_work_item_id
  const eventId = form.source_event_id
  if (!itemId || !eventId) return
  return changeLesson(async () => {
    const lesson = await learningApi.draft(itemId, eventId)
    editorOpen.value = false
    await openLesson(lesson.id)
  }, editorError)
}

function review(status: 'confirmed' | 'declined') {
  const id = selected.value?.id
  if (!id) return
  return changeLesson(async () => { await learningApi.review(id, status) })
}

function recordUse() {
  const id = selected.value?.id
  const workItemId = useItem.value
  if (!id || !workItemId) return
  return changeLesson(async () => {
    await learningApi.recordUse(id, {
      work_item_id: workItemId, outcome: outcome.value, detail: useDetail.value.trim() || null,
    })
  })
}

function findLessons() {
  searchedQuery.value = query.value
  void loadRecall()
}

function filterShelf(page = 1) {
  filters.q = filterInput.value.trim()
  filters.page = page
  void loadShelf()
}

const outcomeLabels: Record<LessonOutcome, string> = {
  applied: 'Applied · outcome pending', helped: 'Helped', did_not_help: 'Did not help',
}
</script>

<template>
  <header class="learning-heading">
    <h1>Learning</h1>
    <button type="button" :disabled="busy" @click="openEditor()">Add lesson</button>
  </header>

  <section aria-labelledby="recall-heading">
    <h2 id="recall-heading">Find lessons for new work</h2>
    <p v-if="workContext && !contextError" class="meta">
      For <RouterLink :to="{ name: 'work-item', params: { id: workContext.item.id } }">{{ workContext.item.title }}</RouterLink>
    </p>
    <p v-if="contextError" class="meta">Work item details are unavailable. You can still search by topic.</p>
    <form class="form-card inline-form" @submit.prevent="findLessons">
      <label class="field flex-field">
        <span class="field-label">Work description or topic</span>
        <input v-model="query" maxlength="3000" placeholder="e.g. verify fuzzy matching in a pick list" />
      </label>
      <button type="submit" :disabled="recallLoading">Find related lessons</button>
    </form>
    <p v-if="recallLoading" role="status">Finding reviewed lessons…</p>
    <div v-else-if="recallError" class="card" role="alert">
      {{ recallError }} <button type="button" class="ghost-btn" @click="loadRecall">Retry</button>
    </div>
    <template v-else-if="searchedQuery.trim()">
      <ul v-if="recommendations?.length" class="learning-results">
        <li v-for="match in recommendations" :key="match.id" class="card">
          <RouterLink :to="{ query: { ...route.query, lesson_id: match.id } }"><strong>{{ match.title }}</strong></RouterLink>
          <p>{{ match.first_step }}</p>
          <p class="meta">{{ match.reasons.join(' · ') }}</p>
        </li>
      </ul>
      <p v-else class="meta">No confirmed lessons match this topic.</p>
    </template>
  </section>

  <section v-if="editorOpen" aria-labelledby="editor-heading">
    <h2 id="editor-heading">{{ editing ? 'Edit lesson' : 'New lesson candidate' }}</h2>
    <p v-if="editing?.status === 'confirmed'" class="meta">Saving changes sends this lesson back for review.</p>
    <form class="form-card form-grid-2" @submit.prevent="saveLesson">
      <label class="field">
        <span class="field-label">Source work item</span>
        <select v-model="form.source_work_item_id" :disabled="!!editing || itemsLoading || busy"
          required @change="form.source_event_id = null">
          <option :value="null">Select a work item</option>
          <option v-for="item in availableItems" :key="item.id" :value="item.id">
            {{ item.title }} · {{ item.jira_key || ('#' + item.id) }}
          </option>
          <option v-if="editing && !availableItems?.some(i => i.id === editing?.source_work_item_id)"
            :value="editing.source_work_item_id">{{ editing.source_work_item_title }}</option>
        </select>
      </label>
      <label class="field">
        <span class="field-label">Source event</span>
        <select v-model="form.source_event_id" :disabled="!form.source_work_item_id || sourceLoading || editing?.origin === 'codebuddy' || busy">
          <option :value="null">No event selected</option>
          <option v-for="event in evidenceEvents" :key="event.id" :value="event.id">{{ event.summary || ('Event #' + event.id) }}</option>
          <option v-if="editing?.source_event_id && !evidenceEvents.some(e => e.id === editing?.source_event_id)"
            :value="editing.source_event_id">{{ editing.source_event_summary || ('Event #' + editing.source_event_id) }}</option>
        </select>
      </label>
      <div v-if="itemsError || sourceError" class="form-span" role="alert">
        {{ itemsError || sourceError }}
        <button type="button" class="ghost-btn" @click="itemsError ? loadItems() : loadSource()">Retry</button>
      </div>
      <p v-if="!editing && availableItems?.length === 0" class="form-span">
        Add a work item to give this lesson a source.
      </p>
      <RouterLink v-if="!editing" class="form-span" to="/work-items?discover=1">Find an older source record</RouterLink>
      <div v-if="agentReady && !editing" class="form-span">
        <button type="button" class="ghost-btn" :disabled="!form.source_event_id || busy" @click="draftLesson">Draft with CodeBuddy</button>
        <p class="meta">Sends the selected event text and work item title and goal to CodeBuddy.</p>
      </div>
      <label class="field">
        <span class="field-label">Title</span><input v-model="form.title" maxlength="140" required />
      </label>
      <label class="field">
        <span class="field-label">Type</span>
        <select v-model="form.kind"><option value="process">Process improvement</option><option value="skill">Skill</option></select>
      </label>
      <label class="field form-span">
        <span class="field-label">When to use it</span><textarea v-model="form.trigger" rows="2" maxlength="800" required />
      </label>
      <label class="field form-span">
        <span class="field-label">First step</span><textarea v-model="form.first_step" rows="2" maxlength="1800" required />
      </label>
      <label class="field form-span">
        <span class="field-label">Limits or exceptions</span><textarea v-model="form.limits" rows="2" maxlength="1200" />
      </label>
      <label class="field">
        <span class="field-label">Tags</span><input v-model="form.tags" placeholder="Comma-separated" />
      </label>
      <label class="field">
        <span class="field-label">Evidence URL</span><input v-model="form.evidence_url" type="url" maxlength="2000" />
      </label>
      <p v-if="editorError" class="form-span" role="alert">{{ editorError }}</p>
      <div class="form-actions form-span">
        <button type="submit" :disabled="!form.source_work_item_id || busy || !form.title.trim() || !form.trigger.trim() || !form.first_step.trim()">
          {{ busy ? 'Working…' : 'Save candidate' }}
        </button>
        <button type="button" class="ghost-btn" :disabled="busy" @click="editorOpen = false">Cancel</button>
      </div>
    </form>
  </section>

  <section v-if="selectedId" aria-labelledby="detail-heading">
    <h2 id="detail-heading">Lesson details</h2>
    <p v-if="detailLoading" role="status">Loading lesson…</p>
    <div v-else-if="detailError" class="card" role="alert">
      {{ detailError }} <button type="button" class="ghost-btn" @click="loadDetail">Retry</button>
    </div>
    <article v-else-if="selected" class="card lesson-detail">
      <div class="lesson-header">
        <h3>{{ selected.title }}</h3>
        <span :class="['badge', selected.status === 'confirmed' ? 'badge-done' : 'badge-pending']">{{ selected.status }}</span>
      </div>
      <p class="source-line">
        <strong>Source</strong>
        <RouterLink :to="{ name: 'work-item', params: { id: selected.source_work_item_id } }">{{ selected.source_work_item_title }}</RouterLink>
        <span v-if="selected.source_project_name"> · {{ selected.source_project_name }}</span>
      </p>
      <p v-if="selected.source_event_id || selected.evidence_url">
        <RouterLink v-if="selected.source_event_id" :to="'/event/' + selected.source_event_id">{{ selected.source_event_summary || 'Source event' }}</RouterLink>
        <span v-if="selected.source_event_id && selected.evidence_url"> · </span>
        <a v-if="selected.evidence_url" :href="selected.evidence_url" target="_blank" rel="noopener noreferrer">Evidence link</a>
      </p>
      <dl>
        <dt>When to use it</dt><dd>{{ selected.trigger }}</dd>
        <dt>First step</dt><dd>{{ selected.first_step }}</dd>
        <template v-if="selected.limits"><dt>Limits</dt><dd>{{ selected.limits }}</dd></template>
      </dl>
      <p class="meta">{{ selected.kind === 'skill' ? 'Skill' : 'Process improvement' }} · {{ selected.origin === 'codebuddy' ? 'CodeBuddy draft' : 'Manual' }}<template v-if="selected.tags.length"> · {{ selected.tags.join(', ') }}</template></p>
      <div class="card-actions">
        <button v-if="selected.status !== 'confirmed'" type="button" :disabled="busy" @click="review('confirmed')">Confirm lesson</button>
        <button v-if="selected.status !== 'declined'" type="button" class="ghost-btn" :disabled="busy" @click="review('declined')">Decline</button>
        <button type="button" class="ghost-btn" :disabled="busy" @click="openEditor(selected)">Edit</button>
        <button type="button" class="ghost-btn" :disabled="busy" @click="openLesson(null)">Close</button>
      </div>
      <h3>Reuse history</h3>
      <ul v-if="selected.uses.length" class="use-list">
        <li v-for="reuse in selected.uses" :key="reuse.work_item_id">
          <RouterLink :to="'/work-items/' + reuse.work_item_id">{{ reuse.work_item_title }}</RouterLink>
          · {{ outcomeLabels[reuse.outcome] }} · {{ reuse.updated_at.slice(0, 10) }}
          <p v-if="reuse.detail">{{ reuse.detail }}</p>
        </li>
      </ul>
      <p v-else class="meta">No reuse recorded.</p>
      <form v-if="selected.status === 'confirmed'" class="form-grid-2" @submit.prevent="recordUse">
        <label class="field">
          <span class="field-label">Work item where you used this</span>
          <select v-model="useItem" required :disabled="itemsLoading || busy">
            <option :value="null">Select a work item</option>
            <option v-for="item in availableItems?.filter(i => i.id !== selected?.source_work_item_id)" :key="item.id" :value="item.id">
              {{ item.title }} · {{ item.jira_key || ('#' + item.id) }}
            </option>
          </select>
        </label>
        <label class="field">
          <span class="field-label">Observed outcome</span>
          <select v-model="outcome">
            <option v-for="(label, key) in outcomeLabels" :key="key" :value="key">{{ label }}</option>
          </select>
        </label>
        <label class="field form-span">
          <span class="field-label">Outcome details</span><textarea v-model="useDetail" rows="2" maxlength="1500" />
        </label>
        <div v-if="itemsError" class="form-span" role="alert">
          {{ itemsError }} <button type="button" class="ghost-btn" @click="loadItems">Retry</button>
        </div>
        <div class="form-actions form-span">
          <button type="submit" :disabled="!useItem || useItem === selected.source_work_item_id || busy">Save reuse outcome</button>
        </div>
      </form>
      <p v-if="detailActionError" role="alert">{{ detailActionError }}</p>
    </article>
  </section>

  <section aria-labelledby="shelf-heading">
    <h2 id="shelf-heading">Saved lessons</h2>
    <form class="form-card inline-form" @submit.prevent="filterShelf()">
      <label class="field flex-field">
        <span class="field-label">Search saved lessons</span><input v-model="filterInput" maxlength="2000" />
      </label>
      <label class="field">
        <span class="field-label">Review status</span>
        <select v-model="filters.status" @change="filterShelf()">
          <option value="">All statuses</option><option value="candidate">Candidate</option>
          <option value="confirmed">Confirmed</option><option value="declined">Declined</option>
        </select>
      </label>
      <button type="submit" :disabled="shelfLoading">Search</button>
    </form>
    <p v-if="shelfLoading" role="status">Loading lessons…</p>
    <div v-else-if="shelfError" class="card" role="alert">
      {{ shelfError }} <button type="button" class="ghost-btn" @click="loadShelf">Retry</button>
    </div>
    <template v-else-if="shelf?.items.length">
      <ul class="learning-results">
        <li v-for="lesson in shelf.items" :key="lesson.id" class="card">
          <div class="lesson-header">
            <RouterLink :to="{ query: { ...route.query, lesson_id: lesson.id } }"><strong>{{ lesson.title }}</strong></RouterLink>
            <span :class="['badge', lesson.status === 'confirmed' ? 'badge-done' : 'badge-pending']">{{ lesson.status }}</span>
          </div>
          <p>{{ lesson.trigger }}</p>
          <p class="meta">{{ lesson.source_work_item_title }} · {{ lesson.use_count }} reuse {{ lesson.use_count === 1 ? 'record' : 'records' }}</p>
        </li>
      </ul>
      <div v-if="shelf.pages > 1" class="card-actions" aria-label="Lesson pages">
        <button type="button" class="ghost-btn" :disabled="filters.page <= 1" @click="filterShelf(filters.page - 1)">Previous</button>
        <span>Page {{ filters.page }} of {{ shelf.pages }}</span>
        <button type="button" class="ghost-btn" :disabled="filters.page >= shelf.pages" @click="filterShelf(filters.page + 1)">Next</button>
      </div>
    </template>
    <p v-else class="meta">No saved lessons match this view.</p>
  </section>
</template>

<style scoped>
.learning-heading, .lesson-header { display: flex; align-items: center; flex-wrap: wrap; gap: .75rem; }
.learning-heading { justify-content: space-between; }
.learning-heading h1, .lesson-header h3 { margin: 0; }
.flex-field { flex: 1 1 180px; min-width: 0; }
.inline-form { align-items: flex-end; }
.learning-results { display: grid; gap: .6rem; padding: 0; list-style: none; }
.learning-results p, .lesson-detail p { margin: .5rem 0; }
.lesson-detail dl { margin: .75rem 0; }
.lesson-detail dt { margin-top: .6rem; font-weight: 650; }
.lesson-detail dd { margin-left: 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.lesson-detail h3:not(.lesson-header h3) { margin-top: 1rem; }
.use-list { padding-left: 1.2rem; }
.source-line strong { margin-right: .45rem; }
@media (max-width: 480px) {
  .inline-form { align-items: stretch; }
  .flex-field { flex-basis: auto; }
}
</style>

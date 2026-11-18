<script setup lang="ts">
import { reactive, computed, ref } from 'vue'
import { api, errorMessage } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import { useToast } from '@/stores/toast'
import Badge from '@/components/Badge.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { SprintStatus } from '@/types'

const toast = useToast()
const { data: projects, loading: projectsLoading, error: projectsError, run: reloadProjects } = useAsync(() => api.listProjects(true))
const { data: sprints, loading: sprintsLoading, error: sprintsError, run: reloadSprints } = useAsync(() => api.listSprints())
const { data: agent, loading: agentLoading, error: agentError, run: reloadAgent } = useAsync(() => api.agentStatus())
const projectMap = computed(() => Object.fromEntries((projects.value ?? []).map(p => [p.id, p.key])))
const busy = ref(false)
const pf = reactive({ name: '', key: '', repo: '', color: '#2563eb' })
const sf = reactive({ project_id: '', name: '', start_date: '', end_date: '', goal: '' })

async function mutate(action: () => Promise<unknown>, reload: () => Promise<void>, message: string) {
  if (busy.value) return
  busy.value = true
  try {
    await action()
    await reload()
    toast.success(message)
  } catch (error) {
    toast.error(errorMessage(error))
  } finally {
    busy.value = false
  }
}

function addProject() {
  if (!pf.name.trim() || !pf.key.trim()) return
  void mutate(async () => {
    await api.createProject({ name: pf.name.trim(), key: pf.key.trim(), repo: pf.repo.trim() || null, color: pf.color })
    Object.assign(pf, { name: '', key: '', repo: '' })
  }, reloadProjects, 'Project created')
}

function archive(id: number, value: boolean) {
  void mutate(() => api.updateProject(id, { is_archived: value }), reloadProjects, value ? 'Project archived' : 'Project restored')
}

function delProject(id: number) {
  if (!window.confirm('Delete project? Linked events will be unlinked and its sprints will be removed.')) return
  void mutate(() => api.deleteProject(id), async () => {
    await Promise.all([reloadProjects(), reloadSprints()])
  }, 'Project deleted')
}

function addSprint() {
  if (!sf.project_id || !sf.name.trim() || !sf.start_date || !sf.end_date) return
  void mutate(async () => {
    await api.createSprint({
      project_id: Number(sf.project_id), name: sf.name.trim(), start_date: sf.start_date,
      end_date: sf.end_date, goal: sf.goal.trim() || null,
    })
    Object.assign(sf, { name: '', start_date: '', end_date: '', goal: '' })
  }, reloadSprints, 'Sprint created')
}

function setSprint(id: number, status: SprintStatus) {
  void mutate(() => api.updateSprint(id, { status }), reloadSprints, 'Sprint updated')
}

function delSprint(id: number) {
  if (!window.confirm('Delete sprint?')) return
  void mutate(() => api.deleteSprint(id), reloadSprints, 'Sprint deleted')
}
</script>

<template>
  <h1>Settings</h1>

  <h2>Built-in AI</h2>
  <section class="card" aria-label="CodeBuddy configuration">
    <p v-if="agentLoading" class="meta">Checking CodeBuddy configuration…</p>
    <p v-else-if="agentError" role="alert">{{ agentError }} <button class="ghost-btn" @click="reloadAgent">Retry</button></p>
    <template v-else-if="agent">
      <div class="card-header"><Badge :variant="agent.enabled ? 'ok' : 'type'" :label="agent.enabled ? 'Enabled' : 'Disabled'" />
        <strong>CodeBuddy</strong>
      </div>
      <p>Drafting sends the selected note, AI search sends the question, and narrative generation sends records from the selected period.</p>
      <p class="meta">{{ agent.cli_available ? 'CLI found' : 'CLI missing' }} · {{ agent.key_configured ? 'API key configured' : 'API key missing' }} · {{ agent.model }}</p>
    </template>
  </section>

  <h2>Projects</h2>
  <p v-if="projectsLoading" class="loading">Loading projects…</p>
  <p v-else-if="projectsError" role="alert">{{ projectsError }} <button class="ghost-btn" @click="reloadProjects">Retry projects</button></p>
  <div v-else-if="projects?.length" class="card-list">
    <div v-for="p in projects" :key="p.id" class="card entity-card">
      <div class="entity-card-main">
        <div class="entity-card-head">
          <span class="color-dot" :style="{ background: p.color }"></span>
          <span class="entity-card-title">{{ p.name }}</span>
          <Badge variant="type" :label="p.key" />
          <Badge v-if="p.is_archived" variant="warn" label="archived" />
        </div>
        <div class="entity-card-sub">{{ p.repo || p.description || 'No repository linked' }}</div>
      </div>
      <div class="entity-card-actions">
        <button class="ghost-btn" :disabled="busy" @click="archive(p.id, !p.is_archived)">{{ p.is_archived ? 'Unarchive' : 'Archive' }}</button>
        <button class="danger" :disabled="busy" @click="delProject(p.id)">Delete</button>
      </div>
    </div>
  </div>
  <EmptyState v-else message="No projects yet. Create one below." />

  <form class="form-card" style="margin-top:14px" @submit.prevent="addProject">
    <div class="form-card-title">New project</div>
    <div class="form-grid-3">
      <label class="field"><span class="field-label">Name</span><input v-model="pf.name" type="text" placeholder="Project name" required /></label>
      <label class="field"><span class="field-label">Key</span><input v-model="pf.key" type="text" placeholder="WL" required /></label>
      <label class="field"><span class="field-label">Repository</span><input v-model="pf.repo" type="text" placeholder="owner/repo (optional)" /></label>
    </div>
    <div class="form-actions" style="justify-content:space-between">
      <label class="field color-field"><span class="field-label">Color</span><input v-model="pf.color" type="color" /></label>
      <button type="submit" :disabled="busy">Add project</button>
    </div>
  </form>

  <h2>Sprints</h2>
  <p v-if="sprintsLoading" class="loading">Loading sprints…</p>
  <p v-else-if="sprintsError" role="alert">{{ sprintsError }} <button class="ghost-btn" @click="reloadSprints">Retry sprints</button></p>
  <div v-else-if="sprints?.length" class="card-list">
    <div v-for="s in sprints" :key="s.id" class="card entity-card">
      <div class="entity-card-main">
        <div class="entity-card-head">
          <Badge :variant="s.status" :label="s.status" />
          <span class="entity-card-title">{{ s.name }}</span>
          <Badge variant="type" :label="projectMap[s.project_id] || '?'" />
        </div>
        <div class="entity-card-sub">{{ s.start_date }} → {{ s.end_date }}<template v-if="s.goal"> · {{ s.goal }}</template></div>
      </div>
      <div class="entity-card-actions">
        <button :disabled="busy" v-if="s.status === 'planned'" @click="setSprint(s.id, 'active')">Activate</button>
        <button :disabled="busy" v-if="s.status === 'active'" @click="setSprint(s.id, 'completed')">Complete</button>
        <button class="danger" :disabled="busy" @click="delSprint(s.id)">Delete</button>
      </div>
    </div>
  </div>
  <EmptyState v-else message="No sprints yet. Create one below." />

  <form class="form-card" style="margin-top:14px" @submit.prevent="addSprint">
    <div class="form-card-title">New sprint</div>
    <div class="form-grid-2">
      <label class="field"><span class="field-label">Project</span>
        <select v-model="sf.project_id" required>
          <option value="" disabled>Select project</option>
          <option v-for="p in (projects ?? []).filter(x => !x.is_archived)" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </label>
      <label class="field"><span class="field-label">Sprint name</span><input v-model="sf.name" type="text" placeholder="Sprint 1" required /></label>
      <label class="field"><span class="field-label">Start date</span><input v-model="sf.start_date" type="date" required /></label>
      <label class="field"><span class="field-label">End date</span><input v-model="sf.end_date" type="date" required /></label>
      <label class="field form-span"><span class="field-label">Goal</span><input v-model="sf.goal" type="text" placeholder="What should this sprint achieve? (optional)" /></label>
    </div>
    <div class="form-actions"><button type="submit" :disabled="busy">Add sprint</button></div>
  </form>
</template>

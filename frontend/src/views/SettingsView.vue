<script setup lang="ts">
import { reactive, computed } from 'vue'
import { api } from '@/api/client'
import { useAsync } from '@/composables/useAsync'
import { useToast } from '@/stores/toast'
import Badge from '@/components/Badge.vue'
import EmptyState from '@/components/EmptyState.vue'

const toast = useToast()
const { data: projects, run: reloadP } = useAsync(() => api.listProjects(true))
const { data: sprints, run: reloadS } = useAsync(() => api.listSprints())
const projectMap = computed(() => Object.fromEntries((projects.value ?? []).map(p => [p.id, p.key])))

const pf = reactive({ name: '', key: '', repo: '', color: '#2563eb' })
async function addProject() {
  if (!pf.name.trim() || !pf.key.trim()) return
  await api.createProject({ name: pf.name, key: pf.key, repo: pf.repo || null, color: pf.color })
  Object.assign(pf, { name: '', key: '', repo: '' })
  toast.success('Project created'); reloadP()
}
async function archive(id: number, val: boolean) { await api.updateProject(id, { is_archived: val }); reloadP() }
async function delProject(id: number) { if (confirm('Delete project? Linked events will be unlinked.')) { await api.deleteProject(id); reloadP() } }

const sf = reactive({ project_id: '', name: '', start_date: '', end_date: '', goal: '' })
async function addSprint() {
  if (!sf.project_id || !sf.name.trim() || !sf.start_date || !sf.end_date) return
  await api.createSprint({ project_id: Number(sf.project_id), name: sf.name, start_date: sf.start_date, end_date: sf.end_date, goal: sf.goal || null })
  Object.assign(sf, { name: '', start_date: '', end_date: '', goal: '' })
  toast.success('Sprint created'); reloadS()
}
async function setSprint(id: number, status: string) { await api.updateSprint(id, { status: status as any }); reloadS() }
async function delSprint(id: number) { if (confirm('Delete sprint?')) { await api.deleteSprint(id); reloadS() } }
</script>

<template>
  <h1>Settings</h1>

  <h2>Projects</h2>
  <div v-if="projects && projects.length" class="card-list">
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
        <button class="ghost-btn" @click="archive(p.id, !p.is_archived)">{{ p.is_archived ? 'Unarchive' : 'Archive' }}</button>
        <button class="danger" @click="delProject(p.id)">Delete</button>
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
      <button type="submit">Add project</button>
    </div>
  </form>

  <h2>Sprints</h2>
  <div v-if="sprints && sprints.length" class="card-list">
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
        <button v-if="s.status === 'planned'" @click="setSprint(s.id, 'active')">Activate</button>
        <button v-if="s.status === 'active'" @click="setSprint(s.id, 'completed')">Complete</button>
        <button class="danger" @click="delSprint(s.id)">Delete</button>
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
    <div class="form-actions"><button type="submit">Add sprint</button></div>
  </form>
</template>
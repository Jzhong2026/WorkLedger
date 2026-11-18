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
    <div v-for="p in projects" :key="p.id" class="card" :style="{ borderLeft: `3px solid ${p.color}` }">
      <div class="card-header">
        <Badge variant="type" :label="p.key" />
        <strong>{{ p.name }}</strong>
        <Badge v-if="p.is_archived" variant="warn" label="archived" />
      </div>
      <div class="card-meta">
        <span v-if="p.repo">{{ p.repo }}</span>
        <span v-if="p.description">{{ p.description }}</span>
      </div>
      <div class="card-actions">
        <button @click="archive(p.id, !p.is_archived)">{{ p.is_archived ? 'Unarchive' : 'Archive' }}</button>
        <button class="danger" @click="delProject(p.id)">Delete</button>
      </div>
    </div>
  </div>
  <EmptyState v-else message="No projects yet." />
  <form class="inline-form" style="margin-top:1rem" @submit.prevent="addProject">
    <input v-model="pf.name" type="text" placeholder="Project name" required />
    <input v-model="pf.key" type="text" placeholder="KEY" required style="width:90px;flex:none" />
    <input v-model="pf.repo" type="text" placeholder="repo (optional)" />
    <input v-model="pf.color" type="color" style="width:46px;flex:none;padding:3px" />
    <button type="submit">Add</button>
  </form>

  <h2>Sprints</h2>
  <div v-if="sprints && sprints.length" class="card-list">
    <div v-for="s in sprints" :key="s.id" class="card">
      <div class="card-header">
        <Badge :variant="s.status" :label="s.status" />
        <strong>{{ s.name }}</strong>
        <Badge variant="type" :label="projectMap[s.project_id] || '?'" />
      </div>
      <div class="card-meta">
        <span>{{ s.start_date }} → {{ s.end_date }}</span>
        <span v-if="s.goal">Goal: {{ s.goal }}</span>
      </div>
      <div class="card-actions">
        <button v-if="s.status === 'planned'" @click="setSprint(s.id, 'active')">Activate</button>
        <button v-if="s.status === 'active'" @click="setSprint(s.id, 'completed')">Complete</button>
        <button class="danger" @click="delSprint(s.id)">Delete</button>
      </div>
    </div>
  </div>
  <EmptyState v-else message="No sprints yet." />
  <form id="add-sprint" style="margin-top:1rem" @submit.prevent="addSprint">
    <select v-model="sf.project_id" required>
      <option value="">Project</option>
      <option v-for="p in (projects ?? []).filter(x => !x.is_archived)" :key="p.id" :value="p.id">{{ p.name }}</option>
    </select>
    <input v-model="sf.name" type="text" placeholder="Sprint name" required />
    <input v-model="sf.start_date" type="date" required />
    <input v-model="sf.end_date" type="date" required />
    <input v-model="sf.goal" type="text" placeholder="Goal (optional)" />
    <button type="submit">Add Sprint</button>
  </form>
</template>
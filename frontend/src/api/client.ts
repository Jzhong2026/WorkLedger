import type {
  WorkEvent, Todo, Accomplishment, Case, Project, Sprint,
  InboxNote, EventDraft, Paginated, Insights, Retrospective,
} from '@/types'

const BASE = '/api'

export class ApiError extends Error {
  constructor(message: string, public status: number, public retryable = false) {
    super(message)
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = { method, headers: { 'Content-Type': 'application/json' } }
  if (body !== undefined) opts.body = JSON.stringify(body)
  const res = await fetch(BASE + path, opts)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(err.detail || err.error || 'Request failed', res.status, err.retryable)
  }
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('Content-Type') || ''
  if (ct.includes('text/markdown') || ct.includes('text/plain')) return (await res.text()) as T
  return res.json() as Promise<T>
}

const get = <T>(p: string) => request<T>('GET', p)
const post = <T>(p: string, b?: unknown) => request<T>('POST', p, b)
const patch = <T>(p: string, b: unknown) => request<T>('PATCH', p, b)
const del = <T>(p: string) => request<T>('DELETE', p)

function qs(params: Record<string, unknown>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export const api = {
  // Events
  searchEvents: (p: Record<string, unknown>) => get<Paginated<WorkEvent>>('/events' + qs(p)),
  searchFts: (p: Record<string, unknown>) => get<Paginated<WorkEvent>>('/search/fts' + qs(p)),
  searchSemantic: (question: string) => post<{ expansion: { keywords: string }; items: WorkEvent[]; total: number }>('/search/semantic', { question }),
  getEvent: (id: number) => get<WorkEvent>(`/events/${id}`),
  getChildren: (id: number) => get<WorkEvent[]>(`/events/${id}/children`),
  createEvent: (b: Partial<WorkEvent>) => post<WorkEvent>('/events', b),
  updateEvent: (id: number, b: Partial<WorkEvent>) => patch<WorkEvent>(`/events/${id}`, b),
  prTimeline: (repo: string, pr: number) => get<WorkEvent[]>(`/prs/timeline${qs({ repo, pr_number: pr })}`),
  listRepos: () => get<string[]>('/repos'),
  snapshotEvent: (id: number) => post<{ snapshot_status: string; chars: number }>(`/events/${id}/snapshot`),

  // Todos
  listTodos: (p: Record<string, unknown> = {}) => get<Paginated<Todo>>('/todos' + qs(p)),
  todayTodos: () => get<Todo[]>('/todos/today'),
  createTodo: (b: Partial<Todo>) => post<Todo>('/todos', b),
  updateTodo: (id: number, b: Partial<Todo>) => patch<Todo>(`/todos/${id}`, b),
  deleteTodo: (id: number) => del<void>(`/todos/${id}`),

  // Accomplishments & cases
  listAccomplishments: (p: Record<string, unknown> = {}) => get<Paginated<Accomplishment>>('/accomplishments' + qs(p)),
  createAccomplishment: (b: Partial<Accomplishment>) => post<Accomplishment>('/accomplishments', b),
  listCases: (p: Record<string, unknown> = {}) => get<Paginated<Case>>('/cases' + qs(p)),
  createCase: (b: Partial<Case>) => post<Case>('/cases', b),
  retrospective: (period: string) => get<Retrospective>('/retrospective' + qs({ period })),

  // Export
  exportMarkdown: (period: string) => get<string>('/export' + qs({ period })),
  exportNarrative: (period: string) => post<{ narrative: string }>('/export/narrative', { period }),

  // Inbox
  listInbox: (status?: string) => get<InboxNote[]>('/inbox' + qs({ status })),
  captureNote: (raw_text: string) => post<InboxNote>('/inbox', { raw_text }),
  structureNote: (id: number) => post<{ drafts: EventDraft[] }>(`/inbox/${id}/structure`),
  discardNote: (id: number) => post<void>(`/inbox/${id}/discard`),
  listDrafts: (status = 'pending') => get<EventDraft[]>('/drafts' + qs({ status })),
  confirmDraft: (id: number) => post<{ event: WorkEvent }>(`/drafts/${id}/confirm`),
  discardDraft: (id: number) => post<void>(`/drafts/${id}/discard`),

  // Master data
  listProjects: (includeArchived = false) => get<Project[]>('/projects' + qs({ include_archived: includeArchived })),
  createProject: (b: Partial<Project>) => post<Project>('/projects', b),
  updateProject: (id: number, b: Partial<Project>) => patch<Project>(`/projects/${id}`, b),
  deleteProject: (id: number) => del<void>(`/projects/${id}`),
  listSprints: (p: Record<string, unknown> = {}) => get<Sprint[]>('/sprints' + qs(p)),
  createSprint: (b: Partial<Sprint>) => post<Sprint>('/sprints', b),
  updateSprint: (id: number, b: Partial<Sprint>) => patch<Sprint>(`/sprints/${id}`, b),
  deleteSprint: (id: number) => del<void>(`/sprints/${id}`),

  // Insights & agent
  insights: () => get<Insights>('/insights'),
  agentStatus: () => get<{ enabled: boolean; model: string; cli_available: boolean; key_configured: boolean }>('/agent/status'),
}
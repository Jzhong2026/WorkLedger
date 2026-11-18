import type {
  WorkEvent, Todo, Accomplishment, Case, Project, Sprint,
  InboxNote, EventDraft, Paginated, Insights, Retrospective,
  AccomplishmentInput, CaseInput, DraftEdit, EventEdit, Narrative,
  ProjectCreate, ProjectEdit, SnapshotStatus, SprintCreate, SprintEdit,
  EventSearchFilters, ExpandedSearch, InsightsFilters, SearchExpansion, TodaySummary,
  TodoCreate, TodoListFilters, TodoUpdate,
} from '@/types'

const BASE = '/api'

export class ApiError extends Error {
  constructor(message: string, public status: number, public retryable = false) {
    super(message)
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function responseMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    const messages = detail.map(item => {
      if (typeof item?.msg !== 'string') return ''
      const field = Array.isArray(item.loc) ? item.loc.slice(1).join('.') : ''
      return field ? `${field}: ${item.msg}` : item.msg
    }).filter(Boolean)
    if (messages.length) return messages.join(' · ')
  }
  return fallback || 'Request failed. Try again.'
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = { method, headers: { 'Content-Type': 'application/json' } }
  if (body !== undefined) opts.body = JSON.stringify(body)
  let res: Response
  try {
    res = await fetch(BASE + path, opts)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError('Cannot reach WorkLedger. Check that the server is running and retry.', 0, true)
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(responseMessage(err.detail ?? err.error, res.statusText), res.status, err.retryable)
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
    if (v !== null && v !== undefined && (v !== '' || k === 'repo')) sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

export const api = {
  // Events
  searchEvents: (filters: EventSearchFilters) => get<Paginated<WorkEvent>>('/events' + qs({ ...filters })),
  searchFts: (p: Record<string, unknown>) => get<Paginated<WorkEvent>>('/search/fts' + qs(p)),
  searchSemantic: (question: string) => post<ExpandedSearch>('/search/semantic', { question }),
  searchExpanded: (expansion: SearchExpansion, page: number) => post<ExpandedSearch>('/search/expanded', { expansion, page }),
  getEvent: (id: number) => get<WorkEvent>(`/events/${id}`),
  getChildren: (id: number) => get<WorkEvent[]>(`/events/${id}/children`),
  createEvent: (b: Partial<WorkEvent>) => post<WorkEvent>('/events', b),
  updateEvent: (id: number, b: EventEdit) => patch<WorkEvent>(`/events/${id}`, b),
  prTimeline: (repo: string, pr: number) => get<WorkEvent[]>(`/prs/timeline${qs({ repo, pr_number: pr })}`),
  listRepos: () => get<string[]>('/repos'),
  snapshotEvent: (id: number) => post<{ snapshot_status: SnapshotStatus; chars: number; error: string | null }>(`/events/${id}/snapshot`),

  // Todos
  listTodos: (filters: TodoListFilters = {}) => get<Paginated<Todo> & { today: string }>('/todos' + qs({ ...filters })),
  todayTodos: () => get<Todo[]>('/todos/today'),
  todaySummary: () => get<TodaySummary>('/todos/today-summary'),
  createTodo: (b: TodoCreate) => post<Todo>('/todos', b),
  updateTodo: (id: number, b: TodoUpdate) => patch<Todo>(`/todos/${id}`, b),
  deleteTodo: (id: number) => del<void>(`/todos/${id}`),

  // Accomplishments & cases
  listAccomplishments: (p: Record<string, unknown> = {}) => get<Paginated<Accomplishment>>('/accomplishments' + qs(p)),
  createAccomplishment: (b: AccomplishmentInput) => post<Accomplishment>('/accomplishments', b),
  listCases: (p: Record<string, unknown> = {}) => get<Paginated<Case>>('/cases' + qs(p)),
  createCase: (b: CaseInput) => post<Case>('/cases', b),
  retrospective: (period: string, page: number, page_size: number) =>
    get<Retrospective>('/retrospective' + qs({ period, page, page_size })),

  // Export
  exportMarkdown: (period: string) => get<string>('/export' + qs({ period })),
  exportNarrative: (period: string) => post<Narrative>('/export/narrative', { period }),

  // Inbox
  listInbox: (status?: string) => get<InboxNote[]>('/inbox' + qs({ status })),
  captureNote: (raw_text: string) => post<InboxNote>('/inbox', { raw_text }),
  structureNote: (id: number) => post<{ drafts: EventDraft[] }>(`/inbox/${id}/structure`),
  discardNote: (id: number) => post<void>(`/inbox/${id}/discard`),
  listDrafts: (status = 'pending') => get<EventDraft[]>('/drafts' + qs({ status })),
  updateDraft: (id: number, data: DraftEdit) => patch<EventDraft>(`/drafts/${id}`, data),
  confirmDraft: (id: number, data: DraftEdit) => post<{ event: WorkEvent }>(`/drafts/${id}/confirm`, data),
  commitNote: (id: number, data: DraftEdit) => post<{ event: WorkEvent }>(`/inbox/${id}/commit`, data),
  discardDraft: (id: number) => post<void>(`/drafts/${id}/discard`),

  // Master data
  listProjects: (includeArchived = false) => get<Project[]>('/projects' + qs({ include_archived: includeArchived })),
  createProject: (b: ProjectCreate) => post<Project>('/projects', b),
  updateProject: (id: number, b: ProjectEdit) => patch<Project>(`/projects/${id}`, b),
  deleteProject: (id: number) => del<void>(`/projects/${id}`),
  listSprints: (p: Record<string, unknown> = {}) => get<Sprint[]>('/sprints' + qs(p)),
  createSprint: (b: SprintCreate) => post<Sprint>('/sprints', b),
  updateSprint: (id: number, b: SprintEdit) => patch<Sprint>(`/sprints/${id}`, b),
  deleteSprint: (id: number) => del<void>(`/sprints/${id}`),

  // Insights & agent
  insights: (filters: InsightsFilters = {}) => get<Insights>('/insights' + qs({ ...filters })),
  agentStatus: () => get<{ enabled: boolean; model: string; cli_available: boolean; key_configured: boolean }>('/agent/status'),
}

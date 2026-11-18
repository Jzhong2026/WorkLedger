export type EventType =
  | 'pr_created' | 'review_finding' | 'comment_analysis' | 'fix'
  | 'verification' | 'reply_drafted' | 'reply_published' | 'manual'

export const eventTypes: EventType[] = [
  'pr_created', 'review_finding', 'comment_analysis', 'fix',
  'verification', 'reply_drafted', 'reply_published', 'manual',
]

export type EventEdit = Partial<Pick<
  WorkEvent, 'summary' | 'detail' | 'evidence_url' | 'root_cause' |
  'root_cause_confirmed' | 'verification_result' | 'verification_done' | 'reply_status' |
  'jira_key' | 'extra_json'
>>

export type DraftEdit = EventEdit & Partial<Pick<WorkEvent,
  'event_type' | 'repo' | 'pr_number' | 'comment_id'
>> & { occurred_at?: string | null }

export type SnapshotStatus = 'captured' | 'failed' | 'inaccessible'

export type TodoStatus = 'pending' | 'waiting' | 'done'
export type SprintStatus = 'planned' | 'active' | 'completed'

export interface WorkEvent {
  id: number
  event_type: EventType
  occurred_at: string
  recorded_at: string
  repo: string | null
  pr_number: number | null
  comment_id: string | null
  jira_key: string | null
  source_key: string
  source_agent: string | null
  summary: string
  detail: string | null
  evidence_url: string | null
  root_cause: string | null
  root_cause_confirmed: boolean
  verification_result: string | null
  verification_done: boolean
  reply_status: string | null
  extra_json: string | null
  user_edited: boolean
  project_id: number | null
  sprint_id: number | null
  parent_event_id: number | null
  evidence_snapshot: string | null
  snapshot_status: SnapshotStatus | null
  snapshot_at: string | null
  snapshot_attempt_at: string | null
  snapshot_error: string | null
  snapshot_source_url: string | null
  created_at: string
  updated_at: string
}

export interface Todo {
  id: number
  title: string
  description: string | null
  status: TodoStatus
  event_id: number | null
  wait_target: string | null
  due_date: string | null
  next_followup: string | null
  completed_at: string | null
  source_key: string | null
  project_id: number | null
  sprint_id: number | null
  created_at: string
  updated_at: string
}

export interface TodoUpdate {
  title?: string
  description?: string | null
  status?: TodoStatus
  event_id?: number | null
  wait_target?: string | null
  due_date?: string | null
  next_followup?: string | null
}

export interface TodoCreate extends TodoUpdate {
  title: string
  source_key?: string
}

export interface TodaySummary {
  today: string
  counts: Record<TodoStatus, number>
  groups: Record<'overdue' | 'today' | 'unscheduled', Todo[]>
}

export interface Accomplishment {
  id: number
  title: string
  description: string | null
  occurred_at: string
  impact: string | null
  impact_evidence_url: string | null
  is_highlight: boolean
  tags: string | null
  source_key: string | null
  event_id: number | null
  user_edited: boolean
  created_at: string
  updated_at: string
}

export interface Case {
  id: number
  title: string
  phenomenon: string
  root_cause: string | null
  root_cause_confirmed: boolean
  solution: string | null
  verification: string | null
  verification_done: boolean
  occurred_at: string
  tags: string | null
  source_key: string | null
  event_id: number | null
  evidence_url: string | null
  user_edited: boolean
  created_at: string
  updated_at: string
}

export interface Project {
  id: number
  name: string
  key: string
  repo: string | null
  description: string | null
  color: string
  is_archived: boolean
  created_at: string
  updated_at: string
}

export interface Sprint {
  id: number
  project_id: number
  name: string
  goal: string | null
  start_date: string
  end_date: string
  status: SprintStatus
  created_at: string
  updated_at: string
}

export interface InboxNote {
  id: number
  raw_text: string
  status: 'raw' | 'structured' | 'committed' | 'discarded'
  created_at: string
  updated_at: string
}

export interface EventDraft {
  id: number
  note_id: number
  draft_json: string
  draft: DraftEdit & { event_type: EventType; summary: string }
  status: 'pending' | 'confirmed' | 'discarded'
  committed_event_id: number | null
  created_at: string
  updated_at: string
}

export interface Paginated<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

export interface LabelValue {
  label: string
  value: number
  filters?: Record<string, string | number>
}

export interface InsightsFilters {
  date_from?: string
  date_to?: string
  project_id?: number | string
}

export interface EventSearchFilters extends InsightsFilters {
  q?: string
  repo?: string | null
  pr_number?: number | string
  jira_key?: string
  event_type?: string
  root_cause?: string
  page?: number
  page_size?: number
}

export interface TodoListFilters extends InsightsFilters {
  status?: TodoStatus | ''
  page?: number
  page_size?: number
}

export interface SearchExpansion {
  keywords: string
  repo?: string | null
  event_type?: EventType | null
}

export interface ExpandedSearch extends Paginated<WorkEvent> {
  expansion: SearchExpansion
}

export interface Insights {
  totals: {
    events: number
    accomplishments: number
    cases: number
    todos: number
    highlights: number
    snapshots: number
  }
  by_type: LabelValue[]
  by_repo: LabelValue[]
  by_project: LabelValue[]
  by_month: LabelValue[]
  root_causes: LabelValue[]
  todo_status: LabelValue[]
  root_cause_confirmation: { confirmed: number; with_cause: number }
}

export interface Retrospective {
  period: string
  date_from: string
  date_to: string
  accomplishments: Accomplishment[]
  cases: Case[]
  events: WorkEvent[]
  totals: { accomplishments: number; cases: number; events: number }
  page: number
  page_size: number
}

export type ProjectCreate = Pick<Project, 'name' | 'key'> &
  Partial<Pick<Project, 'repo' | 'color' | 'description'>>
export type ProjectEdit = Partial<ProjectCreate & Pick<Project, 'is_archived'>>
export type SprintCreate = Pick<Sprint, 'project_id' | 'name' | 'start_date' | 'end_date'> &
  Partial<Pick<Sprint, 'status' | 'goal'>>
export type SprintEdit = Partial<Omit<SprintCreate, 'project_id'>>
export type AccomplishmentInput = Pick<Accomplishment, 'title' | 'occurred_at'> &
  Partial<Pick<Accomplishment, 'description' | 'impact' | 'impact_evidence_url' | 'is_highlight' |
  'tags' | 'source_key' | 'event_id'>>
export type CaseInput = Pick<Case, 'title' | 'occurred_at'> &
  Partial<Pick<Case, 'phenomenon' | 'root_cause' | 'root_cause_confirmed' | 'solution' |
  'verification' | 'verification_done' | 'evidence_url' | 'tags' | 'source_key' | 'event_id'>>

export interface Narrative {
  narrative: string
  coverage: { included: Retrospective['totals']; totals: Retrospective['totals'] }
}

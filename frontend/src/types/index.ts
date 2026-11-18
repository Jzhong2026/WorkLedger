export type EventType =
  | 'pr_created' | 'review_finding' | 'comment_analysis' | 'fix'
  | 'verification' | 'reply_drafted' | 'reply_published' | 'manual'

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
  snapshot_status: string | null
  snapshot_at: string | null
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
  draft: Partial<WorkEvent> & { event_type: EventType; summary: string }
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
}
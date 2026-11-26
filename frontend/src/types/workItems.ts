import type { Paginated, Todo, TodoCreate, WorkEvent } from '@/types'
import type { LessonRecommendation } from '@/types/learning'

export const workStages = [
  { value: 'active', label: 'Active', badge: 'pending' },
  { value: 'waiting', label: 'Waiting', badge: 'waiting' },
  { value: 'verification', label: 'Verification', badge: 'review_finding' },
  { value: 'done', label: 'Done', badge: 'done' },
] as const

export type WorkStage = typeof workStages[number]['value']

export interface WorkItemState {
  stage: WorkStage
  owner: string | null
  last_verified_result: string | null
  blocker: string | null
  next_step: string | null
  needs_decision: boolean
  followup_date: string | null
}

export interface WorkItem extends WorkItemState {
  id: number
  title: string
  goal: string | null
  project_id: number | null
  jira_key: string | null
  source_event_id: number | null
  source_key?: string | null
  linked_followup_date: string | null
  version: number
  created_at: string
  updated_at: string
}

export interface WorkItemCreate extends Partial<WorkItemState> {
  title: string
  goal?: string | null
  project_id?: number | null
  jira_key?: string | null
  source_event_id?: number | null
  source_key?: string
}

export interface WorkHandoff extends Partial<WorkItemState> {
  expected_version: number
  summary: string
  source_key?: string
  event_ids?: number[]
  todo_ids?: number[]
  todo?: Pick<TodoCreate, 'title' | 'description' | 'due_date' | 'next_followup'>
}

export interface WorkHistory extends WorkItemState {
  id: number
  item_id: number
  version: number
  summary: string
  actor: string | null
  previous_stage: WorkStage | null
  event_id: number | null
  todo_id: number | null
  linked_event_ids: number[]
  linked_todo_ids: number[]
  source_key?: string | null
  created_at: string
}

export interface WorkItemContext {
  item: WorkItem
  events: WorkEvent[]
  todos: Todo[]
  history: WorkHistory[]
  source_event: WorkEvent | null
  parent_event: WorkEvent | null
  child_events: WorkEvent[]
  related_lessons: LessonRecommendation[]
  related_lessons_error: string | null
}

export interface WorkItemFilters {
  project_id?: number
  jira_key?: string
  stage?: WorkStage
  open_only?: boolean
  page?: number
  page_size?: number
}

export interface WorkItemPage extends Paginated<WorkItem> {
  today: string
}

export interface WorkBriefing {
  text: string
  sources: Array<{ item_id: number; title: string }>
  coverage: { included: number; total: number }
}

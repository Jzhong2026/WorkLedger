export type LessonStatus = 'candidate' | 'confirmed' | 'declined'
export type LessonKind = 'skill' | 'process'
export type LessonOutcome = 'applied' | 'helped' | 'did_not_help'

export interface LessonFields {
  kind: LessonKind
  title: string
  trigger: string
  first_step: string
  limits: string | null
  tags: string[]
  source_event_id: number | null
  evidence_url: string | null
}

export interface LessonCreate extends LessonFields {
  source_work_item_id: number
}

export interface Lesson extends LessonCreate {
  id: number
  status: LessonStatus
  origin: 'manual' | 'codebuddy'
  source_work_item_title: string
  source_project_id: number | null
  source_project_name: string | null
  source_event_summary: string | null
  source_event_url: string | null
  evidence_url_override: string | null
  reviewed_at: string | null
  use_count: number
  created_at: string
  updated_at: string
}

export interface LessonUseInput {
  work_item_id: number
  outcome: LessonOutcome
  detail: string | null
}

export interface LessonUse extends LessonUseInput {
  lesson_id: number
  work_item_title: string
  created_at: string
  updated_at: string
}

export interface LessonDetail extends Lesson {
  uses: LessonUse[]
}

export interface LessonRecommendation extends Lesson {
  reasons: string[]
}

import { get, patch, post, qs } from './client'
import type { Paginated } from '@/types'
import type {
  Lesson, LessonCreate, LessonDetail, LessonFields, LessonRecommendation, LessonStatus, LessonUse, LessonUseInput,
} from '@/types/learning'

export const learningApi = {
  list: (filters: { q?: string; status?: LessonStatus; page?: number } = {}) =>
    get<Paginated<Lesson>>('/lessons' + qs(filters)),
  recall: (q: string, projectId?: number | null, limit = 5, workItemId?: number | null) =>
    get<LessonRecommendation[]>('/lessons/recall' + qs({ q, project_id: projectId, limit, work_item_id: workItemId })),
  get: (id: number) => get<LessonDetail>(`/lessons/${id}`),
  create: (body: LessonCreate) => post<LessonDetail>('/lessons', body),
  update: (id: number, body: Partial<LessonFields>) => patch<LessonDetail>(`/lessons/${id}`, body),
  review: (id: number, status: 'confirmed' | 'declined') =>
    post<LessonDetail>(`/lessons/${id}/review`, { status }),
  recordUse: (id: number, body: LessonUseInput) => post<LessonUse>(`/lessons/${id}/uses`, body),
  draft: (workItem: number, eventId: number) =>
    post<LessonDetail>('/lessons/draft', { work_item_id: workItem, source_event_id: eventId }),
}

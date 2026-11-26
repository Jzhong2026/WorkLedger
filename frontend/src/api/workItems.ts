import { get, post, qs } from './client'
import type { Paginated, WorkEvent } from '@/types'
import type {
  WorkBriefing, WorkHandoff, WorkItem, WorkItemContext, WorkItemCreate, WorkItemFilters, WorkItemPage,
} from '@/types/workItems'

function list(filters: WorkItemFilters = {}) {
  return get<WorkItemPage>('/work-items' + qs({ ...filters }))
}

async function openItems() {
  const filters = { open_only: true, page_size: 100 }
  const first = await list(filters)
  const items = first.items.slice()
  let pageCount = first.pages
  for (let page = 2; page <= pageCount; page++) {
    const batch = await list({ ...filters, page })
    items.push(...batch.items)
    pageCount = Math.min(pageCount, batch.pages)
  }
  return { today: first.today, items }
}

export const workItemsApi = {
  list,
  openItems,
  create: (data: WorkItemCreate) => post<WorkItem>('/work-items', data),
  context: (id: number) => get<WorkItemContext>(`/work-items/${id}`),
  handoff: (id: number, data: WorkHandoff) => post<WorkItemContext>(`/work-items/${id}/handoffs`, data),
  discover: (filters: Pick<WorkItemFilters, 'project_id' | 'jira_key' | 'page' | 'page_size'>) =>
    get<Paginated<WorkEvent>>('/work-items/discover' + qs({ ...filters })),
  briefing: (data: { project_id?: number; question?: string }) =>
    post<WorkBriefing>('/work-review/briefing', data),
}

import type { WorkEvent } from '@/types'

const JIRA_VARIANT: Record<string, string> = {
  Story: 'story',
  Bug: 'bug',
  Task: 'task',
  'Sprint Task': 'task',
  Epic: 'epic',
  Subtask: 'task',
  'Sub-task': 'task',
  '故事': 'story',
  '缺陷': 'bug',
  '任务': 'task',
  '史诗': 'epic',
  '子任务': 'task',
}

export function displayType(event: WorkEvent): { label: string; variant: string } {
  if (event.source_agent === 'jira-import' && event.extra_json) {
    try {
      const extra = JSON.parse(event.extra_json)
      if (extra.issuetype) {
        return { label: extra.issuetype, variant: JIRA_VARIANT[extra.issuetype] || 'type' }
      }
    } catch { /* fall through */ }
  }
  return { label: event.event_type, variant: event.event_type }
}

export function jiraStatus(event: WorkEvent): string | null {
  if (event.source_agent === 'jira-import' && event.extra_json) {
    try {
      return JSON.parse(event.extra_json).status || null
    } catch { /* ignore */ }
  }
  return null
}
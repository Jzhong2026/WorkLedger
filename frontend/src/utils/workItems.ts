import { workStages, type WorkItem, type WorkItemState, type WorkStage } from '@/types/workItems'

export function stageInfo(value: WorkStage) {
  return workStages.find(stage => stage.value === value) ?? workStages[0]
}

export function workTimestamp(value: string) {
  return new Date(value.includes('T') ? value : value.replace(' ', 'T') + 'Z')
}

export function displayWorkTimestamp(value: string) {
  const date = workTimestamp(value)
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(date)
}

export function isStale(item: WorkItem) {
  const week = 7 * 24 * 60 * 60 * 1_000
  return item.stage !== 'done' && Date.now() - workTimestamp(item.updated_at).getTime() >= week
}

export function followupDate(item: WorkItem) {
  const { followup_date, linked_followup_date } = item
  if (followup_date && linked_followup_date) {
    return followup_date <= linked_followup_date ? followup_date : linked_followup_date
  }
  return followup_date || linked_followup_date
}

export function todayWorkGroup(item: WorkItem, today: string) {
  if (item.needs_decision) return 'decision'
  const due = followupDate(item)
  if (due && due <= today) return 'followup'
  return item.stage === 'waiting' ? 'waiting' : 'active'
}

export function currentWorkState(item?: WorkItem): WorkItemState {
  return {
    stage: item?.stage ?? 'active',
    owner: item?.owner ?? null,
    last_verified_result: item?.last_verified_result ?? null,
    blocker: item?.blocker ?? null,
    next_step: item?.next_step ?? null,
    needs_decision: item?.needs_decision ?? false,
    followup_date: item?.followup_date ?? null,
  }
}

export function normalizedWorkState(state: WorkItemState): WorkItemState {
  const text = (value: string | null) => value?.trim() || null
  return {
    stage: state.stage,
    owner: text(state.owner),
    last_verified_result: text(state.last_verified_result),
    blocker: text(state.blocker),
    next_step: text(state.next_step),
    needs_decision: state.needs_decision,
    followup_date: state.followup_date || null,
  }
}

export function submissionSourceKey(prefix: string) {
  let previous = ''
  let key = ''
  return (data: unknown) => {
    const payload = JSON.stringify(data)
    if (payload !== previous) {
      key = `web:${prefix}:${crypto.randomUUID()}`
      previous = payload
    }
    return key
  }
}

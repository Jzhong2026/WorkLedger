import { ref } from 'vue'
import { api } from '@/api/client'
import { useToast } from '@/stores/toast'
import type { TodoCreate } from '@/types'

export function useTodoActions(reload: () => Promise<void>) {
  const toast = useToast()
  const busy = ref(false)

  async function mutate(action: () => Promise<unknown>, message: string) {
    if (busy.value) return false

    busy.value = true
    try {
      await action()
      toast.success(message)
      await reload()
      return true
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not update the to-do.')
      return false
    } finally {
      busy.value = false
    }
  }

  const add = (todo: TodoCreate) => mutate(() => api.createTodo(todo), 'To-do added')
  const complete = (id: number) => mutate(() => api.updateTodo(id, { status: 'done' }), 'To-do completed')
  const reopen = (id: number) => mutate(() => api.updateTodo(id, { status: 'pending' }), 'To-do reopened')

  function wait(id: number, target: string, date: string | null) {
    return mutate(
      () => api.updateTodo(id, { status: 'waiting', wait_target: target || null, next_followup: date }),
      'Waiting details saved',
    )
  }

  function remove(id: number) {
    if (confirm('Delete this to-do?')) {
      return mutate(() => api.deleteTodo(id), 'To-do deleted')
    }
  }

  return { busy, add, complete, reopen, wait, remove }
}

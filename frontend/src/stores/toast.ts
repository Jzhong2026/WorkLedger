import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Toast {
  id: number
  message: string
  kind: 'success' | 'error'
}

export const useToast = defineStore('toast', () => {
  const toasts = ref<Toast[]>([])
  let nextId = 1

  function push(message: string, kind: 'success' | 'error' = 'success') {
    const id = nextId++
    toasts.value.push({ id, message, kind })
    setTimeout(() => dismiss(id), 4000)
  }
  function dismiss(id: number) {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }
  const success = (m: string) => push(m, 'success')
  const error = (m: string) => push(m, 'error')

  return { toasts, push, dismiss, success, error }
})
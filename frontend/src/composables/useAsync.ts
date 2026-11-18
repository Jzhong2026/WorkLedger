import { getCurrentScope, onScopeDispose, ref, type Ref } from 'vue'
import { ApiError } from '@/api/client'
import { useToast } from '@/stores/toast'

export function useAsync<T>(fn: () => Promise<T>, immediate = true) {
  const data = ref<T | null>(null) as Ref<T | null>
  const loading = ref(false)
  const error = ref<string | null>(null)
  const toast = useToast()
  let request = 0

  async function run() {
    const current = ++request
    loading.value = true
    error.value = null
    try {
      const result = await fn()
      if (current === request) data.value = result
    } catch (e) {
      if (current !== request) return
      error.value = e instanceof ApiError ? e.message : String(e)
      toast.error(error.value)
    } finally {
      if (current === request) loading.value = false
    }
  }

  if (getCurrentScope()) {
    onScopeDispose(() => { request++ })
  }
  if (immediate) run()
  return { data, loading, error, run }
}

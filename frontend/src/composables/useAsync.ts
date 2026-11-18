import { ref, type Ref } from 'vue'
import { ApiError } from '@/api/client'
import { useToast } from '@/stores/toast'

export function useAsync<T>(fn: () => Promise<T>, immediate = true) {
  const data = ref<T | null>(null) as Ref<T | null>
  const loading = ref(false)
  const error = ref<string | null>(null)
  const toast = useToast()

  async function run() {
    loading.value = true
    error.value = null
    try {
      data.value = await fn()
    } catch (e) {
      error.value = e instanceof ApiError ? e.message : String(e)
      toast.error(error.value)
    } finally {
      loading.value = false
    }
  }

  if (immediate) run()
  return { data, loading, error, run }
}
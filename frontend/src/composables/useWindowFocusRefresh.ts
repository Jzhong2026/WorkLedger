import { onMounted, onUnmounted } from 'vue'

export function useWindowFocusRefresh(refresh: () => Promise<void> | void) {
  const handleFocus = () => { void refresh() }
  onMounted(() => window.addEventListener('focus', handleFocus))
  onUnmounted(() => window.removeEventListener('focus', handleFocus))
}

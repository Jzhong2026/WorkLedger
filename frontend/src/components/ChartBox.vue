<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { RouterLink, useRouter, type RouteLocationRaw } from 'vue-router'
import { Chart, registerables, type ChartConfiguration } from 'chart.js'
import type { LabelValue } from '@/types'

Chart.register(...registerables)
Chart.defaults.font.family = "'Inter', sans-serif"
Chart.defaults.color = '#475569'

const props = defineProps<{
  type: 'bar' | 'doughnut'
  rows: LabelValue[]
  horizontal?: boolean
  linkFor?: (row: LabelValue) => RouteLocationRaw | undefined
}>()
const router = useRouter()
const palette = ['#2563eb', '#7c3aed', '#0891b2', '#047857', '#d97706', '#db2777', '#991b1b', '#667085']
const canvas = ref<HTMLCanvasElement | null>(null)
const links = computed(() => props.rows.map(row => props.linkFor?.(row)))
let chart: Chart | null = null

function build() {
  chart?.destroy()
  chart = null
  if (!canvas.value) return
  const config: ChartConfiguration = {
    type: props.type,
    data: {
      labels: props.rows.map(r => r.label),
      datasets: [{
        data: props.rows.map(r => r.value),
        backgroundColor: palette,
        borderColor: '#ffffff',
        borderWidth: props.type === 'doughnut' ? 2 : 0,
        borderRadius: props.type === 'bar' ? 5 : 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: props.horizontal ? 'y' : 'x',
      onClick: (_, elements) => {
        const link = elements[0] && links.value[elements[0].index]
        if (link) void router.push(link)
      },
      onHover: (_, elements, instance) => {
        instance.canvas.style.cursor = elements[0] && links.value[elements[0].index] ? 'pointer' : ''
      },
      plugins: {
        legend: { display: false },
      },
      scales: props.type === 'bar' ? { x: { grid: { display: !props.horizontal } }, y: { grid: { display: !!props.horizontal } } } : {},
    },
  }
  chart = new Chart(canvas.value, config)
}
onMounted(build)
watch(() => props.rows, build, { deep: true, flush: 'post' })
onBeforeUnmount(() => chart?.destroy())
</script>

<template>
  <template v-if="rows.length">
    <div class="chart-wrap"><canvas ref="canvas" aria-hidden="true"></canvas></div>
    <details class="chart-values">
      <summary>View values</summary>
      <ul>
        <li v-for="(row, index) in rows" :key="index">
          <span class="chart-swatch" :style="{ backgroundColor: palette[index % palette.length] }" aria-hidden="true"></span>
          <RouterLink v-if="links[index]" :to="links[index]">{{ row.label }}</RouterLink>
          <span v-else>{{ row.label }}</span>
          <strong>{{ row.value }}</strong>
        </li>
      </ul>
    </details>
  </template>
  <p v-else class="meta">No matching records.</p>
</template>

<style scoped>
.chart-wrap { position: relative; height: 240px; }
.chart-values { font-size: .85rem; }
.chart-values summary { cursor: pointer; color: var(--text-2); }
.chart-values ul { list-style: none; margin-top: 4px; }
.chart-values li { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: baseline; gap: 8px; padding: 3px 0; }
.chart-swatch { display: inline-block; width: 8px; height: 8px; border-radius: 2px; }
.chart-values strong { font-variant-numeric: tabular-nums; }
</style>

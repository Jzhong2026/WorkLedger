<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { Chart, registerables, type ChartConfiguration } from 'chart.js'
import type { LabelValue } from '@/types'

Chart.register(...registerables)
Chart.defaults.font.family = "'Inter', sans-serif"
Chart.defaults.color = '#475569'

const props = defineProps<{ type: 'bar' | 'doughnut'; rows: LabelValue[]; horizontal?: boolean }>()
const palette = ['#2563eb', '#7c3aed', '#0891b2', '#047857', '#d97706', '#db2777', '#991b1b', '#667085']
const canvas = ref<HTMLCanvasElement | null>(null)
let chart: Chart | null = null

function build() {
  if (!canvas.value) return
  chart?.destroy()
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
      plugins: {
        legend: props.type === 'doughnut'
          ? { position: 'bottom', labels: { boxWidth: 12, padding: 10, font: { size: 11 } } }
          : { display: false },
      },
      scales: props.type === 'bar' ? { x: { grid: { display: !props.horizontal } }, y: { grid: { display: !!props.horizontal } } } : {},
    },
  }
  chart = new Chart(canvas.value, config)
}
onMounted(build)
watch(() => props.rows, build, { deep: true })
onBeforeUnmount(() => chart?.destroy())
</script>

<template>
  <div class="chart-wrap"><canvas ref="canvas"></canvas></div>
</template>

<style scoped>
.chart-wrap { position: relative; height: 240px; }
</style>
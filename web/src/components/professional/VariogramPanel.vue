<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { DirectionalVariogramBin, VariogramEvidence, VariogramModelName } from '../../api/types'

// 只渲染 API 下发的证据：经验 bin、拟合参数与候选摘要全部来自服务端，
// 前端不计算任何统计量（拟合线只是把服务端拟合参数按模型公式描点）。
const props = defineProps<{
  evidence: VariogramEvidence
}>()

const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

interface DirectionEntry {
  id: string
  azimuth_deg: number
  dip_deg: number | null
  unsupported: boolean
  bins: DirectionalVariogramBin[]
}

// 方向系列：按 direction_id 分组；点对不足（skipped）的方向只披露、不可选
const directions = computed<DirectionEntry[]>(() => {
  const skipped = new Set(props.evidence.anisotropy_candidates.skipped_direction_ids)
  const grouped = new Map<string, DirectionEntry>()
  for (const bin of props.evidence.directional.rows) {
    let entry = grouped.get(bin.direction_id)
    if (!entry) {
      entry = {
        id: bin.direction_id,
        azimuth_deg: bin.azimuth_deg,
        dip_deg: bin.dip_deg,
        unsupported: skipped.has(bin.direction_id),
        bins: [],
      }
      grouped.set(bin.direction_id, entry)
    }
    entry.bins.push(bin)
  }
  for (const entry of grouped.values()) {
    entry.bins.sort((a, b) => a.bin_index - b.bin_index)
  }
  return [...grouped.values()]
})

const selectedDirections = ref<string[]>([])

function toggleDirection(id: string) {
  const entry = directions.value.find((d) => d.id === id)
  if (!entry || entry.unsupported) return
  selectedDirections.value = selectedDirections.value.includes(id)
    ? selectedDirections.value.filter((item) => item !== id)
    : [...selectedDirections.value, id]
}

const sampling = computed(() => props.evidence.sampling)
const omniRows = computed(() => props.evidence.omnidirectional.rows)

function fmt(value: number | null): string {
  if (value === null) return '—'
  return Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(3)
}

// 与服务端 modeling.variogram.semivariance 相同的模型公式（仅用于描线）
function modelSemivariance(
  model: VariogramModelName,
  nugget: number,
  partialSill: number,
  range: number,
  h: number,
): number {
  if (model === 'spherical') {
    const r = Math.min(h / range, 1)
    return nugget + partialSill * (r < 1 ? 1.5 * r - 0.5 * r ** 3 : 1)
  }
  if (model === 'exponential') return nugget + partialSill * (1 - Math.exp(-h / range))
  return nugget + partialSill * (1 - Math.exp(-((h / range) ** 2)))
}

function binPoint(bin: { mean_distance: number | null; center_distance: number; semivariance: number | null }) {
  if (bin.semivariance === null) return null
  return [bin.mean_distance ?? bin.center_distance, bin.semivariance] as [number, number]
}

function render() {
  if (!chartEl.value) return
  if (!chart) {
    try {
      chart = echarts.init(chartEl.value, undefined, { renderer: 'svg' })
    } catch {
      return // 无图形环境（jsdom 降级）：bin 表与披露信息仍然可见
    }
  }
  const omni = omniRows.value
  const used = omni.filter((b) => b.used_for_fit)
  const excluded = omni.filter((b) => !b.used_for_fit)
  const maxX = Math.max(...omni.map((b) => b.upper_distance), 1) * 1.05

  const series: echarts.SeriesOption[] = [
    {
      type: 'scatter',
      name: '全向经验 bin（用于拟合）',
      data: used.map((b) => ({ value: binPoint(b), pairCount: b.pair_count })),
      symbolSize: 9,
      itemStyle: { color: '#38b2ac' },
    },
    {
      type: 'scatter',
      name: '全向经验 bin（排除）',
      data: excluded.map((b) => ({
        value: binPoint(b),
        pairCount: b.pair_count,
        exclusionReason: b.exclusion_reason,
      })),
      symbol: 'triangle',
      symbolSize: 9,
      itemStyle: { color: '#8fa1b3', opacity: 0.65 },
    },
  ]

  // 三模型拟合线：参数全部来自 fitted_models 证据
  const palette: Record<VariogramModelName, string> = {
    spherical: '#e5c76b',
    exponential: '#b794f4',
    gaussian: '#63b3ed',
  }
  const steps = 60
  for (const fitted of props.evidence.fitted_models.models) {
    const line: Array<[number, number]> = []
    for (let i = 0; i <= steps; i += 1) {
      const h = (maxX * i) / steps
      line.push([h, modelSemivariance(fitted.model, fitted.nugget, fitted.partial_sill, fitted.range, h)])
    }
    series.push({
      type: 'line',
      name: `拟合 ${fitted.model}`,
      data: line,
      showSymbol: false,
      lineStyle: { type: 'dashed', width: 1.5, color: palette[fitted.model] },
      itemStyle: { color: palette[fitted.model] },
    })
  }

  // 方向经验系列对比（仅 supported 方向可选）
  for (const id of selectedDirections.value) {
    const entry = directions.value.find((d) => d.id === id)
    if (!entry) continue
    series.push({
      type: 'scatter',
      name: `方向 ${id}`,
      data: entry.bins.map((b) => ({ value: binPoint(b), pairCount: b.pair_count })),
      symbol: 'diamond',
      symbolSize: 10,
    })
  }

  chart.setOption(
    {
      grid: { left: 70, right: 30, top: 40, bottom: 46 },
      legend: { top: 4, textStyle: { color: '#8fa1b3', fontSize: 11 } },
      xAxis: {
        type: 'value',
        name: '距离 h',
        axisLabel: { color: '#8fa1b3', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(143,161,179,0.15)' } },
      },
      yAxis: {
        type: 'value',
        name: '半变异值 γ(h)',
        axisLabel: { color: '#8fa1b3', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(143,161,179,0.15)' } },
      },
      series,
      tooltip: {
        trigger: 'item',
        formatter: (params: {
          seriesName?: string
          value?: [number, number]
          data?: { pairCount?: number; exclusionReason?: string | null }
        }) => {
          const value = params.value ?? [0, 0]
          const lines = [
            `${params.seriesName ?? ''}`,
            `h = ${value[0].toFixed(2)} · γ = ${value[1].toFixed(4)}`,
          ]
          if (typeof params.data?.pairCount === 'number') lines.push(`点对数 ${params.data.pairCount}`)
          if (params.data?.exclusionReason) lines.push(`排除原因 ${params.data.exclusionReason}`)
          return lines.join('<br/>')
        },
      },
    },
    { notMerge: true },
  )
  chart.resize()
}

onMounted(render)
watch(() => [props.evidence, selectedDirections.value], render, { deep: false })
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <section class="variogram-panel" data-test="variogram-panel">
    <h3>经验半变异函数</h3>
    <div class="sampling-line">
      <span data-test="sampling-mode">点对模式：{{ sampling.sampled ? '分层抽样' : '全量' }}</span>
      <span data-test="sampling-rate">采样率 {{ (sampling.sampling_rate * 100).toFixed(1) }}%</span>
      <span data-test="sampling-pairs">
        点对 {{ sampling.used_pair_count }} / {{ sampling.total_pair_count }}
      </span>
      <span data-test="sampling-seed">抽样种子 {{ sampling.seed }}</span>
    </div>

    <div ref="chartEl" class="chart" data-test="variogram-chart" />

    <div v-if="directions.length" class="direction-picker">
      <span class="picker-label">方向系列对比</span>
      <label
        v-for="entry in directions"
        :key="entry.id"
        class="direction-option"
        :class="{ unsupported: entry.unsupported }"
      >
        <input
          type="checkbox"
          :data-test="`direction-option-${entry.id}`"
          :disabled="entry.unsupported"
          :checked="selectedDirections.includes(entry.id)"
          @change="toggleDirection(entry.id)"
        />
        {{ entry.id }}（方位 {{ entry.azimuth_deg }}°<template v-if="entry.dip_deg !== null">
          / 倾角 {{ entry.dip_deg }}°</template
        >）
        <span v-if="entry.unsupported" class="unsupported-note">点对支持不足，不参与比较</span>
      </label>
      <span
        v-for="id in selectedDirections"
        :key="id"
        class="active-tag"
        :data-test="`active-direction-${id}`"
      >
        {{ id }} 已加入对比
      </span>
    </div>

    <table class="bins-table">
      <thead>
        <tr>
          <th>bin</th>
          <th>距离区间</th>
          <th>平均距离</th>
          <th>半变异值</th>
          <th>点对数</th>
          <th>用于拟合</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="bin in omniRows"
          :key="bin.bin_index"
          data-test="omni-bin-row"
          :class="{ excluded: !bin.used_for_fit }"
        >
          <td>{{ bin.bin_index }}</td>
          <td>{{ fmt(bin.lower_distance) }} ~ {{ fmt(bin.upper_distance) }}</td>
          <td>{{ fmt(bin.mean_distance) }}</td>
          <td>{{ fmt(bin.semivariance) }}</td>
          <td>{{ bin.pair_count }}</td>
          <td>
            <template v-if="bin.used_for_fit">是</template>
            <template v-else>否（{{ bin.exclusion_reason }}）</template>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.variogram-panel {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.variogram-panel h3 {
  margin: 0;
  font-size: 15px;
}

.sampling-line {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.chart {
  width: 100%;
  height: 380px;
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  border-radius: 10px;
}

.direction-picker {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  font-size: 12px;
}

.picker-label {
  color: var(--gmp-text-faint);
}

.direction-option {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.direction-option.unsupported {
  color: var(--gmp-text-faint);
  cursor: not-allowed;
}

.unsupported-note {
  font-size: 11px;
  color: #e5c76b;
}

.active-tag {
  border: 1px solid var(--gmp-accent);
  color: var(--gmp-accent);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
}

.bins-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.bins-table th,
.bins-table td {
  border: 1px solid var(--gmp-border);
  padding: 5px 10px;
  text-align: left;
}

.bins-table th {
  color: var(--gmp-text-faint);
  font-weight: 500;
}

.bins-table tr.excluded td {
  color: var(--gmp-text-faint);
  background: rgba(143, 161, 179, 0.08);
}
</style>

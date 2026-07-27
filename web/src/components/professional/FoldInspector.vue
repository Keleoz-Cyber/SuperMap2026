<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { FoldEvidence, ResidualEvidence } from '../../api/types'

// 折分检查只渲染 API 下发的证据：逐折训练/验证计数、空间组身份、泄漏检查
// 与 OOF 残差行全部来自服务端登记工件，前端不计算任何指标。
const props = defineProps<{
  folds: FoldEvidence
  residuals: ResidualEvidence | null
}>()

const selectedFold = ref<number>(props.folds.folds[0]?.fold_index ?? 0)

const selectedFoldInfo = computed(
  () =>
    props.folds.folds.find((fold) => fold.fold_index === selectedFold.value) ??
    props.folds.folds[0] ??
    null,
)

interface ResidualPoint {
  x: number
  y: number
  residual: number | null
}

function rowsOfFold(foldIndex: number): ResidualPoint[] {
  const evidence = props.residuals
  if (!evidence) return []
  const points: ResidualPoint[] = []
  for (let i = 0; i < evidence.returned; i += 1) {
    if (evidence.fold_index[i] !== foldIndex) continue
    if (evidence.is_nodata[i]) continue // NoData 行不进入残差点集
    points.push({ x: evidence.x[i], y: evidence.y[i], residual: evidence.residual[i] ?? null })
  }
  return points
}

// 选中折的验证点集（OOF 行）与背景点集（对该折而言属训练背景的其他折行）分开计数
const validationPoints = computed(() => rowsOfFold(selectedFold.value))
const contextPoints = computed(() => {
  const evidence = props.residuals
  if (!evidence) return []
  const points: ResidualPoint[] = []
  for (let i = 0; i < evidence.returned; i += 1) {
    if (evidence.fold_index[i] === selectedFold.value) continue
    if (evidence.is_nodata[i]) continue
    points.push({ x: evidence.x[i], y: evidence.y[i], residual: evidence.residual[i] ?? null })
  }
  return points
})

const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!chartEl.value) return
  if (!chart) {
    try {
      chart = echarts.init(chartEl.value, undefined, { renderer: 'svg' })
    } catch {
      return // 无图形环境（如 jsdom 降级）：计数与指标仍然可见
    }
  }
  const toData = (points: ResidualPoint[]) =>
    points.map((p) => ({ value: [p.x, p.y, p.residual ?? 0] }))
  chart.setOption(
    {
      title: {
        text: `折 ${selectedFold.value} 验证残差（三角=验证，圆点=训练背景）`,
        textStyle: { fontSize: 12, color: '#c9d4e0' },
      },
      grid: { left: 70, right: 30, top: 44, bottom: 50 },
      xAxis: { type: 'value', name: 'x', axisLabel: { color: '#8fa1b3', fontSize: 10 } },
      yAxis: { type: 'value', name: 'y', axisLabel: { color: '#8fa1b3', fontSize: 10 } },
      visualMap: {
        dimension: 2,
        min: -3,
        max: 3,
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 4,
        text: ['残差', ''],
        textStyle: { color: '#8fa1b3', fontSize: 10 },
        inRange: { color: ['#2b6cb0', '#faf089', '#c53030'] },
      },
      series: [
        {
          name: '训练背景',
          type: 'scatter',
          symbol: 'circle',
          symbolSize: 6,
          data: toData(contextPoints.value),
          itemStyle: { opacity: 0.45 },
        },
        {
          name: '验证',
          type: 'scatter',
          symbol: 'triangle',
          symbolSize: 10,
          data: toData(validationPoints.value),
          itemStyle: { borderColor: '#ffffff', borderWidth: 1 },
        },
      ],
      tooltip: { trigger: 'item' },
    },
    { notMerge: true },
  )
  chart.resize()
}

function selectFold(foldIndex: number) {
  selectedFold.value = foldIndex
}

watch(
  () => props.folds,
  (folds) => {
    // 候选切换后折集合重建：默认回到首折，绝不沿用旧候选的折身份
    selectedFold.value = folds.folds[0]?.fold_index ?? 0
  },
)
watch([selectedFold, () => props.residuals], render, { flush: 'post' })

onMounted(render)
onBeforeUnmount(() => {
  chart?.dispose()
  chart = null
})
</script>

<template>
  <section class="fold-inspector" data-test="fold-inspector">
    <header class="panel-head">
      <h3>折分检查</h3>
      <span
        class="leakage-badge"
        :class="{ leaked: folds.leakage_detected }"
        data-test="leakage-badge"
      >
        {{ folds.leakage_detected ? '检测到泄漏' : '未检测到泄漏' }}
      </span>
      <span class="fold-count">共 {{ folds.fold_count }} 折</span>
    </header>

    <div class="fold-tabs">
      <button
        v-for="fold in folds.folds"
        :key="fold.fold_index"
        class="fold-tab"
        :class="{ active: fold.fold_index === selectedFold }"
        :data-test="`fold-tab-${fold.fold_index}`"
        @click="selectFold(fold.fold_index)"
      >
        折 {{ fold.fold_index }}
        <span v-if="fold.leakage_detected" class="fold-leaked">泄漏</span>
      </button>
    </div>

    <div v-if="selectedFoldInfo" class="fold-detail">
      <span data-test="fold-training-count">训练 {{ selectedFoldInfo.training_count }} 行</span>
      <span data-test="fold-validation-count">验证 {{ selectedFoldInfo.validation_count }} 行</span>
      <span data-test="fold-group-count">空间组 {{ selectedFoldInfo.group_count }} 个</span>
      <span data-test="fold-validation-groups">
        验证组 {{ selectedFoldInfo.validation_groups.join(', ') || '—' }}
      </span>
      <span v-if="selectedFoldInfo.metrics" data-test="fold-rmse">
        RMSE {{ selectedFoldInfo.metrics.rmse ?? '—' }}
      </span>
      <span v-if="selectedFoldInfo.metrics" data-test="fold-valid-count">
        有效验证 {{ selectedFoldInfo.metrics.valid_count ?? '—' }}
      </span>
      <span v-else data-test="fold-metrics-missing">逐折指标未登记</span>
    </div>

    <div ref="chartEl" class="fold-chart" data-test="fold-scatter" />
    <div class="fold-stats">
      <span data-test="validation-point-count">验证点 {{ validationPoints.length }} 个</span>
      <span data-test="context-point-count">训练背景点 {{ contextPoints.length }} 个</span>
      <span v-if="residuals" data-test="residual-total-count">
        OOF 残差 {{ residuals.returned }} / {{ residuals.total }} 行
      </span>
    </div>
  </section>
</template>

<style scoped>
.fold-inspector {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-head h3 {
  margin: 0;
  font-size: 15px;
}

.leakage-badge {
  border: 1px solid #2f855a;
  color: #68d391;
  border-radius: 999px;
  padding: 2px 12px;
  font-size: 12px;
}

.leakage-badge.leaked {
  border-color: #a43d3d;
  color: #ef9a9a;
}

.fold-count {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.fold-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.fold-tab {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  border-radius: 8px;
  padding: 5px 14px;
  font-size: 12px;
  cursor: pointer;
}

.fold-tab.active {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.fold-leaked {
  margin-left: 6px;
  color: #ef9a9a;
}

.fold-detail {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.fold-chart {
  width: 100%;
  height: 320px;
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  border-radius: 10px;
}

.fold-stats {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--gmp-text-faint);
}
</style>

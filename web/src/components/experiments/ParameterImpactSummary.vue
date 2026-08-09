<script setup lang="ts">
// v0.9.0：参数影响摘要。如实陈述当前参数预计产生的网格规模、验证折数、
// 邻域/算法要点与组合数；风险与上限警告显式展示，绝不编造未计算的数字。
import { computed } from 'vue'
import type { GridSpecPayload, ValidationSpecPayload } from '../../api/types'

const props = defineProps<{
  algorithm: string
  searchMode: 'manual' | 'grid'
  combinationCount: number
  grid: GridSpecPayload | null
  validation: ValidationSpecPayload | null
  parameters: Record<string, unknown>
  warnings: string[]
}>()

// 网格节点估计：resolution 为逐轴间距（与 ParameterEditor 提交合同一致），
// 节点数 = round((max-min)/spacing)+1；任一轴非法则整体不显示
const gridShape = computed<number[] | null>(() => {
  if (!props.grid) return null
  const counts: number[] = []
  for (let i = 0; i < props.grid.bounds.length; i++) {
    const [lo, hi] = props.grid.bounds[i]
    const spacing = props.grid.resolution[i]
    if (!(hi > lo) || !(spacing > 0)) return null
    counts.push(Math.round((hi - lo) / spacing) + 1)
  }
  return counts
})

const gridNodes = computed(() => {
  if (!gridShape.value) return null
  const nodes = gridShape.value.reduce((acc, n) => acc * n, 1)
  return Number.isFinite(nodes) && nodes > 0 ? nodes : null
})

const ALGO_LABELS: Record<string, string> = {
  idw: 'IDW',
  ordinary_kriging: '普通克里金',
  dsi_like: 'DSI-like 离散平滑插值',
}

const algorithmLabel = computed(() => ALGO_LABELS[props.algorithm] ?? props.algorithm)

const neighborhoodLine = computed(() => {
  const p = props.parameters
  if (props.algorithm === 'idw') {
    const power = typeof p.power === 'number' ? p.power : null
    const neighbors = typeof p.neighbor_count === 'number' ? p.neighbor_count : null
    if (power === null && neighbors === null) return null
    return `幂次 ${power ?? '—'} · 邻点 ${neighbors ?? '—'}`
  }
  if (props.algorithm === 'ordinary_kriging') {
    const model = typeof p.variogram_model === 'string' ? p.variogram_model : null
    const neighbors = typeof p.neighbor_count === 'number' ? p.neighbor_count : null
    return [model, neighbors !== null ? `邻点 ${neighbors}` : null].filter(Boolean).join(' · ') || null
  }
  return null
})

const overCap = computed(() => props.combinationCount > 50)
</script>

<template>
  <section class="impact-summary" data-test="parameter-impact">
    <h4 class="impact-title">候选摘要</h4>
    <dl class="impact-list">
      <div class="impact-row">
        <dt>算法</dt>
        <dd>{{ algorithmLabel }}</dd>
      </div>
      <div class="impact-row">
        <dt>参数组合</dt>
        <dd data-test="impact-combinations">
          {{ searchMode === 'manual' ? '单组参数（1 个候选）' : `${combinationCount} 个候选` }}
        </dd>
      </div>
      <div class="impact-row">
        <dt>预计网格</dt>
        <dd v-if="gridNodes !== null && gridShape" data-test="impact-grid">
          {{ gridShape.join('×') }} · {{ gridNodes.toLocaleString() }} 节点
        </dd>
        <dd v-else>默认网格</dd>
      </div>
      <div class="impact-row">
        <dt>空间验证</dt>
        <dd v-if="validation" data-test="impact-folds">
          {{ validation.method === 'spatial_kfold' ? `${validation.folds} 折` : '留出法' }} · 种子 {{ validation.seed }}
        </dd>
        <dd v-else>—</dd>
      </div>
      <div v-if="neighborhoodLine" class="impact-row">
        <dt>邻域 / 模型</dt>
        <dd>{{ neighborhoodLine }}</dd>
      </div>
    </dl>
    <div v-if="overCap" class="impact-warning" data-test="impact-warnings">
      组合数 {{ combinationCount }} 超过上限 50，请收窄参数网格
    </div>
    <div v-else-if="warnings.length > 0" class="impact-warning" data-test="impact-warnings">
      <p v-for="w in warnings" :key="w">{{ w }}</p>
    </div>
  </section>
</template>

<style scoped>
.impact-summary {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  padding: var(--s1-space-3) var(--s1-space-4);
}

.impact-title {
  margin: 0 0 var(--s1-space-2);
  font-size: var(--s1-font-sm);
  font-weight: 600;
  color: var(--s1-text-dim);
  letter-spacing: 0.05em;
}

.impact-list {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.impact-row {
  display: flex;
  gap: 10px;
  font-size: var(--s1-font-sm);
}

.impact-row dt {
  width: 64px;
  flex: none;
  color: var(--s1-text-faint);
}

.impact-row dd {
  margin: 0;
  color: var(--s1-text);
  font-variant-numeric: tabular-nums;
}

.impact-warning {
  margin-top: var(--s1-space-2);
  font-size: var(--s1-font-sm);
  color: var(--s1-warning);
  border: 1px solid rgba(217, 168, 78, 0.4);
  border-radius: var(--s1-radius-sm);
  padding: 6px 10px;
}

.impact-warning p {
  margin: 0;
}
</style>

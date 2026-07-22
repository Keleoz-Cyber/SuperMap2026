<script setup lang="ts">
import { computed } from 'vue'
import type { ModelEntry, ModelRole } from '../api/types'

const props = defineProps<{
  models: ModelEntry[]
  metricSource: string
  commonValid: number
  commonNodata: number
}>()

const ROLE_ORDER: Record<string, number> = {
  default: 0,
  comparison: 1,
  candidate: 2,
  not_formal_candidate: 3,
}

const ROLE_TEXT: Record<string, string> = {
  default: '默认',
  comparison: '对照',
  candidate: '候选',
  not_formal_candidate: '非正式',
}

const sortedModels = computed(() =>
  [...props.models].sort((a, b) => {
    const ra = ROLE_ORDER[a.role] ?? 9
    const rb = ROLE_ORDER[b.role] ?? 9
    if (ra !== rb) return ra - rb
    const ma = a.metrics?.mae ?? Number.POSITIVE_INFINITY
    const mb = b.metrics?.mae ?? Number.POSITIVE_INFINITY
    return ma - mb
  }),
)

const hasMissingMetrics = computed(() => props.models.some((m) => !m.metrics))

function roleText(role: ModelRole): string {
  return ROLE_TEXT[role] ?? role
}

function roleTagType(role: ModelRole): 'primary' | 'info' | undefined {
  if (role === 'comparison') return 'primary'
  if (role === 'candidate') return 'info'
  return undefined
}

function roleTagStyle(role: ModelRole): Record<string, string> | undefined {
  if (role === 'default') {
    return { background: 'rgba(138,109,29,0.25)', color: '#e8c25a', borderColor: '#8a6d1d' }
  }
  if (role === 'not_formal_candidate') {
    return { background: '#1a212a', color: '#6b7686', borderColor: '#2a333f' }
  }
  return undefined
}

function fmt(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined ? '—' : v.toFixed(digits)
}

function fmtPct(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${(v * 100).toFixed(1)}%`
}

function metricNumber(row: ModelEntry, key: 'mae' | 'rmse' | 'r2' | 'bias' | 'coverage_rate') {
  const v = row.metrics?.[key]
  return v === null || v === undefined ? Number.NEGATIVE_INFINITY : v
}

function sortBy(key: 'mae' | 'rmse' | 'r2' | 'bias' | 'coverage_rate') {
  return (a: ModelEntry, b: ModelEntry) => metricNumber(a, key) - metricNumber(b, key)
}
</script>

<template>
  <div class="leaderboard">
    <el-alert
      v-if="hasMissingMetrics"
      type="warning"
      :closable="false"
      class="missing-alert"
      title="部分模型指标产物缺失，请先运行 geomodeling run-all"
    />
    <el-table :data="sortedModels" row-key="model_id" size="small">
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="model-detail">
            <template v-if="row.metrics">
              <div class="detail-grid">
                <div><span>分辨率</span><b>{{ row.resolution_xy_m }} m</b></div>
                <div><span>邻域点数</span><b>{{ row.neighbor_count }}</b></div>
                <div><span>n_valid</span><b>{{ row.metrics.n_valid.toLocaleString() }}</b></div>
                <div><span>n_nodata</span><b>{{ row.metrics.n_nodata.toLocaleString() }}</b></div>
              </div>
              <div class="param-chips">
                <span class="param-chip mono" v-for="(val, key) in row.parameters" :key="key">
                  {{ key }} = {{ val }}
                </span>
              </div>
            </template>
            <el-alert
              v-else
              type="warning"
              :closable="false"
              title="指标产物缺失，请先运行 geomodeling run-all"
            />
          </div>
        </template>
      </el-table-column>
      <el-table-column label="模型" min-width="132">
        <template #default="{ row }">
          <div class="model-name">{{ row.display_name }}</div>
          <div class="model-tags">
            <el-tag
              size="small"
              effect="dark"
              :type="roleTagType(row.role)"
              :style="roleTagStyle(row.role)"
            >
              {{ roleText(row.role) }}
            </el-tag>
            <span class="method mono">{{ row.method }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="MAE" width="64" align="right" sortable :sort-method="sortBy('mae')">
        <template #default="{ row }">{{ fmt(row.metrics?.mae) }}</template>
      </el-table-column>
      <el-table-column label="RMSE" width="66" align="right" sortable :sort-method="sortBy('rmse')">
        <template #default="{ row }">{{ fmt(row.metrics?.rmse) }}</template>
      </el-table-column>
      <el-table-column label="R²" width="64" align="right" sortable :sort-method="sortBy('r2')">
        <template #default="{ row }">{{ fmt(row.metrics?.r2, 3) }}</template>
      </el-table-column>
      <el-table-column label="Bias" width="62" align="right" sortable :sort-method="sortBy('bias')">
        <template #default="{ row }">{{ fmt(row.metrics?.bias) }}</template>
      </el-table-column>
      <el-table-column
        label="覆盖率"
        width="70"
        align="right"
        sortable
        :sort-method="sortBy('coverage_rate')"
      >
        <template #default="{ row }">{{ fmtPct(row.metrics?.coverage_rate) }}</template>
      </el-table-column>
    </el-table>
    <p class="panel-note">
      {{ models.length }} 个模型在同一公共有效验证集（{{ commonValid.toLocaleString() }} valid /
      {{ commonNodata.toLocaleString() }} NoData）上比较 · 指标来源
      <span class="mono">{{ metricSource }}</span>
    </p>
  </div>
</template>

<style scoped>
.missing-alert {
  margin-bottom: 10px;
}

.leaderboard :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: var(--gmp-bg-soft);
  --el-table-border-color: var(--gmp-border-soft);
  --el-table-expanded-cell-bg-color: var(--gmp-bg-soft);
  font-size: 12px;
}

.model-name {
  font-weight: 600;
  font-size: 12px;
  line-height: 1.4;
}

.model-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}

.method {
  color: var(--gmp-text-faint);
  font-size: 11px;
}

.model-detail {
  padding: 6px 10px 10px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  margin-bottom: 10px;
}

.detail-grid div {
  display: flex;
  flex-direction: column;
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border-soft);
  border-radius: 6px;
  padding: 6px 8px;
}

.detail-grid span {
  font-size: 11px;
  color: var(--gmp-text-faint);
}

.detail-grid b {
  font-size: 13px;
  margin-top: 2px;
}

.param-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.param-chip {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border-soft);
  border-radius: 6px;
  padding: 3px 8px;
  color: var(--gmp-text-dim);
}
</style>

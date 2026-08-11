<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { AnalysisModuleResult } from '../../api/types'
import { algorithmLabel, parameterSummary } from '../../utils/modelingLabels'
import {
  comparisonCandidatesOf,
  formatNumber,
  type ModelComparisonCandidate,
} from './analysisTypes'

// v0.8.0 第二批 Task 5：模型比较——只读既有 succeeded 候选（后端绝不重
// 算指标）。表格列：算法中文标签/参数摘要/RMSE/MAE/R²/Bias + 物化与正式
// 选择徽标；点击行导航到 /results/{result_id}。无候选时解释性空状态。

const props = defineProps<{ module: AnalysisModuleResult | null }>()

const router = useRouter()

const candidates = computed(() => comparisonCandidatesOf(props.module))

const unavailableMessage = computed(() => {
  if (props.module && props.module.status !== 'ok') {
    return props.module.message ?? '模型比较模块在当前数据版本不可用。'
  }
  return null
})

function paramsOf(candidate: ModelComparisonCandidate): string {
  const parts = parameterSummary(candidate.algorithm, candidate.parameters)
  return parts.length > 0 ? parts.join(' · ') : '—'
}

function metricOf(candidate: ModelComparisonCandidate, key: string): string {
  return formatNumber(candidate.metrics[key])
}

function openCandidate(candidate: ModelComparisonCandidate) {
  void router.push({ path: candidate.result_url })
}
</script>

<template>
  <section class="panel model-comparison" data-test="model-comparison-panel">
    <h3>模型比较</h3>
    <p v-if="unavailableMessage" class="empty-note" data-test="model-comparison-empty">
      {{ unavailableMessage }}
    </p>
    <p v-else-if="candidates.length === 0" class="empty-note" data-test="model-comparison-empty">
      该数据版本下尚无已成功的候选成果；运行实验并等待候选成功后，此处将展示可对比的公共指标。
    </p>
    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>算法</th>
            <th>参数</th>
            <th>RMSE</th>
            <th>MAE</th>
            <th>R²</th>
            <th>Bias</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="candidate in candidates"
            :key="candidate.result_id"
            class="candidate-row"
            data-test="model-candidate-row"
            tabindex="0"
            @click="openCandidate(candidate)"
            @keydown.enter="openCandidate(candidate)"
          >
            <td>{{ algorithmLabel(candidate.algorithm) }}</td>
            <td class="params">{{ paramsOf(candidate) }}</td>
            <td class="num">{{ metricOf(candidate, 'rmse') }}</td>
            <td class="num">{{ metricOf(candidate, 'mae') }}</td>
            <td class="num">{{ metricOf(candidate, 'r2') }}</td>
            <td class="num">{{ metricOf(candidate, 'bias') }}</td>
            <td class="badges">
              <el-tag v-if="candidate.materialized" size="small" type="primary" effect="plain" data-test="badge-materialized">
                已物化
              </el-tag>
              <span v-else class="not-materialized">未物化</span>
              <el-tag v-if="candidate.formal_selection" size="small" type="success" effect="dark" data-test="badge-formal">
                正式选择
              </el-tag>
            </td>
          </tr>
        </tbody>
      </table>
      <p class="hint">指标为公共有效集上的既有记录；点击行打开成果视图。</p>
    </div>
  </section>
</template>

<style scoped>
.panel {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

h3 {
  margin: 0;
  font-size: 15px;
}

.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

th {
  text-align: left;
  color: var(--gmp-text-faint);
  font-weight: 500;
  padding: 4px 8px 4px 0;
  border-bottom: 1px solid var(--gmp-border);
  white-space: nowrap;
}

td {
  padding: 6px 8px 6px 0;
  border-bottom: 1px solid var(--gmp-border-soft);
  vertical-align: top;
}

.candidate-row {
  cursor: pointer;
}

.candidate-row:hover td {
  background: var(--gmp-card-hover);
}

.params {
  color: var(--gmp-text-dim);
  max-width: 220px;
}

.num {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.badges {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}

.not-materialized {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.hint {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.empty-note {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-faint);
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import type { MLResultEvidence } from '../../api/types'
import { algorithmLabel } from '../../utils/modelingLabels'

const props = defineProps<{ evidence: MLResultEvidence }>()

const isComparable = computed(() => props.evidence.comparison_status === 'comparable')

const conclusion = computed(() => {
  if (!isComparable.value) return '暂不能与普通克里金直接比较'
  return props.evidence.improved_over_kriging
    ? '本次验证优于普通克里金'
    : '本次验证未优于普通克里金'
})

function percentChange(value: number | null, metric: string): string {
  if (value === null || !Number.isFinite(value)) return `${metric} 变化率不可用`
  const action = value < 0 ? '降低' : value > 0 ? '增加' : '持平'
  return action === '持平' ? `${metric} 持平` : `${metric} ${action} ${Math.abs(value).toFixed(1)}%`
}

function shortHash(value: string | null): string {
  if (!value) return '—'
  return value.length > 16 ? `${value.slice(0, 12)}…${value.slice(-4)}` : value
}
</script>

<template>
  <section class="ml-evidence" data-test="ml-model-evidence">
    <div class="summary" data-test="ml-evidence-summary">
      <header class="summary-head">
        <div>
          <span class="eyebrow">机器学习模型证据</span>
          <h4>{{ algorithmLabel(evidence.algorithm) }}</h4>
        </div>
        <span
          class="verdict"
          :class="{ improved: evidence.improved_over_kriging === true, neutral: evidence.improved_over_kriging !== true }"
          data-test="ml-evidence-conclusion"
        >
          {{ conclusion }}
        </span>
      </header>

      <template v-if="isComparable && evidence.metric_change && evidence.baseline">
        <div class="metric-grid">
          <article>
            <span>相对普通克里金</span>
            <strong>{{ percentChange(evidence.metric_change.rmse_percent, 'RMSE') }}</strong>
          </article>
          <article>
            <span>平均绝对误差</span>
            <strong>{{ percentChange(evidence.metric_change.mae_percent, 'MAE') }}</strong>
          </article>
          <article>
            <span>相同验证方式</span>
            <strong>公共有效点 {{ evidence.baseline.common_valid_count.toLocaleString() }}</strong>
          </article>
        </div>
      </template>
      <p v-else class="comparison-note">
        当前没有满足相同数据版本、验证规则和公共有效集的普通克里金成果，因此不计算提升比例。
      </p>

      <ul v-if="evidence.limitations.length" class="limitations" aria-label="模型限制">
        <li v-for="item in evidence.limitations" :key="item">{{ item }}</li>
      </ul>
    </div>

    <details class="technical" data-test="ml-evidence-technical">
      <summary>技术详情</summary>
      <dl>
        <div><dt>特征版本</dt><dd>{{ evidence.technical_details.feature_version ?? '—' }}</dd></div>
        <div><dt>运行库</dt><dd>scikit-learn {{ evidence.technical_details.sklearn_version ?? '—' }}</dd></div>
        <div><dt>验证方式</dt><dd>{{ evidence.technical_details.validation_method ?? '—' }}</dd></div>
        <div><dt>公共有效点</dt><dd>{{ evidence.technical_details.common_valid_count?.toLocaleString() ?? '—' }}</dd></div>
        <div><dt>折分指纹</dt><dd class="mono">{{ shortHash(evidence.technical_details.fold_assignments_sha256) }}</dd></div>
      </dl>
    </details>
  </section>
</template>

<style scoped>
.ml-evidence {
  grid-column: 1 / -1;
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-2);
  overflow: hidden;
}

.summary {
  padding: var(--s1-space-3);
}

.summary-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s1-space-3);
}

.eyebrow,
.metric-grid span {
  color: var(--s1-text-faint);
  font-size: var(--s1-font-xs);
}

h4 {
  margin: 3px 0 0;
  color: var(--s1-text);
  font-size: var(--s1-font-md);
}

.verdict {
  padding: 4px 9px;
  border: 1px solid var(--s1-warning);
  border-radius: 5px;
  color: var(--s1-warning);
  font-size: var(--s1-font-xs);
  font-weight: 600;
}

.verdict.improved {
  border-color: var(--s1-success);
  color: var(--s1-success);
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--s1-space-2);
  margin-top: var(--s1-space-3);
}

.metric-grid article {
  min-width: 0;
  padding: 8px 10px;
  border-left: 2px solid var(--s1-cyan-dim);
  background: var(--s1-surface-1);
}

.metric-grid strong {
  display: block;
  margin-top: 3px;
  color: var(--s1-text);
  font-size: var(--s1-font-sm);
}

.comparison-note,
.limitations {
  margin: var(--s1-space-3) 0 0;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-sm);
  line-height: 1.55;
}

.limitations {
  padding-left: 18px;
}

.technical {
  border-top: 1px solid var(--s1-border-soft);
  padding: 7px var(--s1-space-3);
  color: var(--s1-text-faint);
  font-size: var(--s1-font-xs);
}

.technical summary {
  cursor: pointer;
}

.technical dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 18px;
  margin: 10px 0 4px;
}

.technical dl div {
  min-width: 0;
}

.technical dt,
.technical dd {
  margin: 0;
}

.technical dd {
  color: var(--s1-text-dim);
  overflow-wrap: anywhere;
}

@media (max-width: 720px) {
  .summary-head {
    flex-direction: column;
  }

  .metric-grid,
  .technical dl {
    grid-template-columns: 1fr;
  }
}
</style>

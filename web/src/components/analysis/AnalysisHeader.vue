<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisProfileId, AnalysisSummaryResponse } from '../../api/types'

// v0.8.0 第二批 Task 5：分析中心顶栏——案例身份、数据版本、变量/单位、
// 坐标类型、数据质量徽标与导出入口（Task 7 起 export 事件由视图展开底部
// 导出/溯源区，执行真实 JSON/CSV 导出）。绝不渲染原始文件路径。

const props = defineProps<{ summary: AnalysisSummaryResponse }>()
const emit = defineEmits<{ (e: 'export'): void }>()

const PROFILE_LABELS: Record<AnalysisProfileId, string> = {
  microseismic_velocity: '微震速度',
  resistivity: '电阻率',
  gas_content: '瓦斯含量',
  generic_3d: '通用三维',
}

const profileLabel = computed(() => PROFILE_LABELS[props.summary.analysis_profile])
const variableDisplayName = computed(() => {
  if (props.summary.analysis_profile === 'gas_content') return '瓦斯含量'
  if (props.summary.analysis_profile === 'resistivity') return '电阻率'
  if (props.summary.analysis_profile === 'microseismic_velocity') return '微震速度'
  return props.summary.variable.name
})

const unitSuffix = computed(() =>
  props.summary.variable.unit ? `（${props.summary.variable.unit}）` : '',
)

// 坐标类型由质量摘要 bounds 的轴键推导（后端合同：键为 x/y[/z]）
const coordType = computed(() => {
  const bounds = props.summary.quality.bounds
  if (!bounds) return '坐标范围未知'
  return 'z' in bounds ? '三维坐标（X/Y/Z）' : '二维坐标（X/Y）'
})

interface QualityBadge {
  type: 'success' | 'warning' | 'info'
  text: string
}

const qualityBadge = computed<QualityBadge>(() => {
  const q = props.summary.quality
  const rows = q.row_count ?? 0
  const invalid = q.invalid_count ?? 0
  if (q.valid_count !== null && invalid === 0) {
    return { type: 'success', text: `数据全部有效（${rows.toLocaleString('zh-CN')} 行）` }
  }
  if (invalid > 0) {
    return {
      type: 'warning',
      text: `${invalid.toLocaleString('zh-CN')} 行无效/缺失（有效 ${(q.valid_count ?? 0).toLocaleString('zh-CN')}/${rows.toLocaleString('zh-CN')}）`,
    }
  }
  return { type: 'info', text: '数据质量未知' }
})
</script>

<template>
  <header class="analysis-header" data-test="analysis-header">
    <div class="identity">
      <div class="identity-head">
        <h1>统计与空间分析</h1>
        <el-tag type="primary" effect="dark" data-test="analysis-profile-badge">
          {{ profileLabel }}
        </el-tag>
        <el-tag
          :type="qualityBadge.type"
          effect="plain"
          data-test="analysis-quality-badge"
        >
          {{ qualityBadge.text }}
        </el-tag>
      </div>
      <p class="identity-line">
        <span data-test="analysis-variable">分析属性：{{ variableDisplayName }}{{ unitSuffix }}</span>
        · <span data-test="analysis-coord-type">{{ coordType }}</span>
      </p>
      <details class="identity-technical" data-test="analysis-identity">
        <summary>技术详情</summary>
        <p>案例 <span class="mono">{{ summary.case_id }}</span> · 数据集 <span class="mono">{{ summary.dataset_id }}</span></p>
        <p>源字段 <span class="mono">{{ summary.variable.name }}</span></p>
        <p>数据版本 v{{ summary.provenance.dataset_version }} · 计算版本 <span class="mono">{{ summary.provenance.calculation_version }}</span></p>
      </details>
    </div>
    <div class="header-actions">
      <el-button type="primary" plain data-test="analysis-export-command" @click="emit('export')">
        导出分析摘要
      </el-button>
    </div>
  </header>
</template>

<style scoped>
.analysis-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
}

.identity {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.identity-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.identity-head h1 {
  margin: 0;
  font-size: 18px;
}

.identity-line {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.identity-technical {
  color: var(--gmp-text-faint);
  font-size: 12px;
}

.identity-technical summary {
  cursor: pointer;
}

.identity-technical p {
  margin: 5px 0 0;
}

.mono {
  font-family: ui-monospace, monospace;
}

.header-actions {
  flex-shrink: 0;
}

@media (max-width: 600px) {
  .analysis-header {
    flex-direction: column;
  }
}
</style>

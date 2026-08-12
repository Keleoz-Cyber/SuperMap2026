<script setup lang="ts">
// v0.9.0：数据接入与准备同屏工作台（混合式布局）。
// 顶部四阶段导航 + 左侧数据区 + 中央空间预览 + 右侧映射诊断 + 底部质量摘要。
// 本组件只组合 DTO 并透传回调：不上传、不校验、不直接调用任何 API；
// DatasetWizardView 仍是唯一状态所有者。
import { computed } from 'vue'
import type {
  DatasetVersionRecord,
  FieldMappingPayload,
  InspectionResult,
  QualityReport,
} from '../../api/types'
import FileStep from './FileStep.vue'
import MappingStep from './MappingStep.vue'
import QualityStep from './QualityStep.vue'
import SpatialPreview from './SpatialPreview.vue'
import type { SpatialMapping } from './SpatialPreview.vue'
import QualityComposition from './QualityComposition.vue'

interface ConversionSummary {
  valid: number
  invalid: number
  total: number
}

const props = defineProps<{
  dataset: DatasetVersionRecord
  inspection: InspectionResult | null
  report: QualityReport | null
  conversion: ConversionSummary | null
  submitting: boolean
  validating: boolean
  confirming: boolean
}>()

const emit = defineEmits<{
  (e: 'sheet-change', sheet: string): void
  (e: 'submit-mapping', mapping: FieldMappingPayload): void
  (e: 'validate'): void
  (e: 'confirm-warnings'): void
  (e: 'start'): void
}>()

type IntakeStage = 'file' | 'mapping' | 'quality' | 'confirm'

// 当前阶段由服务端数据版本状态推导（刷新后恢复同一阶段）
const currentStage = computed<IntakeStage>(() => {
  switch (props.dataset.status) {
    case 'validated':
      return 'confirm'
    case 'mapped':
      return 'quality'
    default:
      return 'mapping'
  }
})

const STAGE_ORDER: IntakeStage[] = ['file', 'mapping', 'quality', 'confirm']
const STAGE_LABELS: Record<IntakeStage, string> = {
  file: '文件接入',
  mapping: '字段映射',
  quality: '质量检查',
  confirm: '建模确认',
}

function stageState(stage: IntakeStage): 'done' | 'active' | 'pending' {
  const current = STAGE_ORDER.indexOf(currentStage.value)
  const mine = STAGE_ORDER.indexOf(stage)
  if (mine < current) return 'done'
  if (mine === current) return 'active'
  return 'pending'
}

const showMapping = computed(
  () => props.dataset.status === 'uploaded' || props.dataset.status === 'blocked',
)
const showQuality = computed(
  () =>
    props.dataset.status === 'mapped' ||
    (props.report !== null && props.dataset.status === 'validated'),
)

// 空间预览映射：已映射/已验证用服务端确认映射，否则用候选映射（仅预览，不提交）
const activeMapping = computed<SpatialMapping | null>(() => {
  const profile = props.dataset.profile as Record<string, unknown>
  const confirmed = profile?.mapping as Record<string, unknown> | undefined
  if (confirmed && typeof confirmed.x === 'string' && typeof confirmed.y === 'string') {
    return {
      x: confirmed.x,
      y: confirmed.y,
      z: typeof confirmed.z === 'string' ? confirmed.z : null,
      value: typeof confirmed.value === 'string' ? confirmed.value : null,
    }
  }
  const candidate = props.inspection?.candidate_mapping
  if (candidate?.x && candidate.y) {
    return {
      x: candidate.x,
      y: candidate.y,
      z: candidate.z ?? null,
      value: candidate.value ?? null,
    }
  }
  return null
})
</script>

<template>
  <div class="intake-workbench" data-test="data-intake-workbench">
    <nav class="intake-stages" aria-label="数据接入阶段">
      <span
        v-for="stage in STAGE_ORDER"
        :key="stage"
        class="intake-stage"
        :class="stageState(stage)"
        :data-test="`intake-stage-${stage}`"
        :data-state="stageState(stage)"
      >
        {{ STAGE_LABELS[stage] }}
      </span>
    </nav>

    <div class="intake-grid">
      <div class="intake-left">
        <FileStep :dataset="dataset" :inspection="inspection" @sheet-change="emit('sheet-change', $event)" />
      </div>
      <div class="intake-center">
        <SpatialPreview :inspection="inspection" :mapping="activeMapping" />
      </div>
      <div class="intake-right">
        <div v-if="showMapping" data-test="wizard-step-mapping">
          <MappingStep
            :inspection="inspection"
            :submitting="submitting"
            :conversion="conversion"
            @submit="emit('submit-mapping', $event)"
          />
        </div>
        <div v-else-if="showQuality" data-test="wizard-step-quality">
          <QualityStep
            :report="report"
            :validating="validating"
            :confirming="confirming"
            @validate="emit('validate')"
            @confirm="emit('confirm-warnings')"
            @start="emit('start')"
          />
        </div>
      </div>
    </div>

    <QualityComposition :report="report" />
  </div>
</template>

<style scoped>
.intake-workbench {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-4);
}

.intake-stages {
  display: flex;
  gap: var(--s1-space-2);
  flex-wrap: wrap;
}

.intake-stage {
  font-size: var(--s1-font-sm);
  border: 1px solid var(--s1-border);
  border-radius: 999px;
  padding: 4px 14px;
  color: var(--s1-text-faint);
  background: var(--s1-surface-1);
}

.intake-stage.done {
  color: var(--s1-success);
  border-color: rgba(70, 185, 124, 0.4);
}

.intake-stage.active {
  color: var(--s1-cyan-strong);
  border-color: var(--s1-cyan-dim);
  background: var(--s1-cyan-ghost);
  font-weight: 600;
}

.intake-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1.1fr);
  gap: var(--s1-space-4);
  align-items: start;
}

.intake-left,
.intake-center,
.intake-right {
  min-width: 0;
}

@media (max-width: 1100px) {
  .intake-grid {
    grid-template-columns: 1fr 1fr;
  }

  .intake-right {
    grid-column: 1 / -1;
  }
}

@media (max-width: 640px) {
  .intake-grid {
    grid-template-columns: 1fr;
  }
}
</style>

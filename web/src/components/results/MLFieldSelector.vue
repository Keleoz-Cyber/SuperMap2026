<script setup lang="ts">
import type { MLResultField } from '../../api/types'

withDefaults(defineProps<{
  modelValue: MLResultField
  availableFields: MLResultField[]
  propertyUnit?: string | null
  loading?: boolean
}>(), {
  propertyUnit: null,
  loading: false,
})

const emit = defineEmits<{ (e: 'update:modelValue', field: MLResultField): void }>()

const LABELS: Record<MLResultField, { label: string; note: string }> = {
  prediction: { label: '预测结果', note: '模型输出的属性连续场' },
  model_dispersion: { label: '模型离散度', note: '树模型分歧参考，不是置信区间' },
  kriging_baseline: { label: '克里金基线', note: '残差校正前的克里金预测' },
  residual_correction: { label: '残差校正', note: '正负值表示对基线的增减修正' },
}
</script>

<template>
  <section class="field-selector" data-test="ml-field-selector" aria-label="机器学习成果字段">
    <div class="field-heading">
      <div>
        <span>成果字段</span>
        <strong>{{ LABELS[modelValue].label }}</strong>
      </div>
      <p data-test="ml-field-status">
        {{ loading ? '正在切换字段…' : `${LABELS[modelValue].note}${propertyUnit ? ` · ${propertyUnit}` : ''}` }}
      </p>
    </div>
    <div class="field-options" role="tablist" aria-label="选择成果字段">
      <button
        v-for="field in availableFields"
        :key="field"
        type="button"
        role="tab"
        :aria-selected="modelValue === field"
        :disabled="loading"
        :data-test="`ml-field-${field}`"
        @click="emit('update:modelValue', field)"
      >
        {{ LABELS[field].label }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.field-selector {
  display: grid;
  grid-template-columns: minmax(190px, 0.75fr) minmax(0, 1.6fr);
  align-items: center;
  gap: var(--s1-space-3);
  padding: 8px 12px;
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-sm);
  background: var(--s1-surface-1);
}

.field-heading {
  min-width: 0;
}

.field-heading > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.field-heading span,
.field-heading p {
  color: var(--s1-text-faint);
  font-size: var(--s1-font-xs);
}

.field-heading strong {
  color: var(--s1-text);
  font-size: var(--s1-font-sm);
}

.field-heading p {
  margin: 3px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.field-options {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(112px, 1fr));
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--s1-border-soft);
  border-radius: 6px;
  background: var(--s1-surface-2);
}

.field-options button {
  min-height: 30px;
  border: 1px solid transparent;
  border-radius: 4px;
  background: transparent;
  color: var(--s1-text-dim);
  cursor: pointer;
  font-size: var(--s1-font-xs);
}

.field-options button[aria-selected='true'] {
  border-color: var(--s1-cyan-dim);
  background: var(--s1-cyan-ghost);
  color: var(--s1-cyan-strong);
  font-weight: 600;
}

.field-options button:disabled {
  cursor: wait;
  opacity: 0.55;
}

@media (max-width: 720px) {
  .field-selector {
    grid-template-columns: 1fr;
  }
}
</style>

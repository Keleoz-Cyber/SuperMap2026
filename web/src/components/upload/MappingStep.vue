<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { FieldMappingPayload, InspectionResult } from '../../api/types'

interface ConversionSummary {
  valid: number
  invalid: number
  total: number
}

const props = defineProps<{
  inspection: InspectionResult | null
  submitting: boolean
  conversion: ConversionSummary | null
}>()

const emit = defineEmits<{
  (e: 'submit', mapping: FieldMappingPayload): void
}>()

const columnNames = computed(() => (props.inspection?.columns ?? []).map((c) => c.name))

const dimension = ref<'2d' | '3d'>('2d')
const x = ref('')
const y = ref('')
const z = ref('')
const value = ref('')
const valueName = ref('')
const valueUnit = ref('')
const coordinateKind = ref<FieldMappingPayload['coordinate_kind']>('local_linear')

// 候选映射到达后初始化（服务端启发式猜测，仅作默认值，用户可改）
watch(
  () => props.inspection,
  (inspection) => {
    if (!inspection) return
    const candidate = inspection.candidate_mapping ?? {}
    x.value = candidate.x ?? ''
    y.value = candidate.y ?? ''
    z.value = candidate.z ?? ''
    value.value = candidate.value ?? ''
    valueName.value = candidate.value_name ?? ''
    dimension.value = candidate.z ? '3d' : '2d'
  },
  { immediate: true },
)

const canSubmit = computed(() => {
  if (props.submitting || !x.value || !y.value || !value.value || !valueName.value) return false
  const picked = [x.value, y.value, value.value]
  if (dimension.value === '3d') {
    if (!z.value) return false
    picked.push(z.value)
  }
  return new Set(picked).size === picked.length
})

function submit() {
  emit('submit', {
    dimension: dimension.value,
    x: x.value,
    y: y.value,
    z: dimension.value === '3d' ? z.value : null,
    value: value.value,
    value_name: valueName.value,
    value_unit: valueUnit.value || null,
    coordinate_kind: coordinateKind.value,
  })
}
</script>

<template>
  <section class="wizard-step" data-test="step-mapping">
    <h3><span class="step-no">2</span> 字段映射</h3>

    <div class="dimension-row">
      <label class="radio">
        <input
          type="radio"
          name="dimension"
          value="2d"
          data-test="dimension-2d"
          :checked="dimension === '2d'"
          @change="dimension = '2d'"
        />
        二维（X/Y）
      </label>
      <label class="radio">
        <input
          type="radio"
          name="dimension"
          value="3d"
          data-test="dimension-3d"
          :checked="dimension === '3d'"
          @change="dimension = '3d'"
        />
        三维（X/Y/Z）
      </label>
    </div>

    <div class="mapping-grid">
      <label class="field">
        <span>X 列</span>
        <select v-model="x" class="gmp-select" data-test="mapping-x">
          <option value="" disabled>选择列</option>
          <option v-for="name in columnNames" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <label class="field">
        <span>Y 列</span>
        <select v-model="y" class="gmp-select" data-test="mapping-y">
          <option value="" disabled>选择列</option>
          <option v-for="name in columnNames" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <label v-if="dimension === '3d'" class="field">
        <span>Z 列</span>
        <select v-model="z" class="gmp-select" data-test="mapping-z">
          <option value="" disabled>选择列</option>
          <option v-for="name in columnNames" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <label class="field">
        <span>属性值列</span>
        <select v-model="value" class="gmp-select" data-test="mapping-value">
          <option value="" disabled>选择列</option>
          <option v-for="name in columnNames" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>
      <label class="field">
        <span>属性名称</span>
        <input
          v-model="valueName"
          class="gmp-input"
          data-test="mapping-value-name"
          placeholder="如：电阻率"
        />
      </label>
      <label class="field">
        <span>单位（可选）</span>
        <input v-model="valueUnit" class="gmp-input" data-test="mapping-value-unit" placeholder="如：Ω·m" />
      </label>
      <label class="field">
        <span>坐标类型</span>
        <select v-model="coordinateKind" class="gmp-select" data-test="mapping-coordinate-kind">
          <option value="local_linear">局部线性坐标</option>
          <option value="projected">投影坐标</option>
          <option value="geographic">经纬度（暂不支持，须先投影）</option>
        </select>
      </label>
    </div>

    <div class="mapping-actions">
      <button
        class="gmp-btn primary"
        data-test="mapping-submit"
        :disabled="!canSubmit"
        @click="submit"
      >
        {{ submitting ? '映射中…' : '应用映射并校验' }}
      </button>
      <span v-if="conversion" class="conversion" data-test="conversion-result">
        数值转换：有效 {{ conversion.valid }} 行 / 失败 {{ conversion.invalid }} 行 / 共
        {{ conversion.total }} 行
      </span>
    </div>
  </section>
</template>

<style scoped>
.wizard-step {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 18px 20px;
}

.wizard-step h3 {
  margin: 0 0 14px;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--gmp-accent);
  color: #0b0f14;
  font-size: 12px;
  font-weight: 700;
}

.dimension-row {
  display: flex;
  gap: 18px;
  margin-bottom: 14px;
}

.radio {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
}

.mapping-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.gmp-select,
.gmp-input {
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  color: var(--gmp-text);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
}

.mapping-actions {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 8px 18px;
  font-size: 13px;
  cursor: pointer;
}

.gmp-btn.primary {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.conversion {
  font-size: 13px;
  color: var(--gmp-text-dim);
}
</style>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  AnisotropyConfirmationPayload,
  AnisotropySuggestion,
  ProfessionalConfirmationPayload,
  VariogramModelName,
} from '../../api/types'

// 各向异性确认面板：展示候选证据（恒为诊断建议），收集人工确认并创建
// **新的**不可变确认快照。面板只发 POST confirm，绝不存在编辑确认的入口。
const props = defineProps<{
  suggestion: AnisotropySuggestion
  fittedModelNames: VariogramModelName[]
  bestModel: VariogramModelName | null
  fittedModelsSha256: string | null
  anisotropyCandidatesSha256: string | null
  dimension: '2d' | '3d'
  submitting: boolean
}>()

const emit = defineEmits<{
  (e: 'confirm', payload: ProfessionalConfirmationPayload): void
}>()

const mode = ref<'anisotropy' | 'isotropic'>(
  props.suggestion.candidates.length > 0 ? 'anisotropy' : 'isotropic',
)
const selectedRank = ref<number | null>(props.suggestion.candidates[0]?.rank ?? null)

// 手动字段：选择候选时用其证据预填，用户可再调整（校验规则与服务端契约一致）
const azimuth = ref<number | null>(null)
const dip = ref<number | null>(null)
const roll = ref<number | null>(null)
const ratioMinor = ref<number | null>(null)
const ratioVertical = ref<number | null>(null)

function asNumber(value: number | null): number | null {
  // v-model.number 清空输入时写入 ''，统一按未设置处理
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

watch(
  selectedRank,
  (rank) => {
    const candidate = props.suggestion.candidates.find((c) => c.rank === rank) ?? null
    if (!candidate) return
    azimuth.value = candidate.major_azimuth_deg
    dip.value = props.dimension === '3d' ? (candidate.major_dip_deg ?? 0) : null
    roll.value = null
    ratioMinor.value = candidate.major_minor_range_ratio ?? 1
    ratioVertical.value = candidate.major_vertical_range_ratio
  },
  { immediate: true },
)

const model = ref<VariogramModelName>(
  props.bestModel ?? props.fittedModelNames[0] ?? 'spherical',
)
const strategy = ref<'automatic_candidate' | 'manual'>('automatic_candidate')
const manualNugget = ref(0)
const manualSill = ref(1)
const manualRange = ref(100)
const note = ref('')

// 各向异性手动字段校验（与服务端 _AnisotropyConfirmation 同一规则）
const anisotropyErrors = computed<string[]>(() => {
  if (mode.value !== 'anisotropy') return []
  const errors: string[] = []
  if (selectedRank.value === null) errors.push('必须引用一个证据候选 rank')
  const az = asNumber(azimuth.value)
  if (az === null || !(az >= 0 && az < 180)) errors.push('方位角必须在 [0, 180) 内')
  const minor = asNumber(ratioMinor.value)
  if (minor === null || !(minor > 0)) errors.push('主/次变程比必须大于 0')
  // 可空字段：清空（''）按未设置处理；给出数值时必须 > 0
  const vertical = asNumber(ratioVertical.value)
  if (vertical !== null && !(vertical > 0)) errors.push('主/垂变程比必须大于 0')
  const dipValue = asNumber(dip.value)
  if (props.dimension === '2d' && dipValue !== null) errors.push('2D 数据不接受倾角')
  if (dipValue !== null && !(dipValue >= -90 && dipValue <= 90)) errors.push('倾角必须在 [-90, 90] 内')
  const rollValue = asNumber(roll.value)
  if (rollValue !== null && !(rollValue >= -180 && rollValue <= 180)) {
    errors.push('滚转角必须在 [-180, 180] 内')
  }
  if (!props.anisotropyCandidatesSha256) errors.push('缺少 anisotropy_candidates 证据哈希')
  return errors
})

const strategyErrors = computed<string[]>(() => {
  if (strategy.value === 'automatic_candidate') {
    return props.fittedModelsSha256 ? [] : ['缺少 fitted_models 证据哈希']
  }
  return manualSill.value > manualNugget.value && manualNugget.value >= 0 && manualRange.value > 0
    ? []
    : ['人工固定参数要求 sill > nugget ≥ 0 且 range > 0']
})

const noteMissing = computed(() => note.value.trim().length === 0)

const canSubmit = computed(
  () =>
    !props.submitting &&
    !noteMissing.value &&
    anisotropyErrors.value.length === 0 &&
    strategyErrors.value.length === 0,
)

function buildAnisotropy(): AnisotropyConfirmationPayload {
  if (mode.value === 'isotropic') return { keep_isotropic: true }
  return {
    keep_isotropic: false,
    azimuth_deg: asNumber(azimuth.value) ?? 0,
    dip_deg: asNumber(dip.value),
    roll_deg: asNumber(roll.value),
    major_minor_ratio: asNumber(ratioMinor.value) ?? 1,
    major_vertical_ratio: asNumber(ratioVertical.value),
    candidate_rank: selectedRank.value ?? undefined,
    anisotropy_candidates_sha256: props.anisotropyCandidatesSha256 ?? undefined,
  }
}

function submit() {
  if (!canSubmit.value) return
  const payload: ProfessionalConfirmationPayload = {
    model: model.value,
    parameter_strategy: strategy.value,
    anisotropy: buildAnisotropy(),
    note: note.value.trim(),
  }
  if (strategy.value === 'automatic_candidate') {
    payload.fitted_models_sha256 = props.fittedModelsSha256 ?? undefined
  } else {
    payload.manual_parameters = {
      nugget: manualNugget.value,
      sill: manualSill.value,
      range: manualRange.value,
    }
  }
  emit('confirm', payload)
}
</script>

<template>
  <section class="anisotropy-panel" data-test="anisotropy-panel">
    <h3>各向异性与变异函数确认</h3>
    <p class="suggestion-label" data-test="suggestion-label">诊断建议，需人工确认</p>

    <div v-if="suggestion.candidates.length" class="candidates">
      <article
        v-for="candidate in suggestion.candidates"
        :key="candidate.rank"
        class="candidate"
        data-test="candidate-evidence"
      >
        <header>
          候选 #{{ candidate.rank }} · 主方向
          <span class="mono">{{ candidate.major_direction_id }}</span>
        </header>
        <ul>
          <li>
            主方位角 {{ candidate.major_azimuth_deg }}°<template v-if="candidate.major_dip_deg !== null">
              · 倾角 {{ candidate.major_dip_deg }}°</template
            >
            · 主方向变程 {{ candidate.major_range }}
          </li>
          <li v-if="candidate.major_minor_range_ratio !== null">
            主/次变程比 {{ candidate.major_minor_range_ratio }}（次方向点对
            {{ candidate.secondary_support_pairs }}）
          </li>
          <li v-if="candidate.major_vertical_range_ratio !== null">
            主/垂变程比 {{ candidate.major_vertical_range_ratio }}（垂向点对
            {{ candidate.vertical_support_pairs }}）
          </li>
          <li>候选点对支持 {{ candidate.used_pair_count }}</li>
          <li v-if="candidate.warnings.length" class="warnings">
            稳定性警告：<code v-for="warning in candidate.warnings" :key="warning">{{ warning }}</code>
          </li>
        </ul>
      </article>
      <p v-if="suggestion.warnings.length" class="panel-warnings">
        整体警告：<code v-for="warning in suggestion.warnings" :key="warning">{{ warning }}</code>
      </p>
    </div>
    <p v-else class="no-candidate">未形成各向异性候选（方向支持不足），可保持各向同性。</p>

    <div class="mode-row">
      <label class="radio">
        <input
          type="radio"
          name="aniso-mode"
          data-test="mode-anisotropy"
          :checked="mode === 'anisotropy'"
          :disabled="!suggestion.candidates.length"
          @change="mode = 'anisotropy'"
        />
        确认各向异性（引用候选证据 + 人工参数）
      </label>
      <label class="radio">
        <input
          type="radio"
          name="aniso-mode"
          data-test="mode-isotropic"
          :checked="mode === 'isotropic'"
          @change="mode = 'isotropic'"
        />
        保持各向同性
      </label>
    </div>

    <template v-if="mode === 'anisotropy'">
      <label class="field">
        <span>证据候选（rank）</span>
        <select v-model.number="selectedRank" class="gmp-select" data-test="candidate-rank">
          <option v-for="candidate in suggestion.candidates" :key="candidate.rank" :value="candidate.rank">
            候选 #{{ candidate.rank }}
          </option>
        </select>
      </label>
      <div class="manual-grid">
        <label class="field">
          <span>方位角 azimuth（[0, 180) 度）</span>
          <input v-model.number="azimuth" type="number" step="1" class="gmp-input" data-test="manual-azimuth" />
        </label>
        <label v-if="dimension === '3d'" class="field">
          <span>倾角 dip（[-90, 90] 度，可空）</span>
          <input v-model.number="dip" type="number" step="1" class="gmp-input" data-test="manual-dip" />
        </label>
        <label v-if="dimension === '3d'" class="field">
          <span>滚转 roll（[-180, 180] 度，可空）</span>
          <input v-model.number="roll" type="number" step="1" class="gmp-input" data-test="manual-roll" />
        </label>
        <label class="field">
          <span>主/次变程比（&gt; 0）</span>
          <input
            v-model.number="ratioMinor"
            type="number"
            step="0.1"
            class="gmp-input"
            data-test="manual-ratio-minor"
          />
        </label>
        <label v-if="dimension === '3d'" class="field">
          <span>主/垂变程比（&gt; 0，可空）</span>
          <input
            v-model.number="ratioVertical"
            type="number"
            step="0.1"
            class="gmp-input"
            data-test="manual-ratio-vertical"
          />
        </label>
      </div>
      <ul v-if="anisotropyErrors.length" class="invalid-list" data-test="anisotropy-invalid">
        <li v-for="error in anisotropyErrors" :key="error">{{ error }}</li>
      </ul>
    </template>

    <div class="model-row">
      <label class="field">
        <span>变异函数模型</span>
        <select v-model="model" class="gmp-select" data-test="confirm-model">
          <option v-for="name in fittedModelNames" :key="name" :value="name">
            {{ name }}{{ name === bestModel ? '（拟合最优）' : '' }}
          </option>
        </select>
      </label>
      <label class="radio">
        <input
          type="radio"
          name="strategy"
          data-test="strategy-auto"
          :checked="strategy === 'automatic_candidate'"
          @change="strategy = 'automatic_candidate'"
        />
        自动候选证据（引用 fitted_models 哈希）
      </label>
      <label class="radio">
        <input
          type="radio"
          name="strategy"
          data-test="strategy-manual"
          :checked="strategy === 'manual'"
          @change="strategy = 'manual'"
        />
        人工固定参数（用户先验）
      </label>
    </div>

    <div v-if="strategy === 'manual'" class="manual-grid">
      <label class="field">
        <span>块金 nugget</span>
        <input v-model.number="manualNugget" type="number" step="0.01" min="0" class="gmp-input" data-test="manual-nugget" />
      </label>
      <label class="field">
        <span>总基台 sill</span>
        <input v-model.number="manualSill" type="number" step="0.01" min="0" class="gmp-input" data-test="manual-sill" />
      </label>
      <label class="field">
        <span>变程 range</span>
        <input v-model.number="manualRange" type="number" step="1" min="1" class="gmp-input" data-test="manual-range" />
      </label>
    </div>
    <ul v-if="strategyErrors.length" class="invalid-list" data-test="strategy-invalid">
      <li v-for="error in strategyErrors" :key="error">{{ error }}</li>
    </ul>

    <label class="field note-field">
      <span>确认说明 note（必填，随不可变快照保存）</span>
      <textarea v-model="note" class="gmp-input" rows="2" maxlength="2000" data-test="confirm-note" />
    </label>
    <p v-if="noteMissing" class="note-hint">确认前必须填写说明（note）。</p>

    <div class="confirm-actions">
      <button class="gmp-btn primary" data-test="confirm-submit" :disabled="!canSubmit" @click="submit">
        {{ submitting ? '创建中…' : '创建不可变确认快照' }}
      </button>
      <span class="immutability-hint">确认只创建新快照；既有确认永不修改。</span>
    </div>
  </section>
</template>

<style scoped>
.anisotropy-panel {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.anisotropy-panel h3 {
  margin: 0;
  font-size: 15px;
}

.suggestion-label {
  display: inline-block;
  align-self: flex-start;
  margin: 0;
  border: 1px solid #9a7b2d;
  background: rgba(154, 123, 45, 0.15);
  color: #e5c76b;
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
}

.candidates {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.candidate {
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}

.candidate header {
  font-weight: 600;
  margin-bottom: 6px;
}

.candidate ul {
  margin: 0;
  padding-left: 18px;
  color: var(--gmp-text-dim);
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.warnings code,
.panel-warnings code {
  color: #e5c76b;
  margin-right: 8px;
}

.panel-warnings,
.no-candidate {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.mono {
  font-family: ui-monospace, monospace;
}

.mode-row,
.model-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.radio {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
}

.manual-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.gmp-input,
.gmp-select {
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  color: var(--gmp-text);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
}

.note-field textarea {
  resize: vertical;
  font-family: inherit;
}

.note-hint {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.invalid-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12px;
  color: #ef9a9a;
}

.confirm-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.immutability-hint {
  font-size: 12px;
  color: var(--gmp-text-faint);
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
</style>

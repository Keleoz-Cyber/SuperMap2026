<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError, createProfessionalComparison } from '../../api/client'
import type { CandidateComparisonResult, CandidateRecord } from '../../api/types'

// 兼容性结论只来自服务端（§13.3：不允许前端自行判断兼容）；
// 最多固定两个候选：first 恒为当前选中候选，second 由用户指定。
const props = defineProps<{
  candidates: CandidateRecord[]
  firstResultId: string
  initialSecondResultId?: string
}>()

const secondResultId = ref<string | null>(null)
const comparison = ref<CandidateComparisonResult | null>(null)
const running = ref(false)
const error = ref<string | null>(null)
// 跨实验候选：用户粘贴的任意成果 ID（快捷按钮只覆盖同实验成功候选）
const externalId = ref('')

// 成果 ID 为 uuid4 形态；前端只校验形态、绝不自行判断兼容——
// 兼容/存在性结论一律来自后端 comparison API（404/409 错误封套原样展示）。
const UUID_RE = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/

const externalIdTrimmed = computed(() => externalId.value.trim())
const externalIdValid = computed(() => UUID_RE.test(externalIdTrimmed.value))
const externalIdInvalid = computed(() => externalIdTrimmed.value !== '' && !externalIdValid.value)

// 只有成功候选可以进入比较（后端对非成功候选 409）
const secondOptions = computed(() =>
  props.candidates.filter(
    (candidate) => candidate.status === 'succeeded' && candidate.id !== props.firstResultId,
  ),
)

const canRun = computed(() => secondResultId.value !== null && !running.value)

const metricDeltas = computed(() => {
  const deltas = comparison.value?.metric_deltas
  if (!deltas) return []
  return Object.entries(deltas).map(([name, delta]) => ({ name, delta }))
})

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

function selectSecond(id: string) {
  secondResultId.value = id
  comparison.value = null
  error.value = null
}

function applyExternal() {
  if (!externalIdValid.value) return
  selectSecond(externalIdTrimmed.value)
}

async function run() {
  if (!canRun.value || secondResultId.value === null) return
  running.value = true
  error.value = null
  comparison.value = null
  try {
    comparison.value = await createProfessionalComparison(props.firstResultId, secondResultId.value)
  } catch (e) {
    error.value = describeError(e)
  } finally {
    running.value = false
  }
}

// 当前候选切换：比较对与既有结论全部重置，绝不混用不同 first 的结论
watch(
  () => props.firstResultId,
  () => {
    secondResultId.value = null
    externalId.value = ''
    comparison.value = null
    error.value = null
  },
)

// 从模型对比页直达：预选 second 并自动提交比较
watch(
  () => props.initialSecondResultId,
  (newId) => {
    if (!newId || newId === props.firstResultId) return
    selectSecond(newId)
    externalId.value = newId
    void run()
  },
  { immediate: true },
)
</script>

<template>
  <section class="candidate-comparison" data-test="candidate-comparison">
    <header class="panel-head">
      <h3>双候选比较</h3>
      <details class="first-technical" data-test="comparison-technical-details">
        <summary>技术详情</summary>
        <span class="mono">基准候选标识：{{ firstResultId }}</span>
      </details>
    </header>

    <div class="second-picker">
      <span class="picker-label">对比候选（最多两个）：</span>
      <button
        v-for="candidate in secondOptions"
        :key="candidate.id"
        class="second-option"
        :class="{ active: candidate.id === secondResultId }"
        :data-test="`comparison-second-${candidate.id}`"
        @click="selectSecond(candidate.id)"
      >
        <span class="mono">{{ candidate.id }}</span>
      </button>
      <span v-if="secondOptions.length === 0" class="picker-empty" data-test="comparison-empty">
        实验内无其他成功候选可比较
      </span>
      <button class="gmp-btn primary" data-test="comparison-run" :disabled="!canRun" @click="run">
        {{ running ? '比较中…' : '运行比较' }}
      </button>
    </div>

    <div class="external-picker">
      <label class="picker-label" for="comparison-external-input">跨实验成果标识：</label>
      <input
        v-model="externalId"
        id="comparison-external-input"
        name="comparison-external-result"
        class="external-input mono"
        data-test="comparison-external-input"
        type="text"
        placeholder="粘贴成果标识…"
        spellcheck="false"
      />
      <button
        class="gmp-btn"
        data-test="comparison-external-apply"
        :disabled="!externalIdValid"
        @click="applyExternal"
      >
        设为对比候选
      </button>
      <span v-if="externalIdInvalid" class="external-invalid" data-test="comparison-external-invalid">
        ID 需为 UUID 形态（8-4-4-4-12 十六进制）
      </span>
      <span v-if="secondResultId" class="second-current" data-test="comparison-second-current">
        当前对比候选 <span class="mono">{{ secondResultId }}</span>
      </span>
    </div>

    <div v-if="error" class="comparison-error" data-test="comparison-error">{{ error }}</div>

    <template v-if="comparison">
      <div class="comparison-meta">
        <span data-test="comparison-fingerprint">
          比较指纹 <span class="mono">{{ comparison.comparison_fingerprint }}</span>
        </span>
      </div>

      <div v-if="comparison.compatible" class="comparison-result" data-test="comparison-compatible">
        <p class="result-line" data-test="common-valid-count">
          两项成果共同参与比较的节点 {{ comparison.common_valid_count }} 个（指标差 = 第一项 − 第二项，使用相同数据重新计算）
        </p>
        <table class="delta-table">
          <thead>
            <tr><th>指标</th><th>差值</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in metricDeltas" :key="row.name" data-test="metric-delta-row">
              <td class="mono">{{ row.name }}</td>
              <td>{{ row.delta }}</td>
            </tr>
          </tbody>
        </table>
        <p
          v-if="comparison.grid_difference_available && comparison.grid_difference"
          class="result-line"
          data-test="grid-difference"
        >
          场差摘要（共同有效网格节点 {{ comparison.grid_difference.common_valid_count }} 个）：
          均值 {{ comparison.grid_difference.mean }}，最大绝对差 {{ comparison.grid_difference.max_abs }}
        </p>
      </div>

      <div v-else class="comparison-result incompatible" data-test="comparison-incompatible">
        <p class="result-line">两候选不兼容，仅可分别独立查看；不兼容字段：</p>
        <ul class="mismatch-list" data-test="mismatch-reasons">
          <li v-for="reason in comparison.mismatches" :key="reason" class="mono" data-test="mismatch-reason">
            {{ reason }}
          </li>
        </ul>
      </div>
    </template>
  </section>
</template>

<style scoped>
.candidate-comparison {
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
  gap: 14px;
}

.panel-head h3 {
  margin: 0;
  font-size: 15px;
}

.first-technical {
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.mono {
  font-family: ui-monospace, monospace;
}

.second-picker {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.picker-label {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.picker-empty {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.external-picker {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.external-input {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 12px;
  width: 340px;
}

.external-input:focus-visible {
  outline: none;
  border-color: var(--gmp-accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--gmp-accent) 28%, transparent);
}

.external-invalid {
  font-size: 12px;
  color: #ef9a9a;
}

.second-current {
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.second-option {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}

.second-option.active {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 7px 16px;
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

.comparison-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}

.comparison-meta {
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.comparison-result {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.result-line {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.delta-table {
  border-collapse: collapse;
  font-size: 12px;
  align-self: flex-start;
}

.delta-table th,
.delta-table td {
  border: 1px solid var(--gmp-border);
  padding: 5px 12px;
  text-align: left;
}

.incompatible {
  border: 1px solid #9a7b2d;
  background: rgba(154, 123, 45, 0.1);
  border-radius: 10px;
  padding: 12px 16px;
}

.mismatch-list {
  margin: 0;
  padding-left: 20px;
  font-size: 12px;
  color: #e5c76b;
}
</style>

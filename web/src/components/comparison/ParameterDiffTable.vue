<script setup lang="ts">
// v0.9.0：参数差异表。逐参数键对比所选候选，只有真实取值不同的行
// 标记差异；绝不隐藏差异制造“看起来一致”。
import { computed } from 'vue'
import type { ComparisonCandidateSummary } from '../../api/types'
import { algorithmLabel, parameterLabel, parameterValueLabel } from '../../utils/modelingLabels'

const props = defineProps<{
  candidates: ComparisonCandidateSummary[]
}>()

const allKeys = computed(() => {
  const keys: string[] = []
  for (const c of props.candidates) {
    for (const key of Object.keys(c.parameters)) {
      if (!keys.includes(key)) keys.push(key)
    }
  }
  return keys.sort()
})

function display(key: string, value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (Array.isArray(value)) return value.map((item) => parameterValueLabel(key, item)).join(', ')
  return parameterValueLabel(key, value)
}

function differs(key: string): boolean {
  const values = props.candidates.map((c) => display(key, c.parameters[key]))
  return new Set(values).size > 1
}

function candidateLabel(c: ComparisonCandidateSummary): string {
  return `${algorithmLabel(c.algorithm)}·${c.candidate_result_id.slice(0, 8)}`
}
</script>

<template>
  <div class="param-diff" data-test="param-diff-table">
    <table>
      <thead>
        <tr>
          <th>参数</th>
          <th v-for="c in candidates" :key="c.candidate_result_id">{{ candidateLabel(c) }}</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="key in allKeys"
          :key="key"
          data-test="param-diff-row"
          :data-differs="differs(key) ? 'true' : 'false'"
          :class="{ differs: differs(key) }"
        >
          <td class="param-key">{{ parameterLabel(key) }}</td>
          <td v-for="c in candidates" :key="c.candidate_result_id">
            {{ display(key, c.parameters[key]) }}
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.param-diff {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--s1-font-sm);
}

th,
td {
  border: 1px solid var(--s1-border);
  padding: 5px 10px;
  text-align: left;
}

th {
  background: var(--s1-surface-2);
  color: var(--s1-text-dim);
  font-weight: 600;
}

.param-key {
  color: var(--s1-text-dim);
}

tr.differs td {
  background: var(--s1-gold-ghost);
}
</style>

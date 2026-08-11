<script setup lang="ts">
import { computed } from 'vue'
import type { CandidateRecord } from '../../api/types'

const props = defineProps<{
  candidates: CandidateRecord[]
  publicMetrics: Record<string, number>
}>()

// 默认排序：成功候选按公共有效 RMSE 升序；失败候选永远保留在表格中、
// 排在成功候选之后并展示错误码（失败也是证据，不丢弃）。
const sorted = computed(() =>
  [...props.candidates].sort((a, b) => {
    if ((a.status === 'succeeded') !== (b.status === 'succeeded')) {
      return a.status === 'succeeded' ? -1 : 1
    }
    const rmseA = a.metrics.rmse ?? Number.POSITIVE_INFINITY
    const rmseB = b.metrics.rmse ?? Number.POSITIVE_INFINITY
    return rmseA - rmseB
  }),
)

function fmt(value: number | undefined, digits = 3): string {
  return value === undefined ? '—' : value.toFixed(digits)
}

function percent(value: number | undefined): string {
  return value === undefined ? '—' : `${(value * 100).toFixed(1)}%`
}

// number 精度语义：12 位有效数字截断浮点噪声长尾（0.30000000000000004 → 0.3），
// 整数与常规小数保持原样。
function formatParamNumber(value: number): string {
  return Number.isFinite(value) ? String(Number(value.toPrecision(12))) : String(value)
}

// 确定性递归格式化：object 按键字典序、array 紧凑逗号分隔、null/boolean/number/string
// 各有确定输出——专业候选的嵌套参数（neighborhood/anisotropy）绝不退化为 [object Object]。
function formatParamValue(value: unknown): string {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'number') return formatParamNumber(value)
  if (typeof value === 'boolean') return String(value)
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return `[${value.map((item) => formatParamValue(item)).join(',')}]`
  if (typeof value === 'object') {
    const entries = Object.keys(value as Record<string, unknown>)
      .sort()
      .map((key) => `${key}:${formatParamValue((value as Record<string, unknown>)[key])}`)
    return `{${entries.join(',')}}`
  }
  return String(value)
}

function paramsPreview(parameters: Record<string, unknown>): string {
  return Object.keys(parameters)
    .sort()
    .map((key) => `${key}=${formatParamValue(parameters[key])}`)
    .join(' ')
}
</script>

<template>
  <section class="leaderboard" data-test="leaderboard">
    <div class="board-head">
      <h3>本实验候选排行榜</h3>
      <span class="public" data-test="public-metrics">
        仅比较当前实验本次运行的参数组合 · 公共有效点
        {{ publicMetrics.common_valid_count ?? '—' }}（公共掩膜复算，NoData 不换排名优势）
      </span>
    </div>

    <table class="board-table">
      <thead>
        <tr>
          <th>#</th>
          <th>参数</th>
          <th>RMSE</th>
          <th>MAE</th>
          <th>R²</th>
          <th>Bias</th>
          <th>覆盖率</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="(candidate, idx) in sorted"
          :key="candidate.id"
          :class="{ failed: candidate.status !== 'succeeded' }"
          data-test="candidate-row"
        >
          <td>{{ idx + 1 }}</td>
          <td class="mono">{{ paramsPreview(candidate.parameters) }}</td>
          <td>{{ fmt(candidate.metrics.rmse) }}</td>
          <td>{{ fmt(candidate.metrics.mae) }}</td>
          <td>{{ fmt(candidate.metrics.r2) }}</td>
          <td>{{ fmt(candidate.metrics.bias) }}</td>
          <td>{{ percent(candidate.metrics.coverage) }}</td>
          <td>
            <span v-if="candidate.status === 'succeeded'" class="status ok">
              成功
              <router-link class="open-result" :to="`/results/${candidate.id}`" data-test="open-result">
                成果
              </router-link>
            </span>
            <span v-else class="status bad" :title="candidate.error?.message">
              失败 · {{ candidate.error?.code ?? 'UNKNOWN' }}
            </span>
          </td>
        </tr>
        <tr v-if="sorted.length === 0">
          <td colspan="8" class="empty">尚无候选结果</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.leaderboard {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
}

.board-head {
  display: flex;
  align-items: baseline;
  gap: 14px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.board-head h3 {
  margin: 0;
  font-size: 15px;
}

.public {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.board-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.board-table th,
.board-table td {
  border: 1px solid var(--gmp-border);
  padding: 6px 8px;
  text-align: left;
}

.board-table th {
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
}

.mono {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}

tr.failed {
  opacity: 0.75;
}

.status.ok {
  color: #7fd6a4;
}

.open-result {
  margin-left: 8px;
  color: var(--gmp-accent);
  text-decoration: none;
}

.status.bad {
  color: #ef9a9a;
}

.empty {
  text-align: center;
  color: var(--gmp-text-faint);
  padding: 16px;
}
</style>

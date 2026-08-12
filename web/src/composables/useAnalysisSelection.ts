// v0.9.0：图表—三维分析选择控制器。持有当前分析选择（轴/区间）与
// 数据/成果身份上下文；上下文切换立即清空旧选择，身份不匹配与非法
// 区间一律拒绝。控制器只存选择语义，绝不缓存服务端数据。
import { computed, ref } from 'vue'
import type { AnalysisSelection } from '../components/analysis/analysisTypes'

export interface AnalysisSelectionContext {
  datasetId: string
  resultId: string | null
}

function isFinitePair(range: [number, number] | undefined): range is [number, number] {
  return (
    Array.isArray(range) &&
    range.length === 2 &&
    Number.isFinite(range[0]) &&
    Number.isFinite(range[1]) &&
    range[0] <= range[1]
  )
}

function validate(selection: AnalysisSelection): boolean {
  if (selection.axis === 'xy') {
    return isFinitePair(selection.x_range) && isFinitePair(selection.y_range)
  }
  return isFinitePair(selection.range)
}

export function createAnalysisSelectionController() {
  const context = ref<AnalysisSelectionContext | null>(null)
  const current = ref<AnalysisSelection | null>(null)

  const activeContext = computed(() => context.value)

  function setContext(next: AnalysisSelectionContext) {
    const prev = context.value
    context.value = next
    if (!prev || prev.datasetId !== next.datasetId || prev.resultId !== next.resultId) {
      current.value = null
    }
  }

  function select(selection: AnalysisSelection): boolean {
    const ctx = context.value
    if (!ctx) return false
    if (selection.dataset_id !== ctx.datasetId) return false
    if ((selection.result_id ?? null) !== ctx.resultId) return false
    if (!validate(selection)) return false
    current.value = selection
    return true
  }

  function clear() {
    current.value = null
  }

  function toRouteQuery(): Record<string, string> {
    const sel = current.value
    const ctx = context.value
    if (!sel || !ctx) return {}
    const query: Record<string, string> = { dataset: ctx.datasetId }
    if (sel.axis === 'xy') {
      query.axis = 'xy'
      query.x_range = `${sel.x_range[0]},${sel.x_range[1]}`
      query.y_range = `${sel.y_range[0]},${sel.y_range[1]}`
    } else {
      query.axis = sel.axis
      query.range = `${sel.range[0]},${sel.range[1]}`
    }
    return query
  }

  return { context: activeContext, current, setContext, select, clear, toRouteQuery }
}

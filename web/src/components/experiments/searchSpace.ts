// 网格搜索组合数的前端预览逻辑。后端（platform/experiments.py，硬上限 50）
// 仍是唯一权威；这里仅用于提交前可见反馈。

export const WARN_GRID_CANDIDATES = 30
export const MAX_GRID_CANDIDATES = 50

export function combinationCount(parameters: Record<string, unknown>, searchMode: 'manual' | 'grid'): number {
  if (searchMode === 'manual') return 1
  const values = Object.values(parameters).filter((v): v is unknown[] => Array.isArray(v))
  if (values.length === 0) return 0
  return values.reduce((acc, list) => acc * Math.max(list.length, 0), 1)
}

export type SearchSpaceState = 'ok' | 'warn' | 'blocked'

export function searchSpaceState(count: number): SearchSpaceState {
  if (count > MAX_GRID_CANDIDATES || count <= 0) return 'blocked'
  if (count > WARN_GRID_CANDIDATES) return 'warn'
  return 'ok'
}

// 解析 "1, 2, 3" 形式的离散候选值输入；非法项返回 null（调用方提示）。
export function parseNumberList(text: string): number[] | null {
  const parts = text
    .split(/[,，\s]+/)
    .map((p) => p.trim())
    .filter(Boolean)
  if (parts.length === 0) return []
  const numbers = parts.map(Number)
  if (numbers.some((n) => !Number.isFinite(n)) || numbers.some((n) => n <= 0)) return null
  return numbers
}

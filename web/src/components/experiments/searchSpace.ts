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

// ---------------------------------------------------------------------------
// 数据集实验预设：领域适配器数据集（如微震第二案例）的调参默认值。
// 与 config/presets/microseismic.json 的 search_grids 保持同一事实；
// 通用数据集解析为 null，保持现有默认参数体验。
export type VariogramModel = 'spherical' | 'exponential' | 'gaussian'

export interface ExperimentPreset {
  key: 'microseismic'
  // 手动模式 z_scale 数值默认值；网格模式逗号分隔候选
  zScaleManualDefault: number
  idwGrid: { power: number[]; neighborCount: number[]; zScale: number[] }
  krigingGrid: { models: VariogramModel[]; neighborCount: number[]; zScale: number[] }
}

export const Z_SCALE_HINT = '垂向距离缩放只改变实验中距离的计算方式；它本身不能说明地下介质存在方向性。'

export const MICROSEISMIC_EXPERIMENT_PRESET: ExperimentPreset = {
  key: 'microseismic',
  zScaleManualDefault: 1,
  idwGrid: { power: [1, 2, 3], neighborCount: [8, 16, 24, 32], zScale: [0.5, 1, 2] },
  krigingGrid: {
    models: ['spherical', 'exponential', 'gaussian'],
    neighborCount: [12, 24, 36],
    zScale: [0.5, 1, 2],
  },
}

export function resolveDatasetPreset(
  profile: Record<string, unknown> | null | undefined,
): ExperimentPreset | null {
  if (profile?.source_kind === 'microseismic_dat_bundle') return MICROSEISMIC_EXPERIMENT_PRESET
  return null
}

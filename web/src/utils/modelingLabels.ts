const ALGORITHMS: Record<string, string> = {
  idw: 'IDW（反距离加权）',
  ordinary_kriging: '普通克里金',
}

export function algorithmLabel(id: string): string {
  return ALGORITHMS[id] ?? id.slice(0, 64)
}

const PARAM_LABELS: Record<string, string> = {
  power: '幂参数',
  neighbor_count: '邻域点数',
  variogram_model: '变异函数',
  variogram_nugget: '块金',
  variogram_sill: '基台',
  variogram_range: '变程',
  z_scale: 'Z 缩放',
  search_radius: '搜索半径',
}

const VARIOGRAM_MODELS: Record<string, string> = {
  spherical: '球状',
  exponential: '指数',
  gaussian: '高斯',
  linear: '线性',
}

const numberFormatter = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 12 })

function formatParamValue(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? numberFormatter.format(value) : String(value)
  }
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string') return value
  return String(value).slice(0, 80)
}

export function parameterSummary(
  algorithm: string,
  params: Record<string, unknown>,
): string[] {
  void algorithm
  const knownKeys = Object.keys(params).filter((k) => k in PARAM_LABELS)
  if (knownKeys.length > 0) {
    return knownKeys.sort().map((key) => {
      const label = PARAM_LABELS[key]
      const raw = params[key]
      if (key === 'variogram_model' && typeof raw === 'string' && raw in VARIOGRAM_MODELS) {
        return `${label} ${VARIOGRAM_MODELS[raw]}`
      }
      return `${label} ${formatParamValue(raw)}`
    })
  }
  return Object.keys(params)
    .sort()
    .slice(0, 5)
    .map((key) => `${key} ${formatParamValue(params[key])}`)
}

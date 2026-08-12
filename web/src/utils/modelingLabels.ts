const ALGORITHMS: Record<string, string> = {
  idw: 'IDW（反距离加权）',
  ordinary_kriging: '普通克里金',
  dsi_like: 'DSI-like 离散平滑插值',
}

const COORDINATES: Record<string, string> = {
  local_linear: '局部线性米制坐标',
  local_projected: '局部投影坐标',
}

const PROPERTIES: Record<string, string> = {
  RHO: '电阻率',
  Vx: '微震速度',
  CH4_content: '瓦斯含量',
}

const UNITS: Record<string, string> = {
  ohm_m: 'Ω·m',
}

export function algorithmLabel(id: string): string {
  return ALGORITHMS[id] ?? id.slice(0, 64)
}

export function coordinateLabel(id: string): string {
  return COORDINATES[id] ?? '局部坐标'
}

export function propertyLabel(id: string): string {
  return PROPERTIES[id] ?? id.slice(0, 64)
}

export function unitLabel(id: string): string {
  return UNITS[id] ?? id.slice(0, 32)
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
  init_power: '初始场幂次',
  neighbor_connectivity: '邻域连接数',
  smoothing_strength: '平滑强度',
  max_iterations: '最大迭代次数',
  convergence_tolerance: '收敛容差',
  hard_constraints: '观测点约束',
}

const VARIOGRAM_MODELS: Record<string, string> = {
  spherical: '球状',
  exponential: '指数',
  gaussian: '高斯',
  linear: '线性',
}

export function parameterLabel(key: string): string {
  return PARAM_LABELS[key] ?? key.replaceAll('_', ' ')
}

export function parameterValueLabel(key: string, value: unknown): string {
  if (key === 'variogram_model' && typeof value === 'string' && value in VARIOGRAM_MODELS) {
    return VARIOGRAM_MODELS[value]
  }
  return formatParamValue(value)
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
      const label = parameterLabel(key)
      const raw = params[key]
      return `${label} ${parameterValueLabel(key, raw)}`
    })
  }
  return Object.keys(params)
    .sort()
    .slice(0, 5)
    .map((key) => `${key} ${formatParamValue(params[key])}`)
}

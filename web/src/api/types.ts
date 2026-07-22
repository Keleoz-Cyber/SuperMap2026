// 与 FastAPI 后端契约一一对应的类型定义（字段名以后端实际返回为准）。

export interface HealthResponse {
  status: string
  version: string
  time: string
}

export interface CaseSummary {
  case_id: string
  title: string
  data_form: string
  status: string
  coordinate: string
  unit_note: string
  v03_stage: string
  links: {
    detail: string | null
    publish_status: string | null
  }
}

export interface CasesResponse {
  cases: CaseSummary[]
}

export interface ModelMetrics {
  model?: string
  n_total: number
  n_valid: number
  n_nodata: number
  coverage_rate: number
  mae: number
  rmse: number
  r2: number
  median_abs_error: number
  mean_abs_relative_error: number
  median_abs_relative_error: number
  log10_rmse: number
  bias: number
  p90_abs_error: number
}

export type ModelRole = 'default' | 'comparison' | 'candidate' | 'not_formal_candidate' | string

export interface ModelEntry {
  model_id: string
  display_name: string
  method: string
  resolution_xy_m: number
  neighbor_count: number
  role: ModelRole
  parameters: Record<string, string | number>
  metrics: ModelMetrics | null
}

export interface SupermapResult {
  dataset: string
  model_id?: string
  dataset_type: string
  method?: string
  resolution_xy_m?: number
  neighbor_count?: number
  rows?: number
  columns?: number
  bands?: number
  value_min?: number
  value_max?: number
  status: string
  result_category: string
  openable?: boolean
  threshold_demo?: {
    min_visible_rho: number
    note: string
  }
  manual_evidence?: string[]
  error_evidence?: string
}

export interface IssueEntry {
  issue_id?: string
  severity: string
  code?: string
  message?: string
  description?: string
  scope?: string
  evidence?: string
  blocking?: boolean
  current_handling?: string
}

export interface DatasetSummary {
  name: string
  rows: number
  fields?: string
  spatial_columns?: number
}

export interface RhoCaseDetail {
  case_id: string
  title: string
  coordinate: {
    type: string
    epsg: number | null
    note: string
  }
  datasets: DatasetSummary[]
  validation_split: {
    spatial_column_overlap: number
    seed: string
  }
  metric_expectations: {
    common_valid: number
    common_nodata: number
    coverage_rate: number
  }
  models: ModelEntry[]
  baseline_comparison: {
    passed: boolean
    differences: unknown[]
    models_checked: number
  } | null
  metric_source: string
  supermap: {
    version: string
    datasource_alias: string
    dataset_api: string
    results: SupermapResult[]
  }
  views: Array<Record<string, unknown>>
  issues: IssueEntry[]
}

export interface ServiceInfo {
  name: string
  service_type: string
  url: string
  reachable: boolean
  http_status?: number | null
  error: string | null
}

export interface DatasetInfo {
  type: string
  width: number
  height: number
  minValue: number
  maxValue: number
  bounds: {
    left: number
    right: number
    top: number
    bottom: number
    [key: string]: unknown
  }
  prjCoordSys: string
}

export interface ServiceCheck {
  name: string
  service_type: string
  url: string
  reachable: boolean
  http_status: number | null
  detail: {
    datasource_names?: string[]
    dataset_count?: number
    dataset_info?: DatasetInfo
    mismatches?: string[]
    scene_names?: string[]
    layers?: Array<{
      name: string
      layer3DType: string
      visible: boolean
    }>
  }
  error: string | null
}

export interface EvidenceState {
  state: string
  ok: boolean
  source: string
  checked_at: string | null
  detail: string | null
}

export interface FailedResult {
  dataset: string
  status: string
  result_category: string
  error_evidence: string | null
}

export interface PublishStatus {
  case_id: string
  result_id: string
  iserver_available: boolean
  iserver: {
    base_url: string
    reachable: boolean
    http_status: number | null
    version?: string | null
    services: ServiceInfo[]
    error?: string | null
  }
  service_checks: ServiceCheck[]
  evidence_chain: {
    result_id: string
    states: EvidenceState[]
  }
  failed_results: FailedResult[]
  planned_services: {
    data: string
    map: string
    realspace: string
    scene_name: string
    volume: VolumeServicePlan
  }
}

export interface VolumeServicePlan {
  url: string
  service_name: string
  scene_name: string
  available: boolean
  layers: Array<{ name: string | null; layer3DType: string | null; visible: boolean | null }>
  note: string
}

export interface RhoPoints {
  case_id: string
  source: string
  source_path: string
  sha256: string
  decimate: number
  count: number
  served: number
  value_field: string
  unit_note: string
  x: number[]
  y: number[]
  z: number[]
  values: number[]
  value_range: [number, number]
  x_range: [number, number]
  y_range: [number, number]
  z_range: [number, number]
}

export interface BrowserLoadReport {
  case_id: string
  result_id: string
  service_url: string
  scene_name: string
  layer_count: number
  note: string
}

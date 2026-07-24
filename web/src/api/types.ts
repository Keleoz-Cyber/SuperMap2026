// 与 FastAPI 后端契约一一对应的类型定义（字段名以后端实际返回为准）。

export interface HealthResponse {
  status: string
  version: string
  time: string
}

export interface CaseSummary {
  case_id: string
  title: string
  // legacy 卡片专有字段；上传案例卡片不携带
  data_form?: string
  status: string
  coordinate?: string
  unit_note?: string
  v03_stage?: string
  // v0.4：builtin_legacy（内置电阻率等）或 upload（持久化上传案例）
  source_kind?: 'builtin_legacy' | 'upload'
  case_type?: string
  created_at?: string
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

export interface VoxelCells {
  case_id: string
  result_id: string
  source: string
  local_cache_dir: string
  local_cache_present: boolean
  local_cache_note: string
  service_url: string
  tile_files: number
  fetched_bytes: number
  count: number
  value_field: string
  unit_note: string
  x: number[]
  y: number[]
  z: number[]
  values: number[]
  x_range: [number, number]
  y_range: [number, number]
  z_range: [number, number]
  value_range: [number, number]
  registry_facts: {
    rows_columns_bands: Array<number | null>
    cell_exact_value_range: Array<number | null>
    note: string
  }
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
  success: boolean
  render_kind: 'iserver_scene' | 's3m_voxel_cache' | 'fallback_points'
  validated_count: number
  note: string
}

// ---------------- v0.4 通用建模平台契约（与后端 schemas 一一对应） ----------------

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details: Record<string, unknown>
  }
}

export type DatasetStatus = 'uploaded' | 'mapped' | 'validated' | 'blocked'

export interface PlatformCaseRecord {
  id: string
  name: string
  case_type: string
  config: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface DatasetVersionRecord {
  id: string
  case_id: string
  version: number
  status: DatasetStatus
  source_path: string
  standardized_path: string | null
  profile: Record<string, unknown>
  created_at: string
}

export interface InspectionColumn {
  name: string
  inferred_type: string
}

export interface InspectionResult {
  dataset_id: string
  case_id: string
  suffix: string
  sheet: string | null
  sheets?: string[]
  columns: InspectionColumn[]
  preview_rows: Record<string, unknown>[]
  row_count: number
  candidate_mapping: Partial<Record<'x' | 'y' | 'z' | 'value' | 'value_name', string>>
  limits: { max_upload_bytes: number; max_upload_rows: number }
  profile: Record<string, unknown>
}

export interface FieldMappingPayload {
  dimension: '2d' | '3d'
  x: string
  y: string
  z?: string | null
  value: string
  value_name: string
  value_unit?: string | null
  coordinate_kind: 'local_linear' | 'projected' | 'geographic'
}

export interface QualityIssue {
  code: string
  kind: 'blocker' | 'warning'
  message: string
  details: Record<string, unknown>
}

export interface QualityCheck {
  code: string
  kind: string
  passed: boolean
}

export interface QualityReport {
  status: 'ready' | 'warnings' | 'blocked'
  checks: QualityCheck[]
  issues: QualityIssue[]
  statistics: {
    ranges: Record<string, [number, number] | null>
    unique_coordinate_count: number
    duplicate_count: number
    conflict_count: number
  }
  valid_row_count: number
  invalid_row_count: number
  row_count: number
  source_sha256: string
  standardized_sha256: string
  confirmed: boolean
  confirmed_issue_codes: string[]
}

// ---------------- v0.4 实验 / 运行 / 候选契约 ----------------

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled' | 'interrupted'

export interface RunMetrics {
  current_candidate?: number | null
  completed?: number
  total?: number
  failed?: number
  cancel_requested?: boolean
  public_metrics?: Record<string, number>
}

export interface RunRecord {
  id: string
  experiment_id: string
  status: RunStatus
  error_code: string | null
  metrics: RunMetrics
  retry_of_run_id: string | null
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
}

export interface ValidationSpecPayload {
  method: 'spatial_kfold' | 'spatial_holdout'
  folds: number
  seed: number
  holdout_fraction: number
}

export interface GridSpecPayload {
  bounds: Array<[number, number]>
  resolution: number[]
  max_cells?: number
}

export interface ExperimentCreatePayload {
  case_id: string
  name: string
  algorithm: 'idw' | 'kriging'
  dataset_version_id: string
  search_mode: 'manual' | 'grid'
  parameters: Record<string, unknown>
  validation: ValidationSpecPayload
  grid?: GridSpecPayload | null
}

export interface ExperimentRecord {
  id: string
  case_id: string
  name: string
  params: ExperimentCreatePayload
  created_at: string
  updated_at: string
}

export interface CandidateMetrics {
  n_total?: number
  n_valid?: number
  n_nodata?: number
  coverage?: number
  mae?: number
  rmse?: number
  r2?: number
  bias?: number
}

export interface CandidateRecord {
  id: string
  fingerprint: string
  status: 'succeeded' | 'failed' | string
  parameters: Record<string, unknown>
  metrics: CandidateMetrics
  error: { code: string; message: string } | null
}

export interface CandidatesResponse {
  experiment_id: string
  candidates: CandidateRecord[]
  public_metrics: Record<string, number>
  latest_run: RunRecord | null
}

export interface CaseDatasetsResponse {
  datasets: DatasetVersionRecord[]
}

// ---------------- v0.4 成果 / 切片 / 选择 / 导出 / 发布契约 ----------------

export interface ResultMetadata {
  result_id: string
  run_id: string
  experiment_id: string
  algorithm: string
  parameters: Record<string, unknown>
  dimension: '2d' | '3d'
  shape: number[]
  cell_count: number
  bounds: Array<[number, number]>
  resolution: number[]
  value_range: [number | null, number | null]
  nodata_count: number
  grid_sha256: string
  source_sha256: string | null
  standardized_sha256: string | null
  fingerprint: string
  validation: Record<string, unknown> | null
  created_at: string
}

export interface ResultPreview {
  result_id: string
  dimension: '2d' | '3d'
  original_cell_count: number
  served_cell_count: number
  stride: number
  x: number[]
  y: number[]
  z: number[] | null
  values: number[]
  is_nodata: boolean[]
  value_range: [number | null, number | null]
}

export interface SliceResponse {
  result_id: string
  fixed_axis: 'x' | 'y' | 'z'
  fixed_coordinate: number
  axes_names: string[]
  axes: number[][]
  matrix: Array<Array<number | null>>
  nodata_mask: boolean[][]
  value_range: [number | null, number | null]
}

export interface FormalSelectionRecord {
  id: string
  case_id: string
  candidate_result_id: string
  selected_by: string | null
  note: string
  created_at: string
}

export interface FormalSelectionsResponse {
  case_id: string
  selections: FormalSelectionRecord[]
}

export interface ExportRecord {
  id: string
  candidate_result_id: string
  case_id: string
  package_sha256: string
  file_count: number
  files: string[]
  manifest: Record<string, unknown>
}

export interface PublicationRecord {
  id: string
  export_id: string
  status: 'manual_required' | 'queued' | 'published' | 'failed' | 'not_requested' | string
  evidence: {
    export_id: string
    package: string
    manual_instruction: string
    iserver_rest_publish_status: string
  }
}

export interface DatasetPoints {
  dataset_id: string
  dimension: '2d' | '3d'
  count: number
  served: number
  decimate: number
  x: number[]
  y: number[]
  z: number[] | null
  values: number[]
  value_range: [number, number] | null
  value_name: string | null
  source_sha256: string | null
}

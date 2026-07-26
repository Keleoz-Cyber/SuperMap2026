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
  local_cache_label: string
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
  source_label: string
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
  // 白名单 DTO：内部路径（source/standardized/grid/package）一律不下发
  id: string
  case_id: string
  version: number
  status: DatasetStatus
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
  status: 'passed' | 'warnings' | 'blocked'
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
  algorithm: 'idw' | 'ordinary_kriging'
  dataset_version_id: string
  search_mode: 'manual' | 'grid'
  parameters: Record<string, unknown>
  validation: ValidationSpecPayload
  grid?: GridSpecPayload | null
  // v0.6 专业输入（三字段全缺时行为与 v0.4 逐位一致）：
  // professional_confirmation_id 仅普通 Kriging 可用（IDW 携带 409）；
  // neighborhood / empirical_uncertainty 为契约原始载荷，严格校验在服务端。
  professional_confirmation_id?: string
  neighborhood?: NeighborhoodPayload
  empirical_uncertainty?: EmpiricalUncertaintyPayload
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
  // 公共口径：所有候选在同一公共掩膜上复算（排名依据）
  common_valid_count?: number
  // 候选自身口径：覆盖率展示，报 NoData 不换排名优势
  candidate_valid_count?: number
  candidate_nodata_count?: number
  total_count?: number
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
  // 成果归属链：result → run → experiment → dataset（Task 10 起服务端下发）
  dataset_version_id: string
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

// ---------------- v0.5 微震 DAT 导入契约（与 routes/microseismic.py 一一对应） ----------------

export interface MicroseismicLayerCounts {
  source_records: number
  finite_records: number
  invalid_records: number
  rejected_3sigma: number
  accepted_modeling: number
  aggregated_nodes: number
}

export interface MicroseismicGoldenCheck {
  name: string
  passed: boolean
  expected: unknown
  actual: unknown
}

export interface MicroseismicGolden {
  passed: boolean
  checks: MicroseismicGoldenCheck[]
}

export interface MicroseismicAggregation {
  conflict_group_count: number
  conflict_row_count: number
  collapsed_row_count: number
  max_value_range: number
}

export interface MicroseismicThreeSigma {
  threshold: number
  ddof: number
  depth_mean: number
  depth_std: number
  vx_mean: number
  vx_std: number
}

export interface MicroseismicCoordinates {
  coord_type: string
  depth_rule: string
  z_rule: string
  vx_unit: string
  absolute_crs: string
}

export interface MicroseismicSourceFile {
  file_name: string
  sha256: string
  point_id: string
  line_id: string
  source_record_count: number
}

// 派生工件的公开身份：逻辑名 + 行数 + 哈希，绝不含服务器路径
export interface MicroseismicArtifactIdentity {
  file: string
  rows: number
  sha256: string
}

export interface MicroseismicDownstreamGates {
  geometry_blocked: boolean
  cleaning_blocked: boolean
  interpolation_blocked: boolean
}

// 导入合同固定的自动映射（不经用户选择）
export interface MicroseismicMapping {
  dimension: '2d' | '3d'
  x: string
  y: string
  z: string | null
  value: string
  value_name: string
  value_unit: string | null
  coordinate_kind: 'local_linear' | 'projected' | 'geographic'
}

export interface MicroseismicImportProfile {
  source_kind: string
  dimension: string
  mapping: MicroseismicMapping
  rule_version: string
  adapter_version: string
  aggregation_method: string
  golden: MicroseismicGolden
  layer_counts: MicroseismicLayerCounts
  aggregation: MicroseismicAggregation
  source_files: MicroseismicSourceFile[]
  derivation_report: string
  modeling_provenance: string
  row_count: number
  valid_row_count: number
  invalid_row_count: number
  standardized_sha256: string
}

// POST /api/cases/{case_id}/microseismic-imports → 201 public_dataset
export interface MicroseismicImportResponse {
  id: string
  case_id: string
  version: number
  status: DatasetStatus
  created_at: string
  profile: MicroseismicImportProfile
}

// GET /api/datasets/{id}/derivation → 白名单 17 键
export interface MicroseismicDerivation {
  dataset_id: string
  case_id: string
  status: DatasetStatus
  source_kind: string
  rule_version: string
  adapter_version: string
  aggregation_method: string
  layer_counts: MicroseismicLayerCounts
  line_counts: Record<string, number>
  three_sigma: MicroseismicThreeSigma
  aggregation: MicroseismicAggregation
  coordinates: MicroseismicCoordinates
  golden: MicroseismicGolden
  validation_passed: boolean
  downstream_gates: MicroseismicDownstreamGates
  source_files: MicroseismicSourceFile[]
  artifacts: Record<string, MicroseismicArtifactIdentity>
}

// GET /api/datasets/{id}/derivation/points?layer=…&decimate=…
export type MicroseismicPointLayerName = 'accepted' | 'rejected' | 'aggregated'

export interface MicroseismicPointLayer {
  dataset_id: string
  layer: MicroseismicPointLayerName
  total: number
  returned: number
  decimate: number
  x: number[]
  y: number[]
  z: number[]
  vx: number[]
  // accepted / rejected 层
  sample_id?: string[]
  // rejected 层
  filter_reason?: string[]
  depth_zscore?: number[]
  vx_zscore?: number[]
  // aggregated 层
  sample_count?: number[]
  source_sample_ids?: string[][]
  vx_min?: number[]
  vx_max?: number[]
  vx_std?: Array<number | null>
}

// ---------------- v0.6 专业诊断契约（与 routes/professional.py + public_dto.py 一一对应） ----------------

// 能力/支持状态的判别联合：「不适用/不支持」是类型化状态，绝不用空值或 0 表达
export type ProfessionalCapabilityState = 'supported' | 'not_applicable'
export type DirectionFitStatus = 'supported' | 'unsupported_insufficient_pairs'

// POST /api/datasets/{id}/professional-diagnostics 请求体（严格校验在服务端契约层）
export interface DirectionPayload {
  dimension: '2d' | '3d'
  azimuth_deg: number
  dip_deg?: number | null
  azimuth_tolerance_deg?: number
  dip_tolerance_deg?: number | null
}

export interface VariogramDiagnosticPayload {
  lag_count?: number
  max_distance?: number | null
  min_pairs_per_bin?: number
  max_pairs?: number
  directions?: DirectionPayload[]
}

export interface ProfessionalDiagnosisRequestPayload {
  variogram?: VariogramDiagnosticPayload
}

// POST 诊断响应：202 新任务 / 200 幂等复用（reused=true 时 job_id 为 null）
export interface ProfessionalDiagnosisAccepted {
  diagnosis_id: string
  job_id: string | null
  status: RunStatus
  reused: boolean
}

// manifest 公开摘要：工件只给逻辑名 + file/sha256/bytes，绝不含服务器目录
export interface ManifestArtifactSummary {
  file: string | null
  sha256: string | null
  bytes: number | null
}

export interface ProfessionalManifestSummary {
  version: number | null
  fingerprint: string | null
  artifacts: Record<string, ManifestArtifactSummary>
  created_at: string | null
  summary?: {
    fitted_models?: Array<'spherical' | 'exponential' | 'gaussian'>
    best_model?: 'spherical' | 'exponential' | 'gaussian'
    omni_used_bin_count?: number
    direction_count?: number
    supported_direction_count?: number
    skipped_direction_ids?: string[]
    candidate_ranks?: number[]
    warnings?: string[]
  }
}

export interface ProfessionalErrorBody {
  code: string
  message: string
}

export interface ProfessionalDiagnosisRecord {
  id: string
  dataset_version_id: string
  status: RunStatus
  fingerprint: string
  config: { variogram?: VariogramDiagnosticPayload } & Record<string, unknown>
  manifest: ProfessionalManifestSummary | null
  error: ProfessionalErrorBody | null
  created_at: string
  updated_at: string
  finished_at: string | null
}

// 分析任务公开 DTO（与插值 run 同一生命周期合同；retry 产生新身份）
export interface AnalysisJobRecord {
  id: string
  job_kind: string
  subject_type: string
  subject_id: string
  request_fingerprint: string
  status: RunStatus
  retry_of_job_id: string | null
  progress: Record<string, unknown>
  error: ProfessionalErrorBody | null
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
}

// 大表有界内联：decimate 抽稀 + 行数硬上限（完整工件走白名单下载）
export interface BoundedRows<T> {
  total: number
  returned: number
  decimate: number
  rows: T[]
}

export interface VariogramBin {
  bin_index: number
  lower_distance: number
  upper_distance: number
  center_distance: number
  // 空 bin 的 mean_distance 为 null（NaN 在公共出口序列化为 null）
  mean_distance: number | null
  semivariance: number | null
  pair_count: number
  used_for_fit: boolean
  exclusion_reason: string | null
}

export interface DirectionalVariogramBin extends VariogramBin {
  direction_id: string
  azimuth_deg: number
  dip_deg: number | null
  azimuth_tolerance_deg: number
  dip_tolerance_deg: number | null
}

export type VariogramModelName = 'spherical' | 'exponential' | 'gaussian'

export interface FittedVariogramModel {
  model: VariogramModelName
  nugget: number
  partial_sill: number
  sill: number
  range: number
  weighted_sse: number
  converged: boolean
  parameter_origin:
    | 'automatic_candidate'
    | 'manual_confirmed'
    | 'legacy_auto_fold_fit'
    | 'final_full_data_fit'
  used_bin_indices: number[]
  bounds: Record<string, [number, number]>
  residuals: number[]
}

export interface FittedModelsEvidence {
  models: FittedVariogramModel[]
  best_model: VariogramModelName
  parameter_origin: string
}

// 各向异性候选：恒为诊断建议（diagnostic_suggestion），确认是显式人工操作
export interface AnisotropyCandidateEvidence {
  status: 'diagnostic_suggestion'
  rank: number
  major_direction_id: string
  major_azimuth_deg: number
  major_dip_deg: number | null
  major_range: number
  secondary_direction_id: string | null
  secondary_range: number | null
  secondary_support_pairs: number
  vertical_direction_id: string | null
  vertical_range: number | null
  vertical_support_pairs: number
  major_minor_range_ratio: number | null
  major_vertical_range_ratio: number | null
  used_direction_ids: string[]
  used_bin_indices: number[]
  used_pair_count: number
  warnings: string[]
}

export interface AnisotropySuggestion {
  candidates: AnisotropyCandidateEvidence[]
  compared_direction_ids: string[]
  skipped_direction_ids: string[]
  warnings: string[]
}

// 点对抽样披露：sampled=false 即全量点对，true 即分层抽样
export interface VariogramSamplingDisclosure {
  total_pair_count: number
  used_pair_count: number
  sampling_rate: number
  sampled: boolean
  seed: number
}

// GET /api/professional-diagnostics/{id}/variogram
export interface VariogramEvidence {
  diagnosis_id: string
  omnidirectional: BoundedRows<VariogramBin>
  directional: BoundedRows<DirectionalVariogramBin>
  fitted_models: FittedModelsEvidence
  anisotropy_candidates: AnisotropySuggestion
  sampling: VariogramSamplingDisclosure
  downloads: Record<string, string>
}

// POST /api/professional-diagnostics/{id}/confirm 请求体（note 必填，服务端 min_length=1）
export interface ManualVariogramParameters {
  nugget: number
  sill: number
  range: number
}

export interface AnisotropyConfirmationPayload {
  keep_isotropic: boolean
  azimuth_deg?: number
  dip_deg?: number | null
  roll_deg?: number | null
  major_minor_ratio?: number
  major_vertical_ratio?: number | null
  candidate_rank?: number
  anisotropy_candidates_sha256?: string
}

export interface ProfessionalConfirmationPayload {
  model: VariogramModelName
  parameter_strategy: 'automatic_candidate' | 'manual'
  fitted_models_sha256?: string
  manual_parameters?: ManualVariogramParameters
  anisotropy: AnisotropyConfirmationPayload
  note: string
}

// 不可变确认快照：只新建（201），无任何更新入口
export interface ProfessionalConfirmationRecord {
  id: string
  diagnostic_id: string
  fingerprint: string
  note: string
  config: Record<string, unknown>
  created_at: string
}

// 实验创建的专业邻域 / 经验不确定性原始载荷（严格校验在服务端契约层）
export interface NeighborhoodPayload {
  radii: number[]
  azimuth_deg?: number
  dip_deg?: number | null
  roll_deg?: number | null
  min_neighbors?: number
  max_neighbors?: number
  sector_count?: number
  max_per_sector?: number
}

export interface EmpiricalUncertaintyPayload {
  min_neighbors?: number
  max_neighbors?: number
  power?: number
}

// ---------------- v0.6 成果专业证据 / 折分 / 残差 / 不确定性 / 异常 / 比较契约 ----------------
// （与 routes/professional.py + public_dto.py + modeling/comparison.py 一一对应）

// 算法能力记录：「不适用」是类型化状态，绝不用空值或 0 表达
export interface ProfessionalCapabilities {
  algorithm?: string
  empirical_variogram?: ProfessionalCapabilityState
  model_anisotropy?: ProfessionalCapabilityState
  z_scale_weight_distance?: ProfessionalCapabilityState
  search_neighborhood?: ProfessionalCapabilityState
  sector_neighbor_limits?: ProfessionalCapabilityState
  spatial_fold_inspection?: ProfessionalCapabilityState
  empirical_error_scale?: ProfessionalCapabilityState
  native_kriging_std?: ProfessionalCapabilityState
  anomaly_extraction?: ProfessionalCapabilityState
  candidate_comparison?: ProfessionalCapabilityState
  notes?: Record<string, string>
}

// 参数出处（§6.4）：折内参数与全数据拟合参数分别标记，互不混述
export interface ParameterProvenanceEntry {
  origin: string
  scope: string
  evidence?: string
  variogram?: Record<string, unknown>
}

export interface ParameterProvenance {
  validation: ParameterProvenanceEntry
  final: ParameterProvenanceEntry
}

// GET /api/results/{id}/professional
// legacy 候选（available=false）只携带 reason，绝不伪造零值能力
export interface ProfessionalResultEvidence {
  result_id: string
  available: boolean
  reason?: string
  algorithm: string
  confirmation_id?: string | null
  capabilities?: ProfessionalCapabilities
  parameter_provenance?: ParameterProvenance | null
  manifest?: ProfessionalManifestSummary | null
}

// GET /api/results/{id}/folds
export interface FoldInfo {
  fold_index: number
  training_count: number
  validation_count: number
  validation_groups: number[]
  group_count: number
  leakage_detected: boolean
  metrics: { rmse: number | null; valid_count: number | null } | null
}

export interface FoldEvidence {
  result_id: string
  fold_count: number
  leakage_detected: boolean
  folds: FoldInfo[]
  download_url: string
}

// GET /api/results/{id}/residuals（列式有界内联；2D 成果 z 列为 null）
export interface ResidualEvidence {
  result_id: string
  total: number
  returned: number
  decimate: number
  source_row: number[]
  fold_index: number[]
  x: number[]
  y: number[]
  z: Array<number | null>
  observed: Array<number | null>
  predicted: Array<number | null>
  residual: Array<number | null>
  absolute_error: Array<number | null>
  squared_error: Array<number | null>
  is_nodata: boolean[]
  download_url: string
}

// GET /api/results/{id}/uncertainty/{kind}（与值预览同一抽稀上限与 NoData 语义）
export type UncertaintyLayerKind = 'empirical_error' | 'kriging_std'

export interface UncertaintyPreview {
  result_id: string
  layer: string
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

// POST /api/results/{id}/anomaly-extractions 请求体（严格校验在服务端契约层）
export interface AnomalyExtractionPayload {
  direction: 'high' | 'low'
  threshold: number
  empirical_error_max?: number | null
  kriging_std_max?: number | null
  min_support_nodes?: number
  connectivity_rule?: 'face_2d4_3d6_v1'
}

// POST 异常提取响应：202 新任务 / 200 幂等复用（reused=true 时 job_id 为 null）
export interface AnomalyExtractionAccepted {
  extraction_id: string
  job_id: string | null
  status: string
  reused: boolean
}

// GET /api/anomaly-extractions/{id} 的连通区行（有界预览，完整工件走下载）
export interface AnomalyComponentRow {
  component_id: number
  support_node_count: number
  support_measure: number
  support_unit: string
  bounds: Array<[number, number]>
  centroid: number[]
  value_min: number
  value_max: number
  value_mean: number
  touches_grid_boundary: boolean
  empirical_error_scale_min?: number | null
  empirical_error_scale_max?: number | null
  empirical_error_scale_mean?: number | null
  kriging_std_min?: number | null
  kriging_std_max?: number | null
  kriging_std_mean?: number | null
}

export interface AnomalyExtractionRecord {
  id: string
  candidate_result_id: string
  status: 'pending' | 'succeeded' | 'failed' | string
  fingerprint: string
  config: Record<string, unknown>
  manifest: ProfessionalManifestSummary | null
  error: ProfessionalErrorBody | null
  components: { total: number; returned: number; rows: AnomalyComponentRow[] } | null
  created_at: string
}

// POST /api/professional-comparisons → 201（comparison_fingerprint 即登记身份）
export interface GridDifferenceSummary {
  common_valid_count: number
  mean: number
  max_abs: number
}

// 双候选比较结论：不兼容时 metric_deltas/common_valid_count 一律 null
export interface CandidateComparisonResult {
  first_result_id: string
  second_result_id: string
  compatible: boolean
  mismatches: string[]
  common_valid_count: number | null
  metric_deltas: Record<string, number> | null
  grid_difference_available: boolean
  grid_difference: GridDifferenceSummary | null
  comparison_fingerprint: string
}

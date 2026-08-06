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
  // v0.6.1：上传案例卡的主打成果直达链接；无成果为 null，legacy 卡片不携带
  featured_result?: FeaturedResultLink | null
  // v0.7.0：统一工作台身份与能力（所有卡片均携带；旧客户端可按 source_kind 回退）
  workspace_kind?: 'builtin_legacy' | 'builtin_preset' | 'user_upload'
  capabilities?: {
    data_summary: boolean
    experiments: boolean
    official_result: boolean
    native_volume: boolean
  }
  official_result?: FeaturedResultLink | null
  provenance_summary?: Record<string, unknown>
  links: {
    detail: string | null
    publish_status: string | null
  }
}

export interface FeaturedResultLink {
  result_id: string
  // 前端路由（非 API 路径），如 /results/{id}
  url: string
  materialized: boolean
}

// v0.7.0：统一案例工作台身份（三种来源共用同一 DTO）
export type WorkspaceKind = 'builtin_legacy' | 'builtin_preset' | 'user_upload'

export interface WorkspaceCapabilities {
  data_summary: boolean
  experiments: boolean
  official_result: boolean
  native_volume: boolean
}

export interface CaseWorkspaceSummary extends CaseSummary {
  workspace_kind: WorkspaceKind
  capabilities: WorkspaceCapabilities
  // 当前可查看/建模的数据版本摘要；没有时为 null
  primary_dataset: DatasetVersionRecord | null
  // 官方或正式主打成果链接；没有时为 null
  official_result: FeaturedResultLink | null
  // 只含允许公开的来源说明、字段、坐标语义、单位和摘要指纹
  provenance_summary: Record<string, unknown>
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

// 历史 S3M 发布证据：available 只表示旧 iServer S3M 发布链路可访问，
// 绝不作为 v0.6.1 NetCDF 原生体渲染能力，也不决定 NetCDF 资产成败；
// 原生能力一律以 render-capability GET（RenderCapability.supported）为准。
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
  // v0.7.0：read_only 官方案例为 false（默认缺省视为允许，兼容旧响应）
  selection_allowed?: boolean
  selections: FormalSelectionRecord[]
}

export interface ExportRecord {
  id: string
  // v0.7.0 第二批：legacy 剖面导出无候选成果（显式 null）
  candidate_result_id: string | null
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
    // SSE 最小只描述变异函数拟合优度，不代表空间验证更优或数值稳定
    min_sse_model?: 'spherical' | 'exponential' | 'gaussian'
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
  min_sse_model: VariogramModelName
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

// ---------------- v0.6.1 NetCDF 原生体渲染契约（与 routes/rendering.py + 设计 §2.3/§2.4 一一对应） ----------------

export type RenderSourceKind = 'candidate_result' | 'builtin_legacy'

export type RenderAssetStatus = 'creating' | 'ready' | 'failed' | 'interrupted'

// 显示锚点变换：wgs84_display_anchor_v1 只是显示变换，绝不代表真实地理配准
export interface DisplayTransform {
  contract: 'wgs84_display_anchor_v1'
  origin_x: number
  origin_y: number
  anchor_longitude: number
  anchor_latitude: number
  anchor_height: number
  metres_per_degree_lon: number
  metres_per_degree_lat: number
}

// GET 渲染能力响应：supported=false 携带稳定 reason_code；display_transform 可能为 null
// （无可用网格也无测点时前端只做文本诊断，不挂载 iframe）
export interface RenderCapability {
  source_kind: RenderSourceKind
  source_id: string
  supported: boolean
  reason_code: string | null
  reason: string | null
  dimension: string | null
  grid_kind: string | null
  property_name: string | null
  units: string | null
  geolocation_status: string
  display_transform: DisplayTransform | null
  // v0.7.0 第二批：来源驱动渲染默认值；不支持时为 null
  render_profile?: RenderProfile | null
}

// v0.7.0 第二批：渲染默认值与剖面分析 DTO
export type RenderScale = 'linear' | 'log'
export type RenderPaletteId = 'native-spectrum' | 'viridis' | 'turbo' | 'coolwarm' | 'grayscale'
export type SliceAxis = 'x' | 'y' | 'z'

export interface RenderProfile {
  property_name: string
  unit: string
  default_scale: RenderScale
  default_palette: RenderPaletteId
  log_available: boolean
  value_range: [number, number]
  filter_range: [number, number]
  lighting: boolean
  gradient_opacity: boolean
  bounding_box: boolean
  opacity: number
}

export interface SliceStatistics {
  total_count: number
  valid_count: number
  nodata_count: number
  min: number | null
  max: number | null
  mean: number | null
  std_population: number | null
  p10: number | null
  p50: number | null
  p90: number | null
}

export interface SlicePlane {
  fixed_axis: SliceAxis
  index: number
  coordinate: number
  sdk_relative_position: number
  row_axis: SliceAxis
  column_axis: SliceAxis
  row_coordinates: number[]
  column_coordinates: number[]
  values: Array<Array<number | null>>
  nodata_mask: boolean[][]
}

export interface SliceAnalysisResponse {
  asset_identity: {
    asset_id: string
    source_kind: RenderSourceKind
    source_id: string
    grid_sha256: string
    netcdf_sha256: string
  }
  property: { name: string; unit: string }
  axes: Record<SliceAxis, { length: number; coordinates: number[]; unit: string }>
  slice: SlicePlane
  statistics: SliceStatistics
  render_profile: RenderProfile | null
}

export interface RenderAssetError {
  code: string
  message: string
  details: Record<string, unknown>
}

// 渲染资产公共记录：服务端内部 asset_dir 绝不下发，只有按 id 派生的相对 URL
export interface RenderAssetRecord {
  id: string
  source_kind: RenderSourceKind
  source_id: string
  renderer: 'supermap_voxelgrid_netcdf'
  status: RenderAssetStatus
  grid_sha256: string
  netcdf_sha256: string | null
  manifest_url: string | null
  netcdf_url: string | null
  error: RenderAssetError | null
}

// legacy 渲染源导入响应的登记身份：artifact_dir 为相对工件目录身份，绝无绝对路径
export interface LegacyRenderSourceRegistration {
  source_kind: 'builtin_legacy'
  source_id: string
  grid_sha256: string
  property_name: string
  units: string
  shape: number[]
  artifact_dir: string
  import_source_sha256: string
}

// 导入请求参数：列名/属性名/单位显式传入（multipart 表单同名字段）
export interface LegacyRenderSourceImportParams {
  xColumn: string
  yColumn: string
  zColumn: string
  valueColumn: string
  propertyName: string
  units: string
}

// 子帧 RENDER_STATE 携带的渲染身份（camelCase，§2.4 协议字段名逐字一致）
export interface RenderIdentity {
  sourceKind: RenderSourceKind
  sourceId: string
  gridSha256: string
  netcdfSha256: string
}

export type PointLayerId = 'grid-samples' | 'aggregated' | 'accepted' | 'rejected' | 'legacy-measurements'

export interface PointLayerStyle {
  color?: string
  pixelSize: number
  outlineColor?: string
  outlineWidth?: number
}

// 辅助/证据点层：坐标恒为局部米制（'local'），由子帧按 INIT.displayTransform 变换；
// 点层是辅助采样/证据层，绝不参与连续体渲染
export interface PointLayerPayload {
  id: PointLayerId
  visible: boolean
  role: 'auxiliary' | 'evidence'
  coordinates: 'local'
  x: number[]
  y: number[]
  z: number[]
  values?: number[]
  isNodata?: boolean[]
  style: PointLayerStyle
}

// ---------------------------------------------------------------------------
// v0.7.0 batch 3: case lifecycle, data preparation, diagnostics, comparison
// ---------------------------------------------------------------------------

export interface TrashCaseSummary {
  case_id: string
  name: string
  trashed_at: string
  counts: { datasets: number; experiments: number; results: number }
  can_restore: boolean
  can_purge: boolean
  reason: string | null
}

export interface DataPreparationNextAction {
  step: 'upload' | 'mapping' | 'quality_review' | 'experiment' | 'repair'
  label: string
  url: string | null
}

export interface DataPreparationSummary {
  state: 'needs_upload' | 'needs_mapping' | 'needs_quality_review' | 'ready' | 'blocked'
  dataset_id: string | null
  latest_validated_dataset_id: string | null
  next_action: DataPreparationNextAction
  error: { code: string; dataset_id: string } | null
}

export interface ProfessionalDiagnosticListItem {
  diagnosis: Record<string, unknown>
  job: Record<string, unknown> | null
  url: string
}

export interface ProfessionalDiagnosticList {
  dataset_id: string
  diagnostics: ProfessionalDiagnosticListItem[]
}

export interface ProfessionalConfirmationSummary {
  confirmation: Record<string, unknown>
  diagnosis_id: string
  diagnosis_status: string
  dataset_id: string
  case_id: string
  fingerprint: string
  config_summary: Record<string, unknown>
}

export interface ComparisonCandidateSummary {
  candidate_result_id: string
  experiment_id: string
  run_id: string
  algorithm: string
  parameters: Record<string, unknown>
  selectable: boolean
  metrics: { rmse: number | null; mae: number | null; r2: number | null; bias: number | null }
  result_url: string
}

export interface CandidateCatalogGroup {
  experiment_id: string
  experiment_name: string
  candidates: ComparisonCandidateSummary[]
}

export interface CandidateCatalog {
  dataset_id: string
  groups: CandidateCatalogGroup[]
}

export interface MultiCandidateComparison {
  candidate_result_ids: string[]
  dataset_version_id: string
  comparable: boolean
  mismatches: string[]
  candidates: ComparisonCandidateSummary[]
  ranking: string[] | null
  comparison_fingerprint: string
}

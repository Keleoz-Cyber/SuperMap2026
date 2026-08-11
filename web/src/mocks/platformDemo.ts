// Playwright 冒烟用的确定性 mock API：不依赖 iServer、不访问网络。
// 在浏览器侧拦截 /api/** 并按小型状态机应答，覆盖完整 v0.4 流程。

import type { Page, Route } from '@playwright/test'
import { WEB_VERSION } from '../version'

const T = '2026-07-23T00:00:00Z'
const SHA = 'ab'.repeat(32)

// ---------------------------------------------------------------- v0.5 微震
// 便携夹具口径（45/44/1/0/44/44）：与 e2e-live/fixtures/microseismicBundle.ts
// 生成的合成 22-DAT 包同一份计数合同，绝不冒充私有 2,006/1,925 证据。
const MICRO_SHA = 'cd'.repeat(32)
const MICRO_RULE_VERSION = 'microseismic_e2e_mock_v0.5'
const MICRO_MAPPING = {
  dimension: '3d',
  x: 'X_LOCAL_M',
  y: 'Y_LOCAL_M',
  z: 'Z_LOCAL_M',
  value: 'VX_KM_S',
  value_name: 'Vx',
  value_unit: 'km/s',
  coordinate_kind: 'local_linear',
}

interface MicroSourceFile {
  file_name: string
  sha256: string
  point_id: string
  line_id: string
  source_record_count: number
}

// 文件名清单即 config/microseismic.yaml 的 expected 清单（公开合同）；
// W8.dat 含 1 个 1.#QNAN0 伪行故 3 条源记录，其余各 2 条。
function buildMicroSourceFiles(): MicroSourceFile[] {
  const files: MicroSourceFile[] = []
  const push = (pointId: string, fileName: string, lineId: string) =>
    files.push({
      file_name: fileName,
      sha256: MICRO_SHA,
      point_id: pointId,
      line_id: lineId,
      source_record_count: pointId === 'W8' ? 3 : 2,
    })
  for (let i = 1; i <= 9; i++) push(`W${i}`, `W${i}.dat`, 'L1')
  for (let i = 12; i <= 20; i++) push(`W${i}`, `WD${i}-Vx.dat`, 'L2')
  for (let i = 24; i <= 27; i++) push(`W${i}`, `WD${i}-Vx.dat`, 'L3')
  return files
}

const MICRO_SOURCE_FILES = buildMicroSourceFiles()

const MICRO_LAYER_COUNTS = {
  source_records: 45,
  finite_records: 44,
  invalid_records: 1,
  rejected_3sigma: 0,
  accepted_modeling: 44,
  aggregated_nodes: 44,
}

const MICRO_AGGREGATION = {
  conflict_group_count: 0,
  conflict_row_count: 0,
  collapsed_row_count: 0,
  max_value_range: 0,
}

const MICRO_GOLDEN = {
  passed: true,
  checks: [
    { name: 'accepted_count', passed: true, expected: 44, actual: 44 },
    { name: 'rejected_count', passed: true, expected: 0, actual: 0 },
    { name: 'accepted_sha256', passed: true, expected: MICRO_SHA, actual: MICRO_SHA },
    { name: 'rejected_sha256', passed: true, expected: MICRO_SHA, actual: MICRO_SHA },
    { name: 'conflict_group_count', passed: true, expected: 0, actual: 0 },
    { name: 'conflict_row_count', passed: true, expected: 0, actual: 0 },
    { name: 'modeling_node_count', passed: true, expected: 44, actual: 44 },
  ],
}

const MICRO_DERIVATION = {
  dataset_id: 'ds-micro',
  case_id: 'case-micro',
  status: 'mapped',
  source_kind: 'microseismic_dat_bundle',
  rule_version: MICRO_RULE_VERSION,
  adapter_version: '0.5.0',
  aggregation_method: 'arithmetic_mean_exact_xyz',
  layer_counts: MICRO_LAYER_COUNTS,
  line_counts: { L1: 19, L2: 18, L3: 8 },
  three_sigma: {
    threshold: 3.0,
    ddof: 1,
    depth_mean: 52.778,
    depth_std: 2.81,
    vx_mean: 0.481744,
    vx_std: 0.0436,
  },
  aggregation: MICRO_AGGREGATION,
  coordinates: {
    coord_type: 'local_engineering_m',
    depth_rule: 'depth_m = WL/2(km) × 1000',
    z_rule: 'z_local_m = -depth_m',
    vx_unit: 'km/s',
    absolute_crs: 'unavailable',
  },
  golden: MICRO_GOLDEN,
  validation_passed: true,
  downstream_gates: {
    geometry_blocked: false,
    cleaning_blocked: false,
    interpolation_blocked: false,
  },
  source_files: MICRO_SOURCE_FILES,
  artifacts: {
    source_records: { file: 'source_records_45.csv', rows: 45, sha256: MICRO_SHA },
    invalid_records: { file: 'invalid_records_1.csv', rows: 1, sha256: MICRO_SHA },
    rejected_3sigma: { file: 'rejected_3sigma_0.csv', rows: 0, sha256: MICRO_SHA },
    accepted_modeling: { file: 'accepted_modeling_44.csv', rows: 44, sha256: MICRO_SHA },
    aggregated_nodes: { file: 'aggregated_nodes_44.csv', rows: 44, sha256: MICRO_SHA },
  },
}

const MICRO_IMPORT_PROFILE = {
  source_kind: 'microseismic_dat_bundle',
  dimension: '3d',
  mapping: MICRO_MAPPING,
  rule_version: MICRO_RULE_VERSION,
  adapter_version: '0.5.0',
  aggregation_method: 'arithmetic_mean_exact_xyz',
  golden: MICRO_GOLDEN,
  layer_counts: MICRO_LAYER_COUNTS,
  aggregation: MICRO_AGGREGATION,
  source_files: MICRO_SOURCE_FILES,
  derivation_report: 'derived/derivation_report.json',
  modeling_provenance: 'derived/modeling_provenance.parquet',
  row_count: 44,
  valid_row_count: 44,
  invalid_row_count: 0,
  standardized_sha256: MICRO_SHA,
}

interface MockState {
  runPolls: number
  runStarted: boolean
  selections: unknown[]
  exported: boolean
  datasetStatus: 'uploaded' | 'mapped' | 'validated' | 'abandoned'
  diagnosisJobPolls: number
  extractionJobPolls: number
  // v0.6.1：cand-1 物化状态机--GET /results 未物化 404，POST materialize 后 200
  resultMaterialized: boolean
  // v0.8.0：电阻率散点预置的 dsi_like 用户实验状态机（轮询/物化）
  rhoDsiRunPolls: number
  rhoResultMaterialized: boolean
  // v0.7.0 batch 3：案例生命周期状态机
  caseName: string | null
  caseTrashed: boolean
  casePurged: boolean
  caseTrashedAt: string | null
  // v0.7.0 batch 3：多候选比较调用计数（首次 comparable，后续 incompatible）
  comparisonCalls: number
  // v0.9.0：AI 辅助研判状态机（404 直到显式 POST 生成）
  aiRecord: unknown | null
}

// ---------------------------------------------------------------- v0.6 专业建模
// 专业 mock 计数全部来自本文件定义的夹具值（32 折外点/3 折/2 连通区/121 网格
// 节点），只驱动浏览器流程，绝不冒充真实数据或私有证据。
const PRO_SHA = 'bd'.repeat(32)

const PRO_OMNI_BINS = Array.from({ length: 8 }, (_, i) => ({
  bin_index: i,
  lower_distance: i * 10,
  upper_distance: (i + 1) * 10,
  center_distance: i * 10 + 5,
  mean_distance: i * 10 + 5.2,
  semivariance: 0.4 + i * 0.3,
  pair_count: 120 - i * 6,
  used_for_fit: i < 6,
  exclusion_reason: i < 6 ? null : 'insufficient_pairs',
}))

const PRO_DIRECTIONS = [
  { id: 'd000', azimuth_deg: 0, range: 20.5 },
  { id: 'd001', azimuth_deg: 90, range: 61.2 },
]

const PRO_DIRECTIONAL_ROWS = PRO_DIRECTIONS.flatMap((direction) =>
  PRO_OMNI_BINS.map((bin, i) => ({
    ...bin,
    semivariance: Number((bin.semivariance * (direction.azimuth_deg === 90 ? 0.7 : 1.4)).toFixed(3)),
    direction_id: direction.id,
    azimuth_deg: direction.azimuth_deg,
    dip_deg: null,
    azimuth_tolerance_deg: 15,
    dip_tolerance_deg: null,
    bin_index: i,
  })),
)

const PRO_FITTED_MODELS = {
  models: [
    {
      model: 'spherical',
      nugget: 0.05,
      partial_sill: 1.15,
      sill: 1.2,
      range: 42.0,
      weighted_sse: 0.031,
      converged: true,
      parameter_origin: 'automatic_candidate',
      used_bin_indices: [0, 1, 2, 3, 4, 5],
      bounds: { nugget: [0, 1.2], partial_sill: [0.001, 3.6], range: [0.001, 160] },
      residuals: [0.01, -0.02, 0.03, -0.01, 0.0, 0.02],
    },
    {
      model: 'exponential',
      nugget: 0.08,
      partial_sill: 1.12,
      sill: 1.2,
      range: 38.5,
      weighted_sse: 0.052,
      converged: true,
      parameter_origin: 'automatic_candidate',
      used_bin_indices: [0, 1, 2, 3, 4, 5],
      bounds: { nugget: [0, 1.2], partial_sill: [0.001, 3.6], range: [0.001, 160] },
      residuals: [0.02, -0.01, 0.04, -0.02, 0.01, 0.03],
    },
    {
      model: 'gaussian',
      nugget: 0.11,
      partial_sill: 1.09,
      sill: 1.2,
      range: 35.8,
      weighted_sse: 0.068,
      converged: true,
      parameter_origin: 'automatic_candidate',
      used_bin_indices: [0, 1, 2, 3, 4, 5],
      bounds: { nugget: [0, 1.2], partial_sill: [0.001, 3.6], range: [0.001, 160] },
      residuals: [0.03, -0.03, 0.05, -0.02, 0.02, 0.04],
    },
  ],
  min_sse_model: 'spherical',
  parameter_origin: 'automatic_candidate',
}

const PRO_SUGGESTION = {
  candidates: [
    {
      status: 'diagnostic_suggestion',
      rank: 1,
      major_direction_id: 'd001',
      major_azimuth_deg: 90,
      major_dip_deg: null,
      major_range: 61.2,
      secondary_direction_id: 'd000',
      secondary_range: 20.5,
      secondary_support_pairs: 640,
      vertical_direction_id: null,
      vertical_range: null,
      vertical_support_pairs: 0,
      major_minor_range_ratio: 2.99,
      major_vertical_range_ratio: null,
      used_direction_ids: ['d001', 'd000'],
      used_bin_indices: [0, 1, 2, 3, 4, 5],
      used_pair_count: 1280,
      warnings: [],
    },
  ],
  compared_direction_ids: ['d000', 'd001'],
  skipped_direction_ids: [],
  warnings: [],
}

const PRO_DIAGNOSIS_MANIFEST = {
  version: 1,
  fingerprint: 'fp-diag-pro-1',
  artifacts: {
    metadata: { file: 'metadata.json', sha256: PRO_SHA, bytes: 512 },
    omnidirectional: { file: 'omnidirectional.csv', sha256: PRO_SHA, bytes: 1024 },
    directional: { file: 'directional.csv', sha256: PRO_SHA, bytes: 2048 },
    fitted_models: { file: 'fitted_models.json', sha256: 'ae'.repeat(32), bytes: 1536 },
    anisotropy_candidates: { file: 'anisotropy_candidates.json', sha256: 'af'.repeat(32), bytes: 768 },
  },
  created_at: T,
  summary: {
    fitted_models: ['spherical', 'exponential', 'gaussian'],
    min_sse_model: 'spherical',
    omni_used_bin_count: 6,
    direction_count: 2,
    supported_direction_count: 2,
    candidate_ranks: [1],
    warnings: [],
  },
}

const PRO_CAPABILITIES = {
  algorithm: 'ordinary_kriging',
  empirical_variogram: 'supported',
  model_anisotropy: 'supported',
  z_scale_weight_distance: 'supported',
  search_neighborhood: 'supported',
  sector_neighbor_limits: 'supported',
  spatial_fold_inspection: 'supported',
  empirical_error_scale: 'supported',
  native_kriging_std: 'supported',
  anomaly_extraction: 'supported',
  candidate_comparison: 'supported',
}

const PRO_FOLDS = {
  result_id: 'cand-pro-1',
  fold_count: 3,
  leakage_detected: false,
  folds: [
    { fold_index: 0, training_count: 96, validation_count: 32, validation_groups: [2, 5], group_count: 2, leakage_detected: false, metrics: { rmse: 1.234, valid_count: 32 } },
    { fold_index: 1, training_count: 104, validation_count: 24, validation_groups: [0], group_count: 1, leakage_detected: false, metrics: { rmse: 1.421, valid_count: 24 } },
    { fold_index: 2, training_count: 100, validation_count: 28, validation_groups: [1, 4], group_count: 2, leakage_detected: false, metrics: { rmse: 1.102, valid_count: 28 } },
  ],
  download_url: '/api/professional-artifacts/art-folds/download',
}

const PRO_RESIDUAL_ROWS = [
  { source_row: 3, fold_index: 0, x: 10, y: 20, observed: 101.2, predicted: 100.4, residual: 0.8 },
  { source_row: 7, fold_index: 0, x: 30, y: 40, observed: 99.1, predicted: 100.2, residual: -1.1 },
  { source_row: 11, fold_index: 0, x: 50, y: 60, observed: 104.5, predicted: 103.1, residual: 1.4 },
  { source_row: 18, fold_index: 1, x: 20, y: 70, observed: 97.6, predicted: 98.9, residual: -1.3 },
  { source_row: 23, fold_index: 1, x: 60, y: 10, observed: 102.8, predicted: 101.7, residual: 1.1 },
  { source_row: 29, fold_index: 2, x: 80, y: 30, observed: 100.0, predicted: 101.2, residual: -1.2 },
  { source_row: 31, fold_index: 2, x: 90, y: 80, observed: 103.3, predicted: 102.0, residual: 1.3 },
]

const PRO_PREVIEW = {
  result_id: 'cand-pro-1',
  dimension: '2d',
  original_cell_count: 121,
  served_cell_count: 121,
  stride: 1,
  x: Array.from({ length: 121 }, (_, i) => (i % 11) * 10),
  y: Array.from({ length: 121 }, (_, i) => Math.floor(i / 11) * 10),
  z: null,
  values: Array.from({ length: 121 }, (_, i) => 90 + ((i * 37) % 41)),
  is_nodata: Array.from({ length: 121 }, () => false),
  value_range: [90, 130],
}

// ---------------------------------------------------------------- v0.8.0 电阻率散点预置
// 预置形态（行数/字段/网格/值域）来自入库公开合同（config/presets/resistivity.json
// 与 resistivity-official-baseline.json 的已核验事实）；候选指标为本文件夹具值，
// 只驱动浏览器流程，绝不冒充真实计算结果或外部私有源内容。
const RHO_SHA = 'e0'.repeat(32)
const RHO_GRID_SHA = 'e1'.repeat(32)
const RHO_NC_SHA = 'e2'.repeat(32)
const RHO_DATASET_ID = 'ds-rho'
const RHO_OFFICIAL_EXPERIMENT_ID = 'exp-rho-official'
const RHO_OFFICIAL_RUN_ID = 'run-rho-official'
const RHO_OFFICIAL_RESULT_ID = 'cand-rho-official'
const RHO_DSI_EXPERIMENT_ID = 'exp-rho-dsi'
const RHO_DSI_RUN_ID = 'run-rho-dsi'
const RHO_DSI_RESULT_ID = 'cand-rho-dsi-1'
const RHO_ROW_COUNT = 17_549
const RHO_VALUE_RANGE: [number, number] = [1.032113, 149.984]
const RHO_GRID_SHAPE = [7, 23, 42]
const RHO_GRID_BOUNDS = [
  [-160, -40],
  [220, 660],
  [-833.0047143, -19.5999],
]
const RHO_GRID_RESOLUTION = [20, 20, 20]
// RHO 单位：Ω·m（v0.8.0 第三批用户权威确认，此前为“待来源确认”占位）
const RHO_VALUE_UNIT = 'Ω·m'
const RHO_MAPPING = {
  dimension: '3d',
  x: 'X',
  y: 'Y',
  z: 'Z',
  value: 'RHO',
  value_name: 'RHO',
  value_unit: RHO_VALUE_UNIT,
  coordinate_kind: 'local_linear',
}
const RHO_DATASET_PROFILE = {
  source_kind: 'builtin_preset',
  dimension: '3d',
  mapping: RHO_MAPPING,
  row_count: RHO_ROW_COUNT,
  valid_row_count: RHO_ROW_COUNT,
  invalid_row_count: 0,
}
const RHO_PROVENANCE = {
  preset_version: 'resistivity-rho-17549/v1',
  source_sha256: RHO_SHA,
  badge: '散点预置 · 官方普通克里金成果',
  data_form: '标准化散点 · 17,549 个节点',
  fields: ['X', 'Y', 'Z', 'RHO'],
  value_unit: RHO_VALUE_UNIT,
  coordinate_kind: 'local_linear',
}
// DSI-like 合同默认参数（与后端 DSIParameters 默认值逐位一致）
const RHO_DSI_PARAMETERS = {
  init_power: 2,
  neighbor_connectivity: 6,
  smoothing_strength: 0.5,
  max_iterations: 25,
  convergence_tolerance: 1e-4,
  hard_constraints: true,
}
const RHO_VALIDATION = { method: 'spatial_kfold', folds: 5, seed: 20260723, holdout_fraction: 0.2 }

// ---------------------------------------------------------------- v0.8.0 第三批：瓦斯散点预置
// 预置形态（58 行/字段/网格/值域）来自入库公开合同（config/presets/gas.json
// 与 gas-official-baseline.json 的已核验事实：X/Y/Z/CH4_content、ml/g、
// 局部线性米制坐标、官方网格 151×333×12、CH4_content∈[0.05, 34.3]、
// winner ordinary_kriging spherical/24 及其空间 5 折指标）；统计/分布等
// 分析数值为本文件按固定算术公式生成的确定性演示合成口径（无随机源），
// 只驱动浏览器流程，绝不冒充真实计算结果或私有证据。
const GAS_SHA = 'f0'.repeat(32)
const GAS_GRID_SHA = 'f1'.repeat(32)
const GAS_NC_SHA = 'f2'.repeat(32)
const GAS_DATASET_ID = 'ds-gas'
const GAS_OFFICIAL_EXPERIMENT_ID = 'exp-gas-official'
const GAS_OFFICIAL_RUN_ID = 'run-gas-official'
const GAS_OFFICIAL_RESULT_ID = 'cand-gas-official'
const GAS_ROW_COUNT = 58
const GAS_VALUE_RANGE: [number, number] = [0.05, 34.3]
const GAS_GRID_SHAPE = [151, 333, 12]
const GAS_GRID_CELL_COUNT = 603_396
const GAS_GRID_BOUNDS = [
  [1023.802, 4016.788],
  [1049.716, 7688.731],
  [121.0375, 175.656],
]
const GAS_GRID_RESOLUTION = [20, 20, 5]
// CH4_content 单位：ml/g（v0.8.0 第三批用户权威确认，绝不静默换算）
const GAS_VALUE_UNIT = 'ml/g'
const GAS_MAPPING = {
  dimension: '3d',
  x: 'X',
  y: 'Y',
  z: 'Z',
  value: 'CH4_content',
  value_name: 'CH4_content',
  value_unit: GAS_VALUE_UNIT,
  coordinate_kind: 'local_linear',
}
const GAS_DATASET_PROFILE = {
  source_kind: 'builtin_preset',
  dimension: '3d',
  mapping: GAS_MAPPING,
  row_count: GAS_ROW_COUNT,
  valid_row_count: GAS_ROW_COUNT,
  invalid_row_count: 0,
}
const GAS_PROVENANCE = {
  preset_version: 'gas-ch4-58/v1',
  source_sha256: GAS_SHA,
  badge: '散点预置 · 官方基线成果',
  data_form: '标准化散点 · 58 个合格样品',
  fields: ['X', 'Y', 'Z', 'CH4_content'],
  value_unit: GAS_VALUE_UNIT,
  coordinate_kind: 'local_linear',
}
// 官方基线指标：config/presets/gas-official-baseline.json 入库公开事实
// （58 点稀疏采样下 r2 为负，如实呈现为解释性估计）
const GAS_OFFICIAL_METRICS = { rmse: 8.298439, mae: 6.5521, r2: -0.109659, bias: -0.068618 }
const GAS_OFFICIAL_PARAMETERS = { variogram_model: 'spherical', neighbor_count: 24 }
const GAS_VALIDATION = { method: 'spatial_kfold', folds: 5, seed: 20260723 }

// ---------------------------------------------------------------- v0.8.0 第二批：统计与空间分析中心
// analysis-summary / analysis-export mock 与真实后端合同逐字段对齐
// （src/geomodeling/api/routes/analysis.py + analysis/schemas.py）：quality/
// statistics/quantiles/32 分箱 distribution/profile_axes 三轴/model_comparison
// 候选/modules 状态数组/provenance；微震含 axis_trends/gradient/spatial_anomaly
// ok，电阻率含 log10/depth_slices/spatial_anomaly ok，v0.8.0 第三批起瓦斯含
// depth_slices/spatial_anomaly/gradient ok，generic_3d 只含通用模块
// 且模块清单与 profiles.py 注册表顺序一致。数值为本文件按固定算术公式生成的
// 确定性演示合成口径（无随机源），只驱动浏览器流程，绝不冒充真实计算结果或
// 私有证据。方法文案与后端 _METHOD_* 常量逐字一致。
const ANALYSIS_METHOD = {
  quality:
    '有效行口径：声明有效且属性值有限（与建模公共有效集一致），排除行计数保留；' +
    '重复坐标按映射维度判定（超出首次出现的行数，仅统计有效行）',
  statistics:
    '有限值基础统计（count/min/max/mean/median/std(ddof=1) 与 p05–p95 分位数，' +
    'NumPy 线性插值）；仅声明有效且有限的样本参与，count=1 时 std 为 null',
  distribution: '原始值等宽分箱（数据范围+固定 32 格），计数守恒',
  log10:
    '对数尺度分箱仅使用严格正值有限值（log10 变换后等宽 32 格）；' +
    '非正值排除且计数保留，原始值分箱与统计不受影响',
  axisTrends:
    'X/Y/Z 逐轴等宽分箱（数据范围+固定 32 格），逐格 count/mean/median，' +
    '空格为 null；与剖面统计同一确定性口径',
  gradient:
    'XY 平面 16×16 网格单元均值 → 相邻（X/Y 向）非空单元差分幅值 |Δmean| ' +
    '的有限统计（count/mean/p95/max）；任一侧为空格的相邻对排除且计数保留；仅用有限值',
  depthSlices:
    'Z 轴等宽 16 层（数据范围+固定层数）；层高值占比=层内 value≥p75 样本数/' +
    '层样本数，低值占比=层内 value≤p25 样本数/层样本数（体积占比以样本计数' +
    '为口径）；空层为 null；阈值来源见 thresholds',
  spatialAnomaly:
    'XY 平面 32×32 网格单元均值与非空单元均值 p75/p25 分位阈值比较划分高/低值' +
    '区域（致密采样下样本级阈值会被单元均值平滑掉，区域口径基于单元均值分布）；' +
    '体积占比=区域样本计数/有效样本总数（样本计数口径）；阈值来源见 thresholds',
  thresholdSource: 'cell_mean_quantiles_p25_p75',
  thresholdMethod: '高值阈值=非空网格单元均值 p75、低值阈值=非空网格单元均值 p25',
}

interface AnalysisHistBin {
  lower: number
  upper: number
  count: number
}
interface AnalysisProfileBin extends AnalysisHistBin {
  mean: number | null
  median: number | null
}
interface AnalysisSpatialBinOut {
  x_lower: number
  x_upper: number
  y_lower: number
  y_upper: number
  count: number
  mean: number | null
}
interface AnalysisAnomalyBinOut extends AnalysisSpatialBinOut {
  region: 'high' | 'low' | 'normal' | 'empty'
}
type AnalysisAxisId = 'x' | 'y' | 'z'
interface AnalysisModuleOut {
  module_id: string
  status: 'ok'
  payload: Record<string, unknown>
  message: null
}
interface AnalysisSummaryOut {
  dataset_id: string
  case_id: string
  analysis_profile: string
  profile_version: number
  variable: { name: string; unit: string | null }
  quality: Record<string, unknown>
  statistics: {
    count: number
    min: number
    max: number
    mean: number
    median: number
    std: number
    quantiles: Record<string, number>
  }
  modules: AnalysisModuleOut[]
  provenance: {
    source_sha256: string
    dataset_version: number
    generated_at: string
    calculation_version: string
  }
}

const analysisModule = (moduleId: string, payload: Record<string, unknown>): AnalysisModuleOut => ({
  module_id: moduleId,
  status: 'ok',
  payload,
  message: null,
})

/** 确定性计数权重（固定算术，无随机源） */
const analysisWeights = (base: number, span: number, bins = 32): number[] =>
  Array.from({ length: bins }, (_, i) => base + ((i * 37) % span))

/** 等宽直方图分箱；末格吸收剩余计数（计数守恒口径与后端一致） */
function analysisHistogram(
  min: number,
  max: number,
  weightsArr: number[],
  total: number,
): AnalysisHistBin[] {
  const width = (max - min) / weightsArr.length
  let assigned = 0
  return weightsArr.map((weight, i) => {
    const count = i === weightsArr.length - 1 ? total - assigned : weight
    assigned += count
    return { lower: min + i * width, upper: min + (i + 1) * width, count }
  })
}

/** 逐轴剖面分箱（count/mean/median；空箱 mean/median 为 null，绝不以 NaN 占位） */
function analysisProfileBins(
  min: number,
  max: number,
  valueBase: number,
  weightsArr: number[],
): AnalysisProfileBin[] {
  const width = (max - min) / weightsArr.length
  return weightsArr.map((weight, i) => ({
    lower: min + i * width,
    upper: min + (i + 1) * width,
    count: weight,
    mean: weight > 0 ? valueBase + i * 0.01 : null,
    median: weight > 0 ? valueBase + i * 0.01 - 0.004 : null,
  }))
}

/** XY 平面网格单元（行主序：先 row 后 col，与后端 spatial bins 顺序一致） */
function analysisSpatialBins(
  xMin: number,
  xMax: number,
  yMin: number,
  yMax: number,
  valueBase: number,
  grid = 32,
): AnalysisSpatialBinOut[] {
  const xw = (xMax - xMin) / grid
  const yw = (yMax - yMin) / grid
  const bins: AnalysisSpatialBinOut[] = []
  for (let row = 0; row < grid; row += 1) {
    for (let col = 0; col < grid; col += 1) {
      const count = (row * 7 + col * 13) % 5 === 0 ? 0 : 1 + ((row * 31 + col * 17) % 9)
      bins.push({
        x_lower: xMin + col * xw,
        x_upper: xMin + (col + 1) * xw,
        y_lower: yMin + row * yw,
        y_upper: yMin + (row + 1) * yw,
        count,
        mean: count > 0 ? valueBase + ((row * 3 + col * 5) % 40) / 10 : null,
      })
    }
  }
  return bins
}

/** 空间异常分箱 + 区域计数摘要（分位阈值口径，与后端载荷字段一致） */
function analysisAnomalyGrid(
  xMin: number,
  xMax: number,
  yMin: number,
  yMax: number,
  low: number,
  high: number,
  grid = 32,
) {
  const xw = (xMax - xMin) / grid
  const yw = (yMax - yMin) / grid
  const span = high - low
  const bins: AnalysisAnomalyBinOut[] = []
  for (let row = 0; row < grid; row += 1) {
    for (let col = 0; col < grid; col += 1) {
      const count = (row * 7 + col * 13) % 6 === 0 ? 0 : 2 + ((row * 31 + col * 17) % 11)
      const mean =
        count > 0 ? low - span * 0.3 + (((row * 11 + col * 7) % 120) / 100) * span * 1.6 : null
      const region: AnalysisAnomalyBinOut['region'] =
        count === 0 || mean === null
          ? 'empty'
          : mean >= high
            ? 'high'
            : mean < low
              ? 'low'
              : 'normal'
      bins.push({
        x_lower: xMin + col * xw,
        x_upper: xMin + (col + 1) * xw,
        y_lower: yMin + row * yw,
        y_upper: yMin + (row + 1) * yw,
        count,
        mean,
        region,
      })
    }
  }
  const nonEmpty = bins.filter((bin) => bin.count > 0)
  const highCells = nonEmpty.filter((bin) => bin.region === 'high')
  const lowCells = nonEmpty.filter((bin) => bin.region === 'low')
  const totalPoints = nonEmpty.reduce((acc, bin) => acc + bin.count, 0)
  const highPoints = highCells.reduce((acc, bin) => acc + bin.count, 0)
  const lowPoints = lowCells.reduce((acc, bin) => acc + bin.count, 0)
  return {
    bins,
    non_empty_cell_count: nonEmpty.length,
    high_cell_count: highCells.length,
    low_cell_count: lowCells.length,
    high_point_count: highPoints,
    low_point_count: lowPoints,
    high_volume_ratio: totalPoints > 0 ? highPoints / totalPoints : null,
    low_volume_ratio: totalPoints > 0 ? lowPoints / totalPoints : null,
  }
}

/** Z 轴 16 层异常占比（末层吸收剩余计数；high/low 计数与占比逐层确定） */
function analysisDepthSlices(zMin: number, zMax: number, total: number) {
  const layers = 16
  const width = (zMax - zMin) / layers
  const weightsArr = analysisWeights(700, 500, layers)
  let assigned = 0
  return weightsArr.map((weight, i) => {
    const count = i === layers - 1 ? total - assigned : weight
    assigned += count
    const highCount = Math.floor(count * (0.08 + ((i * 7) % 26) / 100))
    const lowCount = Math.floor(count * (0.06 + ((i * 11) % 22) / 100))
    return {
      z_lower: zMin + i * width,
      z_upper: zMin + (i + 1) * width,
      count,
      high_count: highCount,
      low_count: lowCount,
      high_ratio: highCount / count,
      low_ratio: lowCount / count,
    }
  })
}

function analysisProfileAxes(
  bounds: Record<AnalysisAxisId, [number, number]>,
  valueBase: number,
  weightsArr: number[],
) {
  return (['x', 'y', 'z'] as const).map((axis) => ({
    axis,
    bins: analysisProfileBins(bounds[axis][0], bounds[axis][1], valueBase, weightsArr),
  }))
}

/** CSV 导出：行模式与后端 _csv_export 逐行一致（provenance 注释头 + 稳定表头） */
function analysisCsvExport(summary: AnalysisSummaryOut): string {
  const lines: string[] = [
    `# dataset_id=${summary.dataset_id}`,
    `# case_id=${summary.case_id}`,
    `# analysis_profile=${summary.analysis_profile}`,
    `# source_sha256=${summary.provenance.source_sha256}`,
    `# dataset_version=${summary.provenance.dataset_version}`,
    `# calculation_version=${summary.provenance.calculation_version}`,
    `# generated_at=${summary.provenance.generated_at}`,
    'section,axis,bin_index,metric,lower,upper,value',
  ]
  const stats = summary.statistics
  for (const metric of ['count', 'min', 'max', 'mean', 'median', 'std'] as const) {
    lines.push(`statistics,,,${metric},,,${stats[metric]}`)
  }
  for (const q of ['p05', 'p25', 'p50', 'p75', 'p95']) {
    lines.push(`statistics,,,${q},,,${stats.quantiles[q]}`)
  }
  const distribution = summary.modules.find((m) => m.module_id === 'distribution')
  const histBins = (distribution?.payload.bins ?? []) as AnalysisHistBin[]
  histBins.forEach((bin, index) => {
    lines.push(`distribution,,${index},count,${bin.lower},${bin.upper},${bin.count}`)
  })
  const profiles = summary.modules.find((m) => m.module_id === 'profile_slices')
  const axes = (profiles?.payload.axes ?? []) as { axis: string; bins: AnalysisProfileBin[] }[]
  for (const axis of axes) {
    axis.bins.forEach((bin, index) => {
      for (const metric of ['count', 'mean', 'median'] as const) {
        const value = bin[metric] === null ? '' : String(bin[metric])
        lines.push(`profile,${axis.axis},${index},${metric},${bin.lower},${bin.upper},${value}`)
      }
    })
  }
  return `${lines.join('\n')}\n`
}

// ---- 微震预置（ds-preset）：microseismic_velocity 专属模块全量 ok ----
const MICRO_ANALYSIS_BOUNDS: Record<AnalysisAxisId, [number, number]> = {
  x: [-750, 960],
  y: [-995, 1310],
  z: [-55.556, -50],
}
const MICRO_ANALYSIS_THRESHOLDS = { high: 5.9, low: 5.02 }

function microAnalysisSummary(): AnalysisSummaryOut {
  const weights32 = analysisWeights(20, 40)
  const { bins: anomalyBins, ...anomalySummary } = analysisAnomalyGrid(
    -750,
    960,
    -995,
    1310,
    MICRO_ANALYSIS_THRESHOLDS.low,
    MICRO_ANALYSIS_THRESHOLDS.high,
  )
  const statistics = {
    count: 1911,
    min: 4.21,
    max: 6.83,
    mean: 5.47,
    median: 5.45,
    std: 0.62,
    quantiles: { p05: 4.45, p25: 5.02, p50: 5.45, p75: 5.9, p95: 6.5 },
  }
  const quality = {
    row_count: 1911,
    valid_count: 1911,
    invalid_count: 0,
    duplicate_coordinate_count: 0,
    bounds: MICRO_ANALYSIS_BOUNDS,
  }
  return {
    dataset_id: 'ds-preset',
    case_id: 'builtin-microseismic-vx-1911',
    analysis_profile: 'microseismic_velocity',
    profile_version: 1,
    variable: { name: 'Vx', unit: 'km/s' },
    quality,
    statistics,
    modules: [
      analysisModule('quality', {
        ...quality,
        method: ANALYSIS_METHOD.quality,
        source_fields: { x: 'X_LOCAL_M', y: 'Y_LOCAL_M', z: 'Z_LOCAL_M', value: 'VX_KM_S' },
      }),
      analysisModule('statistics', {
        ...statistics,
        method: ANALYSIS_METHOD.statistics,
        source_fields: { value: 'VX_KM_S' },
      }),
      analysisModule('distribution', {
        bin_count: 32,
        bins: analysisHistogram(4.21, 6.83, weights32, 1911),
        method: ANALYSIS_METHOD.distribution,
        source_fields: { value: 'VX_KM_S' },
      }),
      analysisModule('axis_trends', {
        method: ANALYSIS_METHOD.axisTrends,
        source_fields: { x: 'X_LOCAL_M', y: 'Y_LOCAL_M', z: 'Z_LOCAL_M', value: 'VX_KM_S' },
        axes: analysisProfileAxes(MICRO_ANALYSIS_BOUNDS, 5.2, analysisWeights(15, 30)).map(
          (entry) => ({ axis: entry.axis, sample_count: 1911, bins: entry.bins }),
        ),
      }),
      analysisModule('gradient', {
        grid_size: 16,
        pair_count: 480,
        excluded_pair_count: 12,
        count: 468,
        mean: 0.18,
        p95: 0.52,
        max: 0.91,
        method: ANALYSIS_METHOD.gradient,
        source_fields: { x: 'X_LOCAL_M', y: 'Y_LOCAL_M', value: 'VX_KM_S' },
      }),
      analysisModule('spatial_anomaly', {
        grid_size: 32,
        cell_count: 32 * 32,
        bounds: { x: MICRO_ANALYSIS_BOUNDS.x, y: MICRO_ANALYSIS_BOUNDS.y },
        thresholds: {
          high: MICRO_ANALYSIS_THRESHOLDS.high,
          low: MICRO_ANALYSIS_THRESHOLDS.low,
          source: ANALYSIS_METHOD.thresholdSource,
          method: ANALYSIS_METHOD.thresholdMethod,
        },
        ...anomalySummary,
        bins: anomalyBins,
        method: ANALYSIS_METHOD.spatialAnomaly,
        source_fields: { x: 'X_LOCAL_M', y: 'Y_LOCAL_M', value: 'VX_KM_S' },
      }),
      analysisModule('profile_slices', {
        axes: analysisProfileAxes(MICRO_ANALYSIS_BOUNDS, 5.2, weights32),
      }),
      analysisModule('model_comparison', {
        candidates: [
          {
            result_id: 'cand-1',
            algorithm: 'ordinary_kriging',
            parameters: { variogram_model: 'spherical', neighbor_count: 16 },
            metrics: { rmse: 0.121, mae: 0.092, r2: 0.93, bias: 0.008 },
            materialized: true,
            formal_selection: true,
            result_url: '/results/cand-1',
          },
        ],
      }),
    ],
    provenance: {
      source_sha256: MICRO_SHA,
      dataset_version: 1,
      generated_at: T,
      calculation_version: 'analysis.v1',
    },
  }
}

// ---- 电阻率预置（ds-rho）：log10 分箱/depth_slices/spatial_anomaly ok ----
const RHO_ANALYSIS_BOUNDS: Record<AnalysisAxisId, [number, number]> = {
  x: [-160, -40],
  y: [220, 660],
  z: [-833.0047143, -19.5999],
}
const RHO_ANALYSIS_THRESHOLDS = { high: 52.74, low: 23.41 }

function rhoAnalysisSummary(): AnalysisSummaryOut {
  const weights32 = analysisWeights(200, 500)
  const { bins: anomalyBins, ...anomalySummary } = analysisAnomalyGrid(
    -160,
    -40,
    220,
    660,
    RHO_ANALYSIS_THRESHOLDS.low,
    RHO_ANALYSIS_THRESHOLDS.high,
  )
  const statistics = {
    count: 17547,
    min: RHO_VALUE_RANGE[0],
    max: RHO_VALUE_RANGE[1],
    mean: 42.06,
    median: 31.27,
    std: 24.81,
    quantiles: { p05: 8.12, p25: 23.41, p50: 31.27, p75: 52.74, p95: 98.2 },
  }
  const quality = {
    row_count: RHO_ROW_COUNT,
    valid_count: 17547,
    invalid_count: 2,
    duplicate_coordinate_count: 0,
    bounds: RHO_ANALYSIS_BOUNDS,
  }
  return {
    dataset_id: RHO_DATASET_ID,
    case_id: 'resistivity',
    analysis_profile: 'resistivity',
    profile_version: 1,
    variable: { name: 'RHO', unit: RHO_VALUE_UNIT },
    quality,
    statistics,
    modules: [
      analysisModule('quality', {
        ...quality,
        method: ANALYSIS_METHOD.quality,
        source_fields: { x: 'X', y: 'Y', z: 'Z', value: 'RHO' },
      }),
      analysisModule('statistics', {
        ...statistics,
        method: ANALYSIS_METHOD.statistics,
        source_fields: { value: 'RHO' },
      }),
      analysisModule('distribution', {
        bin_count: 32,
        bins: analysisHistogram(RHO_VALUE_RANGE[0], RHO_VALUE_RANGE[1], weights32, 17547),
        method: ANALYSIS_METHOD.distribution,
        source_fields: { value: 'RHO' },
        // Task 6：log10 分箱（仅严格正值）与原始值分箱并存，排除计数保留
        log10: {
          bin_count: 32,
          bins: analysisHistogram(
            Math.log10(RHO_VALUE_RANGE[0]),
            Math.log10(RHO_VALUE_RANGE[1]),
            analysisWeights(180, 420),
            17545,
          ),
          excluded_non_positive_count: 2,
          method: ANALYSIS_METHOD.log10,
        },
      }),
      analysisModule('spatial_anomaly', {
        grid_size: 32,
        cell_count: 32 * 32,
        bounds: { x: RHO_ANALYSIS_BOUNDS.x, y: RHO_ANALYSIS_BOUNDS.y },
        thresholds: {
          high: RHO_ANALYSIS_THRESHOLDS.high,
          low: RHO_ANALYSIS_THRESHOLDS.low,
          source: ANALYSIS_METHOD.thresholdSource,
          method: ANALYSIS_METHOD.thresholdMethod,
        },
        ...anomalySummary,
        bins: anomalyBins,
        method: ANALYSIS_METHOD.spatialAnomaly,
        source_fields: { x: 'X', y: 'Y', value: 'RHO' },
      }),
      analysisModule('depth_slices', {
        thresholds: {
          high: RHO_ANALYSIS_THRESHOLDS.high,
          low: RHO_ANALYSIS_THRESHOLDS.low,
          source: ANALYSIS_METHOD.thresholdSource,
          method: ANALYSIS_METHOD.thresholdMethod,
        },
        slice_count: 16,
        slices: analysisDepthSlices(RHO_ANALYSIS_BOUNDS.z[0], RHO_ANALYSIS_BOUNDS.z[1], 17547),
        method: ANALYSIS_METHOD.depthSlices,
        source_fields: { z: 'Z', value: 'RHO' },
      }),
      analysisModule('profile_slices', {
        axes: analysisProfileAxes(RHO_ANALYSIS_BOUNDS, 40, weights32),
      }),
      analysisModule('model_comparison', {
        candidates: [
          {
            result_id: RHO_OFFICIAL_RESULT_ID,
            algorithm: 'ordinary_kriging',
            parameters: { variogram_model: 'exponential', neighbor_count: 24 },
            // 官方基线指标：config/presets/resistivity-official-baseline.json 入库公开事实
            metrics: { rmse: 6.454476, mae: 3.251899, r2: 0.923093, bias: -0.095026 },
            materialized: true,
            formal_selection: true,
            result_url: `/results/${RHO_OFFICIAL_RESULT_ID}`,
          },
        ],
      }),
    ],
    provenance: {
      source_sha256: RHO_SHA,
      dataset_version: 1,
      generated_at: T,
      calculation_version: 'analysis.v1',
    },
  }
}

// ---- 瓦斯预置（ds-gas）：depth_slices/spatial_anomaly/gradient ok ----
// 模块清单与 profiles.py 的 _gas_specs 注册表顺序一致；统计/分布数值为
// 本文件确定性演示合成口径（无随机源），绝不冒充真实 58 行计算结果。
const GAS_ANALYSIS_BOUNDS: Record<AnalysisAxisId, [number, number]> = {
  x: [GAS_GRID_BOUNDS[0][0], GAS_GRID_BOUNDS[0][1]],
  y: [GAS_GRID_BOUNDS[1][0], GAS_GRID_BOUNDS[1][1]],
  z: [GAS_GRID_BOUNDS[2][0], GAS_GRID_BOUNDS[2][1]],
}
const GAS_ANALYSIS_THRESHOLDS = { high: 18.9, low: 3.2 }

function gasAnalysisSummary(): AnalysisSummaryOut {
  const weights32 = analysisWeights(3, 9)
  const { bins: anomalyBins, ...anomalySummary } = analysisAnomalyGrid(
    GAS_ANALYSIS_BOUNDS.x[0],
    GAS_ANALYSIS_BOUNDS.x[1],
    GAS_ANALYSIS_BOUNDS.y[0],
    GAS_ANALYSIS_BOUNDS.y[1],
    GAS_ANALYSIS_THRESHOLDS.low,
    GAS_ANALYSIS_THRESHOLDS.high,
  )
  const statistics = {
    count: GAS_ROW_COUNT,
    min: GAS_VALUE_RANGE[0],
    max: GAS_VALUE_RANGE[1],
    mean: 12.41,
    median: 9.8,
    std: 8.63,
    quantiles: { p05: 0.62, p25: 3.2, p50: 9.8, p75: 18.9, p95: 29.74 },
  }
  const quality = {
    row_count: GAS_ROW_COUNT,
    valid_count: GAS_ROW_COUNT,
    invalid_count: 0,
    duplicate_coordinate_count: 0,
    bounds: GAS_ANALYSIS_BOUNDS,
  }
  return {
    dataset_id: GAS_DATASET_ID,
    case_id: 'gas',
    analysis_profile: 'gas_content',
    profile_version: 1,
    variable: { name: 'CH4_content', unit: GAS_VALUE_UNIT },
    quality,
    statistics,
    modules: [
      analysisModule('quality', {
        ...quality,
        method: ANALYSIS_METHOD.quality,
        source_fields: { x: 'X', y: 'Y', z: 'Z', value: 'CH4_content' },
      }),
      analysisModule('statistics', {
        ...statistics,
        method: ANALYSIS_METHOD.statistics,
        source_fields: { value: 'CH4_content' },
      }),
      analysisModule('distribution', {
        bin_count: 32,
        bins: analysisHistogram(GAS_VALUE_RANGE[0], GAS_VALUE_RANGE[1], weights32, GAS_ROW_COUNT),
        method: ANALYSIS_METHOD.distribution,
        source_fields: { value: 'CH4_content' },
      }),
      analysisModule('depth_slices', {
        thresholds: {
          high: GAS_ANALYSIS_THRESHOLDS.high,
          low: GAS_ANALYSIS_THRESHOLDS.low,
          source: ANALYSIS_METHOD.thresholdSource,
          method: ANALYSIS_METHOD.thresholdMethod,
        },
        slice_count: 16,
        slices: analysisDepthSlices(GAS_ANALYSIS_BOUNDS.z[0], GAS_ANALYSIS_BOUNDS.z[1], GAS_ROW_COUNT),
        method: ANALYSIS_METHOD.depthSlices,
        source_fields: { z: 'Z', value: 'CH4_content' },
      }),
      analysisModule('spatial_anomaly', {
        grid_size: 32,
        cell_count: 32 * 32,
        bounds: { x: GAS_ANALYSIS_BOUNDS.x, y: GAS_ANALYSIS_BOUNDS.y },
        thresholds: {
          high: GAS_ANALYSIS_THRESHOLDS.high,
          low: GAS_ANALYSIS_THRESHOLDS.low,
          source: ANALYSIS_METHOD.thresholdSource,
          method: ANALYSIS_METHOD.thresholdMethod,
        },
        ...anomalySummary,
        bins: anomalyBins,
        method: ANALYSIS_METHOD.spatialAnomaly,
        source_fields: { x: 'X', y: 'Y', value: 'CH4_content' },
      }),
      analysisModule('gradient', {
        grid_size: 16,
        pair_count: 480,
        excluded_pair_count: 452,
        count: 28,
        mean: 4.87,
        p95: 11.92,
        max: 17.35,
        method: ANALYSIS_METHOD.gradient,
        source_fields: { x: 'X', y: 'Y', value: 'CH4_content' },
      }),
      analysisModule('profile_slices', {
        axes: analysisProfileAxes(GAS_ANALYSIS_BOUNDS, 10.5, weights32),
      }),
      analysisModule('model_comparison', {
        candidates: [
          {
            result_id: GAS_OFFICIAL_RESULT_ID,
            algorithm: 'ordinary_kriging',
            parameters: GAS_OFFICIAL_PARAMETERS,
            // 官方基线指标：config/presets/gas-official-baseline.json 入库公开事实
            metrics: GAS_OFFICIAL_METRICS,
            materialized: true,
            formal_selection: true,
            result_url: `/results/${GAS_OFFICIAL_RESULT_ID}`,
          },
        ],
      }),
    ],
    provenance: {
      source_sha256: GAS_SHA,
      dataset_version: 1,
      generated_at: T,
      calculation_version: 'analysis.v1',
    },
  }
}

// ---- 通用上传（ds-e2e）：generic_3d 只含通用模块，无专属模块 ----
const GENERIC_ANALYSIS_BOUNDS: Record<AnalysisAxisId, [number, number]> = {
  x: [-50, 50],
  y: [300, 400],
  z: [-350, -50],
}

function genericAnalysisSummary(): AnalysisSummaryOut {
  const weights32 = analysisWeights(1, 6)
  const statistics = {
    count: 144,
    min: 67,
    max: 240,
    mean: 148.5,
    median: 146,
    std: 49.7,
    quantiles: { p05: 76.1, p25: 109.5, p50: 146, p75: 188.5, p95: 228.9 },
  }
  const quality = {
    row_count: 144,
    valid_count: 144,
    invalid_count: 0,
    duplicate_coordinate_count: 0,
    bounds: GENERIC_ANALYSIS_BOUNDS,
  }
  return {
    dataset_id: 'ds-e2e',
    case_id: 'case-e2e',
    analysis_profile: 'generic_3d',
    profile_version: 1,
    variable: { name: '电阻率', unit: 'unknown' },
    quality,
    statistics,
    modules: [
      analysisModule('quality', {
        ...quality,
        method: ANALYSIS_METHOD.quality,
        source_fields: { x: 'x', y: 'y', z: 'z', value: 'rho' },
      }),
      analysisModule('statistics', {
        ...statistics,
        method: ANALYSIS_METHOD.statistics,
        source_fields: { value: 'rho' },
      }),
      analysisModule('distribution', {
        bin_count: 32,
        bins: analysisHistogram(67, 240, weights32, 144),
        method: ANALYSIS_METHOD.distribution,
        source_fields: { value: 'rho' },
      }),
      analysisModule('spatial_extent', {
        grid_size: 32,
        cell_count: 32 * 32,
        bounds: { x: GENERIC_ANALYSIS_BOUNDS.x, y: GENERIC_ANALYSIS_BOUNDS.y },
        bins: analysisSpatialBins(-50, 50, 300, 400, 148),
      }),
      analysisModule('profile_slices', {
        axes: analysisProfileAxes(GENERIC_ANALYSIS_BOUNDS, 148, weights32),
      }),
      analysisModule('model_comparison', { candidates: [] }),
    ],
    provenance: {
      source_sha256: SHA,
      dataset_version: 1,
      generated_at: T,
      calculation_version: 'analysis.v1',
    },
  }
}

function analysisSummaryFor(datasetId: string): AnalysisSummaryOut {
  if (datasetId === 'ds-preset') return microAnalysisSummary()
  if (datasetId === RHO_DATASET_ID) return rhoAnalysisSummary()
  if (datasetId === GAS_DATASET_ID) return gasAnalysisSummary()
  return genericAnalysisSummary()
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

export async function installMockApi(page: Page): Promise<void> {
  const state: MockState = {
    runPolls: 0,
    runStarted: false,
    selections: [],
    exported: false,
    datasetStatus: 'uploaded',
    diagnosisJobPolls: 0,
    extractionJobPolls: 0,
    resultMaterialized: false,
    rhoDsiRunPolls: 0,
    rhoResultMaterialized: false,
    caseName: null,
    caseTrashed: false,
    casePurged: false,
    caseTrashedAt: null,
    comparisonCalls: 0,
    aiRecord: null,
  }

  const runBody = (status: string, completed: number) => ({
    id: 'run-e2e',
    experiment_id: 'exp-e2e',
    status,
    error_code: null,
    metrics: { current_candidate: 1, completed, total: 2, failed: 0 },
    retry_of_run_id: null,
    created_at: T,
        professional_analysis_supported: true,
    updated_at: T,
    started_at: T,
    finished_at: status === 'succeeded' ? T : null,
  })

  const candidatesBody = (done: boolean) => ({
    experiment_id: 'exp-e2e',
    public_metrics: { common_valid_count: 96 },
    latest_run: done ? runBody('succeeded', 2) : runBody('queued', 0),
    candidates: done
      ? [
          {
            id: 'cand-1',
            fingerprint: 'fp-1',
            status: 'succeeded',
            parameters: { power: 1.5, neighbor_count: 8 },
            metrics: { total_count: 100, common_valid_count: 96, candidate_valid_count: 96, candidate_nodata_count: 4, coverage: 0.95, mae: 0.9, rmse: 1.2, r2: 0.94, bias: 0.05 },
            error: null,
          },
          {
            id: 'cand-2',
            fingerprint: 'fp-2',
            status: 'succeeded',
            parameters: { power: 2, neighbor_count: 8 },
            metrics: { total_count: 100, common_valid_count: 96, candidate_valid_count: 96, candidate_nodata_count: 4, coverage: 0.95, mae: 1.6, rmse: 2.4, r2: 0.88, bias: -0.1 },
            error: null,
          },
        ]
      : [],
  })

  const sliceBody = (axis: string, coordinate: number, resultId = 'cand-1') => ({
    result_id: resultId,
    fixed_axis: axis,
    fixed_coordinate: coordinate,
    axes_names: axis === 'z' ? ['x', 'y'] : axis === 'x' ? ['y', 'z'] : ['x', 'z'],
    axes: [
      [-150, -141, -132],
      [260, 292, 324],
    ],
    matrix: [
      [10, 20, 30],
      [40, null, 60],
    ],
    nodata_mask: [
      [false, false, false],
      [false, true, false],
    ],
    value_range: [10, 60],
  })

  // -------------------------------------- v0.7.0 第二批：RenderAsset 剖面分析 mock
  // 三轴坐标严格递增；矩阵非方形；恰好 1 个 NoData 单元（与掩码一致）。
  // 计数来自本夹具自身形状，绝不冒充真实数据统计。
  const SLICE_MOCK_AXES = {
    x: { length: 3, coordinates: [-150, -141, -132], unit: 'm' },
    y: { length: 4, coordinates: [260, 292, 324, 356], unit: 'm' },
    z: { length: 5, coordinates: [-800, -600, -400, -200, 0], unit: 'm' },
  }
  type SliceMockAxis = keyof typeof SLICE_MOCK_AXES
  const sliceAnalysisBody = (assetId: string, axis: SliceMockAxis, index: number) => {
    const rowAxis: SliceMockAxis = axis === 'z' ? 'y' : 'z'
    const colAxis: SliceMockAxis = axis === 'x' ? 'y' : 'x'
    const rows = SLICE_MOCK_AXES[rowAxis].coordinates
    const cols = SLICE_MOCK_AXES[colAxis].coordinates
    const values = rows.map((_, r) =>
      cols.map((_, c) => (r === 1 && c === 1 ? null : 10 + r * 10 + c)),
    )
    const nodata = rows.map((_, r) => cols.map((_, c) => r === 1 && c === 1))
    const total = rows.length * cols.length
    const legacy = assetId.includes('ef')
    return {
      asset_identity: {
        asset_id: assetId,
        source_kind: legacy ? 'builtin_legacy' : 'candidate_result',
        source_id: legacy ? 'resistivity' : 'cand-1',
        grid_sha256: SHA,
        netcdf_sha256: MICRO_SHA,
      },
      property: legacy ? { name: 'RHO', unit: 'unknown' } : { name: '电阻率', unit: 'unknown' },
      axes: SLICE_MOCK_AXES,
      slice: {
        fixed_axis: axis,
        index,
        coordinate: SLICE_MOCK_AXES[axis].coordinates[index],
        sdk_relative_position: index / (SLICE_MOCK_AXES[axis].length - 1),
        row_axis: rowAxis,
        column_axis: colAxis,
        row_coordinates: rows,
        column_coordinates: cols,
        values,
        nodata_mask: nodata,
      },
      statistics: {
        total_count: total,
        valid_count: total - 1,
        nodata_count: 1,
        min: 10,
        max: 10 + (rows.length - 1) * 10 + (cols.length - 1),
        mean: 20,
        std_population: 5,
        p10: 12,
        p50: 20,
        p90: 40,
        // 与夹具自身值一致的三桶口径：11 个有效值（10..42，1 个 NoData）
        // 阈值 [15, 35] → 低 3（10/11/12）/ 正常 5（20..32）/ 高 3（40/41/42）
        low_count: 3,
        normal_count: 5,
        high_count: 3,
        low_ratio: 3 / 11,
        normal_ratio: 5 / 11,
        high_ratio: 3 / 11,
        thresholds: {
          low: 15,
          high: 35,
          source: 'full_grid_quartile',
          method: 'numpy_linear_p25_p75',
        },
      },
      render_profile: null,
    }
  }

  // -------------------------------------- v0.9.0：成果级分析 + AI 辅助研判 mock
  // 与 sliceAnalysisBody 共用同一阈值 [15,35]（后端保证同口径）；坐标落在
  // cand-1 网格 bounds 内；形态与 result_analysis_contracts.py 逐字段一致，
  // 绝不添加合同外字段。
  const RESULT_ANALYSIS_E2E = {
    identity: {
      result_id: 'cand-1',
      grid_sha256: SHA,
      analysis_version: 'result_analysis.v1',
      dimension: '3d',
      coordinate_type: 'local_linear',
    },
    variable: { name: '电阻率', unit: 'unknown' },
    grid: {
      shape: [11, 11, 11],
      valid_count: 1296,
      nodata_count: 35,
      min: 10,
      max: 60,
      mean: 34.6,
      median: 33.8,
      p25: 15,
      p75: 35,
    },
    thresholds: { low: 15, high: 35, source: 'full_grid_quartile', method: 'numpy_linear_p25_p75' },
    composition: {
      buckets: [
        { category: 'low', count: 324, ratio: 0.25 },
        { category: 'normal', count: 648, ratio: 0.5 },
        { category: 'high', count: 324, ratio: 0.25 },
      ],
    },
    depth_profile: {
      status: 'applicable',
      bins: [
        { z_lower: -800, z_upper: -650, valid_count: 320, mean: 22.4, high_count: 26, high_ratio: 0.081 },
        { z_lower: -650, z_upper: -500, valid_count: 328, mean: 38.9, high_count: 148, high_ratio: 0.451 },
        { z_lower: -500, z_upper: -350, valid_count: 326, mean: 39.7, high_count: 118, high_ratio: 0.362 },
        { z_lower: -350, z_upper: -200, valid_count: 322, mean: 36.2, high_count: 32, high_ratio: 0.099 },
      ],
    },
    components_preview: {
      threshold: 35,
      connectivity_rule: 'face_2d4_3d6_v1',
      total: 2,
      returned: 2,
      rows: [
        {
          rank: 1, label: 'A', component_id: 1,
          support_node_count: 48, support_measure: 1200,
          support_unit: 'volume_coordinate_unit3',
          bounds: [[-120, -80], [350, 450], [-650, -550]],
          centroid: [-100, 400, -600],
          value_min: 35.2, value_max: 58, value_mean: 44.6,
          touches_grid_boundary: false,
        },
        {
          rank: 2, label: 'B', component_id: 2,
          support_node_count: 26, support_measure: 640,
          support_unit: 'volume_coordinate_unit3',
          bounds: [[-90, -60], [260, 320], [-350, -250]],
          centroid: [-70, 300, -300],
          value_min: 35, value_max: 45, value_mean: 39.1,
          touches_grid_boundary: true,
        },
      ],
    },
    model_evidence: {
      algorithm: 'idw',
      metrics: { rmse: 1.2, mae: 0.9, r2: 0.94, coverage: 0.96, common_valid_count: 96 },
      common_valid_count: 96,
      formal_selection_id: null,
      formal_selection_note: null,
    },
    findings: [
      {
        id: 'finding-dominant-depth',
        kind: 'dominant_depth_interval',
        title: '高值主要集中在 -650–-500m 深度层段',
        statement: '第二层段高值占比 45.1%，为所有层段最高',
        evidence: [{ name: 'depth_bin_index', value: 1 }, { name: 'high_ratio', value: 0.451 }],
        confidence: 'medium',
        limitations: ['局部坐标系'],
        spatial_target: { kind: 'depth_bin', component_id: null, depth_bin_index: 1 },
      },
      {
        id: 'finding-largest-component',
        kind: 'largest_high_component',
        title: '最大高值连通区为 A 区',
        statement: 'A 区网格支持体积估计 1200，为最大连通区',
        evidence: [{ name: 'label', value: 'A' }, { name: 'support_measure', value: 1200 }],
        confidence: 'high',
        limitations: ['网格支持体积估计非真实地质体积'],
        spatial_target: { kind: 'component', component_id: 1, depth_bin_index: null },
      },
      {
        id: 'finding-boundary-contact',
        kind: 'boundary_contact',
        title: 'B 区接触网格边界',
        statement: 'B 区接触网格边界，需注意外推影响',
        evidence: [{ name: 'boundary_components', value: 'B' }],
        confidence: 'high',
        limitations: ['边界接触不代表异常延伸范围'],
        spatial_target: null,
      },
      {
        id: 'finding-formal-model',
        kind: 'formal_model',
        title: '正式模型为 IDW',
        statement: '公共有效点 96，RMSE 1.2，R² 0.94',
        evidence: [{ name: 'algorithm', value: 'idw' }, { name: 'rmse', value: 1.2 }, { name: 'r2', value: 0.94 }],
        confidence: 'high',
        limitations: ['指标基于交叉验证'],
        spatial_target: null,
      },
      {
        id: 'finding-uncertainty',
        kind: 'uncertainty_availability',
        title: '不确定性证据缺失',
        statement: '该成果未物化专业不确定性层',
        evidence: [{ name: 'availability', value: 'missing' }],
        confidence: 'high',
        limitations: ['不确定性分析不可用'],
        spatial_target: null,
      },
    ],
    provenance: {
      grid_sha256: SHA,
      calculation_version: 'result_analysis.v1',
      threshold_method: 'numpy_linear_p25_p75',
    },
  }

  const aiRecordE2E = (mode: string) => ({
    id: 'ai-e2e-1',
    result_id: 'cand-1',
    grid_sha256: SHA,
    evidence_hash: 'e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6',
    prompt_version: 'ai_review.v1',
    provider: 'deepseek',
    model: 'deepseek-chat',
    mode,
    status: 'succeeded',
    review: {
      spatial_pattern: {
        summary: '高值体元集中于 -650–-500m 层段，A 区为最大连通区且不接触边界',
        evidence_refs: ['result_grid', 'depth_profile', 'component-1', 'depth_bin-1'],
      },
      model_reliability: {
        summary: '公共有效点 96，RMSE 1.2，R² 0.94，模型指标可接受',
        evidence_refs: ['model_evidence'],
      },
      uncertainty_and_risk: {
        summary: 'B 区接触网格边界存在外推风险；不确定性证据缺失',
        evidence_refs: ['component-2', 'uncertainty'],
      },
      review_and_next_checks: {
        summary: '建议复核 -650–-500m 层段切片组成与备选候选模型',
        evidence_refs: ['current_slice', 'depth_bin-1'],
      },
      consensus: {
        consensus: '四视角一致：高值集中于中部层段，正式模型指标可接受',
        disagreements: ['切片高值占比与完整场存在口径差异'],
        recommended_checks: ['复核 -650–-500m 层段切片', '对比备选候选模型指标'],
        decision_options: [
          {
            label: '维持当前模型',
            trigger: 'RMSE 与 R² 满足验收口径',
            benefit: '无需重新计算',
            cost: '无',
            evidence_refs: ['model_evidence'],
          },
          {
            label: '复核备选模型',
            trigger: '正式模型 R² 低于 0.9',
            benefit: '可能进一步降低偏差',
            cost: '需要重新交叉验证耗时',
            evidence_refs: ['model_evidence', 'result_grid'],
          },
        ],
        limitations: ['局部线性坐标，未做地理配准', '网格支持量非真实地质体积'],
      },
      evidence_hash: 'e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6',
      prompt_version: 'ai_review.v1',
      provider: 'deepseek',
      model: 'deepseek-chat',
      mode,
    },
    error_code: null,
    error_message: null,
    usage_prompt_tokens: 812,
    usage_completion_tokens: 346,
    latency_ms: 4321,
    created_at: T,
  })

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace(/^\/api/, '')
    const method = route.request().method()

    if (path === '/health') return json(route, { status: 'ok', version: WEB_VERSION, time: T })
    // v0.8.0：电阻率统一工作台 DTO（builtin_preset 只读散点预置；形态与
    // 微震预置一致，内容来自入库公开合同；旧 legacy 形态已随 Task 6 退役）
    if (path === '/cases/resistivity/workspace' && method === 'GET') {
      return json(route, {
        case_id: 'resistivity',
        title: '地下电阻率',
        case_type: 'generic',
        status: 'active',
        source_kind: 'builtin_preset',
        workspace_kind: 'builtin_preset',
        created_at: T,
        updated_at: T,
        capabilities: {
          data_summary: true,
          experiments: true,
          official_result: true,
          native_volume: true,
        },
        primary_dataset: {
          id: RHO_DATASET_ID,
          case_id: 'resistivity',
          version: 1,
          status: 'validated',
          created_at: T,
          profile: RHO_DATASET_PROFILE,
        },
        official_result: {
          result_id: RHO_OFFICIAL_RESULT_ID,
          url: `/results/${RHO_OFFICIAL_RESULT_ID}`,
          materialized: true,
        },
        provenance_summary: RHO_PROVENANCE,
        data_preparation: {
          state: 'validated',
          dataset_id: null,
          latest_validated_dataset_id: RHO_DATASET_ID,
          next_action: {
            step: 'experiment',
            label: '新建实验',
            url: '/#/cases/resistivity/experiments/new',
          },
          error: null,
        },
        validated_datasets: [],
        abandoned_datasets: [],
        recent_experiments: [],
        recent_results: [],
        links: { detail: '/api/cases/resistivity', publish_status: null },
      })
    }
    // v0.8.0 第三批：瓦斯统一工作台 DTO（builtin_preset 只读散点预置；形态与
    // 电阻率/微震预置逐字段一致，内容来自入库公开合同；旧 legacy "暂缓" 卡已退役）
    if (path === '/cases/gas/workspace' && method === 'GET') {
      return json(route, {
        case_id: 'gas',
        title: '煤层瓦斯',
        case_type: 'generic',
        status: 'active',
        source_kind: 'builtin_preset',
        workspace_kind: 'builtin_preset',
        created_at: T,
        updated_at: T,
        capabilities: {
          data_summary: true,
          experiments: true,
          official_result: true,
          native_volume: true,
        },
        primary_dataset: {
          id: GAS_DATASET_ID,
          case_id: 'gas',
          version: 1,
          status: 'validated',
          created_at: T,
          profile: GAS_DATASET_PROFILE,
        },
        official_result: {
          result_id: GAS_OFFICIAL_RESULT_ID,
          url: `/results/${GAS_OFFICIAL_RESULT_ID}`,
          materialized: true,
        },
        provenance_summary: GAS_PROVENANCE,
        data_preparation: {
          state: 'validated',
          dataset_id: null,
          latest_validated_dataset_id: GAS_DATASET_ID,
          next_action: {
            step: 'experiment',
            label: '新建实验',
            url: '/#/cases/gas/experiments/new',
          },
          error: null,
        },
        validated_datasets: [],
        abandoned_datasets: [],
        recent_experiments: [],
        recent_results: [],
        links: { detail: '/api/cases/gas', publish_status: null },
      })
    }
    if (path === '/cases/case-e2e/workspace' && method === 'GET') {
      if (state.casePurged) {
        return json(route, { error: { code: 'CASE_NOT_FOUND', message: '案例不存在', details: { case_id: 'case-e2e' } } }, 404)
      }
      if (state.caseTrashed) {
        return json(route, { error: { code: 'CASE_TRASHED', message: '案例已移入回收站', details: { case_id: 'case-e2e' } } }, 410)
      }
      const prepMap: Record<string, { state: string; step: string; label: string; url: string | null }> = {
        uploaded: { state: 'needs_mapping', step: 'mapping', label: '继续字段映射', url: `/#/cases/case-e2e/datasets/ds-e2e/prepare` },
        mapped: { state: 'needs_quality_review', step: 'quality_review', label: '继续质量检查', url: `/#/cases/case-e2e/datasets/ds-e2e/prepare` },
        validated: { state: 'ready', step: 'experiment', label: '新建实验', url: `/#/cases/case-e2e/experiments/new` },
        abandoned: { state: 'needs_upload', step: 'upload', label: '上传数据', url: `/#/cases/case-e2e/datasets/new` },
      }
      const prep = prepMap[state.datasetStatus] ?? prepMap.uploaded
      const validatedDatasets = state.datasetStatus === 'validated'
        ? [{
            id: 'ds-e2e',
            case_id: 'case-e2e',
            version: 1,
            status: 'validated',
            created_at: T,
            profile: {
              mapping: {
                dimension: '3d',
                x: 'x',
                y: 'y',
                z: 'z',
                value: 'rho',
                value_name: '电阻率',
                value_unit: 'unknown',
                coordinate_kind: 'local_linear',
              },
              row_count: 1722,
              valid_row_count: 1722,
              invalid_row_count: 0,
            },
          }]
        : []
      return json(route, {
        case_id: 'case-e2e',
        title: state.caseName ?? 'E2E 案例',
        case_type: 'generic',
        status: 'active',
        source_kind: 'upload',
        workspace_kind: 'user_upload',
        lifecycle_state: 'active',
        trashed_at: null,
        created_at: T,
        updated_at: T,
        capabilities: {
          data_summary: true,
          experiments: true,
          official_result: false,
          native_volume: false,
        },
        primary_dataset: {
          id: 'ds-e2e',
          case_id: 'case-e2e',
          version: 1,
          status: state.datasetStatus === 'abandoned' ? 'abandoned' : state.datasetStatus,
          created_at: T,
          profile: {
            mapping: {
              dimension: '3d',
              x: 'x',
              y: 'y',
              z: 'z',
              value: 'rho',
              value_name: '电阻率',
              value_unit: 'unknown',
              coordinate_kind: 'local_linear',
            },
            row_count: 1722,
            valid_row_count: 1722,
            invalid_row_count: 0,
          },
        },
        official_result: null,
        provenance_summary: {
          value_name: '电阻率',
          value_unit: 'unknown',
          coordinate_kind: 'local_linear',
        },
        data_preparation: {
          state: prep.state,
          dataset_id: state.datasetStatus === 'abandoned' ? null : 'ds-e2e',
          latest_validated_dataset_id: state.datasetStatus === 'validated' ? 'ds-e2e' : null,
          next_action: { step: prep.step, label: prep.label, url: prep.url },
          error: null,
        },
        validated_datasets: validatedDatasets,
        recent_experiments: state.datasetStatus === 'validated'
          ? [{
              id: 'exp-e2e',
              name: 'E2E 实验',
              algorithm: 'idw',
              dataset_version_id: 'ds-e2e',
              latest_run_status: 'succeeded',
              succeeded_candidate_count: 2,
              created_at: T,
              url: '/experiments/exp-e2e',
            }]
          : [],
        recent_results: [],
        links: { detail: '/api/cases/case-e2e', publish_status: null },
      })
    }
    if (path === '/cases/builtin-microseismic-vx-1911/workspace' && method === 'GET') {      return json(route, {
        case_id: 'builtin-microseismic-vx-1911',
        title: '微震速度',
        case_type: 'generic',
        status: 'active',
        source_kind: 'builtin_preset',
        workspace_kind: 'builtin_preset',
        created_at: T,
        updated_at: T,
        capabilities: {
          data_summary: true,
          experiments: true,
          official_result: true,
          native_volume: true,
        },
        primary_dataset: {
          id: 'ds-preset',
          case_id: 'builtin-microseismic-vx-1911',
          version: 1,
          status: 'validated',
          created_at: T,
          profile: {
            mapping: {
              dimension: '3d',
              x: 'X_LOCAL_M',
              y: 'Y_LOCAL_M',
              z: 'Z_LOCAL_M',
              value: 'VX_KM_S',
              value_name: 'Vx',
              value_unit: 'km/s',
              coordinate_kind: 'local_linear',
            },
            row_count: 1911,
            valid_row_count: 1911,
            invalid_row_count: 0,
          },
        },
        official_result: {
          result_id: 'cand-1',
          url: '/results/cand-1',
          materialized: true,
        },
        provenance_summary: {
          badge: 'CSV 预置 · 官方普通克里金成果',
          data_form: '三维 X/Y/Z/Vx（局部测线坐标）',
          value_unit: 'km/s',
          coordinate_kind: 'local_linear',
        },
        links: { detail: null, publish_status: null },
      })
    }
    if (path === '/datasets/ds-preset' && method === 'GET') {
      return json(route, {
        id: 'ds-preset',
        case_id: 'builtin-microseismic-vx-1911',
        version: 1,
        status: 'validated',
        profile: {
          mapping: {
            dimension: '3d',
            x: 'X_LOCAL_M',
            y: 'Y_LOCAL_M',
            z: 'Z_LOCAL_M',
            value: 'VX_KM_S',
            value_name: 'Vx',
            value_unit: 'km/s',
            coordinate_kind: 'local_linear',
          },
          row_count: 1911,
          valid_row_count: 1911,
          invalid_row_count: 0,
        },
        created_at: T,
      })
    }
    if (path === '/cases/builtin-microseismic-vx-1911/datasets' && method === 'GET') {
      return json(route, {
        datasets: [
          {
            id: 'ds-preset',
            case_id: 'builtin-microseismic-vx-1911',
            version: 1,
            status: 'validated',
            created_at: T,
          },
        ],
      })
    }
    if (path === '/cases' && method === 'GET') {
      const cases: unknown[] = [
          {
            // v0.8.0：电阻率散点预置卡（builtin_preset；官方成果直达 cand-rho-official 夹具）
            case_id: 'resistivity',
            title: '地下电阻率',
            case_type: 'generic',
            status: 'active',
            source_kind: 'builtin_preset',
            workspace_kind: 'builtin_preset',
            created_at: T,
            updated_at: T,
            capabilities: {
              data_summary: true,
              experiments: true,
              official_result: true,
              native_volume: true,
            },
            primary_dataset: {
              id: RHO_DATASET_ID,
              case_id: 'resistivity',
              version: 1,
              status: 'validated',
              created_at: T,
              profile: RHO_DATASET_PROFILE,
            },
            official_result: {
              result_id: RHO_OFFICIAL_RESULT_ID,
              url: `/results/${RHO_OFFICIAL_RESULT_ID}`,
              materialized: true,
            },
            featured_result: {
              result_id: RHO_OFFICIAL_RESULT_ID,
              url: `/results/${RHO_OFFICIAL_RESULT_ID}`,
              materialized: true,
            },
            provenance_summary: RHO_PROVENANCE,
            links: { detail: '/api/cases/resistivity', publish_status: null },
          },
          {
            // v0.8.0 第三批：瓦斯散点预置卡（builtin_preset；官方成果直达 cand-gas-official 夹具）
            case_id: 'gas',
            title: '煤层瓦斯',
            case_type: 'generic',
            status: 'active',
            source_kind: 'builtin_preset',
            workspace_kind: 'builtin_preset',
            created_at: T,
            updated_at: T,
            capabilities: {
              data_summary: true,
              experiments: true,
              official_result: true,
              native_volume: true,
            },
            primary_dataset: {
              id: GAS_DATASET_ID,
              case_id: 'gas',
              version: 1,
              status: 'validated',
              created_at: T,
              profile: GAS_DATASET_PROFILE,
            },
            official_result: {
              result_id: GAS_OFFICIAL_RESULT_ID,
              url: `/results/${GAS_OFFICIAL_RESULT_ID}`,
              materialized: true,
            },
            featured_result: {
              result_id: GAS_OFFICIAL_RESULT_ID,
              url: `/results/${GAS_OFFICIAL_RESULT_ID}`,
              materialized: true,
            },
            provenance_summary: GAS_PROVENANCE,
            links: { detail: '/api/cases/gas', publish_status: null },
          },
          {
            // v0.7.0：微震 CSV 预置卡（builtin_preset；官方成果直达 cand-1 夹具）
            case_id: 'builtin-microseismic-vx-1911',
            title: '微震速度',
            case_type: 'generic',
            status: 'active',
            source_kind: 'builtin_preset',
            workspace_kind: 'builtin_preset',
            created_at: T,
            updated_at: T,
            capabilities: {
              data_summary: true,
              experiments: true,
              official_result: true,
              native_volume: true,
            },
            primary_dataset: {
              id: 'ds-preset',
              case_id: 'builtin-microseismic-vx-1911',
              version: 1,
              status: 'validated',
              created_at: T,
              profile: {
                mapping: {
                  dimension: '3d',
                  x: 'X_LOCAL_M',
                  y: 'Y_LOCAL_M',
                  z: 'Z_LOCAL_M',
                  value: 'VX_KM_S',
                  value_name: 'Vx',
                  value_unit: 'km/s',
                  coordinate_kind: 'local_linear',
                },
                row_count: 1911,
                valid_row_count: 1911,
                invalid_row_count: 0,
              },
            },
            official_result: {
              result_id: 'cand-1',
              url: '/results/cand-1',
              materialized: true,
            },
            featured_result: {
              result_id: 'cand-1',
              url: '/results/cand-1',
              materialized: true,
            },
            provenance_summary: {
              badge: 'CSV 预置 · 官方普通克里金成果',
              data_form: '三维 X/Y/Z/Vx（局部测线坐标）',
              value_unit: 'km/s',
              coordinate_kind: 'local_linear',
            },
            links: { detail: null, publish_status: null },
          },
          {
            // v0.6.1：体积基准上传卡，携带 featured_result 直达体渲染成果
            // （复用 cand-1 演示成果夹具，成果页路由与真实基准卡一致）
            case_id: 'case-bench-32',
            title: '体积基准 32³',
            case_type: 'generic',
            status: 'active',
            source_kind: 'upload',
            created_at: T,
            updated_at: T,
            featured_result: {
              result_id: 'cand-1',
              url: '/results/cand-1',
              materialized: true,
            },
            links: { detail: '/api/cases/case-bench-32', publish_status: null },
          },
      ]
      // v0.7.0 batch 3：动态注入已创建的 user_upload 案例（trashed/purged 时排除）
      if (state.caseName && !state.caseTrashed && !state.casePurged) {
        cases.push({
          case_id: 'case-e2e',
          title: state.caseName,
          case_type: 'generic',
          status: 'active',
          source_kind: 'upload',
          workspace_kind: 'user_upload',
          lifecycle_state: 'active',
          trashed_at: null,
          created_at: T,
          updated_at: T,
          links: { detail: '/api/cases/case-e2e', publish_status: null },
        })
      }
      return json(route, { cases })
    }
    if (path === '/cases' && method === 'POST') {
      const body = route.request().postDataJSON() as { name: string; case_type?: string }
      if (body.case_type === 'microseismic') {
        return json(
          route,
          { id: 'case-micro', name: body.name, case_type: 'microseismic', config: {}, lifecycle_state: 'active', trashed_at: null, created_at: T, updated_at: T },
          201,
        )
      }
      state.caseName = body.name
      state.caseTrashed = false
      state.casePurged = false
      state.caseTrashedAt = null
      return json(route, { id: 'case-e2e', name: body.name, case_type: 'generic', config: { workspace_kind: 'user_upload' }, lifecycle_state: 'active', trashed_at: null, created_at: T, updated_at: T }, 201)
    }
    if (path === '/cases/case-e2e/datasets/uploads' && method === 'POST') {
      return json(route, {
        id: 'ds-e2e',
        case_id: 'case-e2e',
        version: 1,
        status: 'uploaded',
        profile: { original_filename: 'platform_demo_3d.csv', suffix: 'csv', size_bytes: 4096, source_sha256: SHA },
        created_at: T,
      }, 201)
    }
    // ---------------------------------- v0.7.0 batch 3：案例生命周期
    if (path === '/cases/case-e2e' && method === 'DELETE') {
      if (state.casePurged || !state.caseName) {
        return json(route, { error: { code: 'CASE_NOT_FOUND', message: '案例不存在', details: { case_id: 'case-e2e' } } }, 404)
      }
      state.caseTrashed = true
      state.caseTrashedAt = T
      return json(route, {
        id: 'case-e2e',
        name: state.caseName,
        case_type: 'generic',
        config: { workspace_kind: 'user_upload' },
        lifecycle_state: 'trashed',
        trashed_at: T,
        created_at: T,
        updated_at: T,
      })
    }
    if (path === '/trash/cases' && method === 'GET') {
      const items: unknown[] = []
      if (state.caseName && state.caseTrashed && !state.casePurged) {
        items.push({
          case_id: 'case-e2e',
          name: state.caseName,
          trashed_at: state.caseTrashedAt ?? T,
          counts: { datasets: 1, experiments: 0, results: 0 },
          can_restore: true,
          can_purge: true,
          reason: null,
        })
      }
      return json(route, { cases: items })
    }
    if (path === '/cases/case-e2e/restore' && method === 'POST') {
      if (state.casePurged || !state.caseName) {
        return json(route, { error: { code: 'CASE_NOT_FOUND', message: '案例不存在', details: { case_id: 'case-e2e' } } }, 404)
      }
      if (!state.caseTrashed) {
        return json(route, { error: { code: 'CASE_PURGE_BLOCKED', message: '案例不在回收站', details: { case_id: 'case-e2e' } } }, 409)
      }
      state.caseTrashed = false
      state.caseTrashedAt = null
      return json(route, {
        id: 'case-e2e',
        name: state.caseName,
        case_type: 'generic',
        config: { workspace_kind: 'user_upload' },
        lifecycle_state: 'active',
        trashed_at: null,
        created_at: T,
        updated_at: T,
      })
    }
    if (path === '/cases/case-e2e/purge' && method === 'POST') {
      const body = route.request().postDataJSON() as { confirmation_name: string }
      if (state.casePurged || !state.caseName) {
        return json(route, { error: { code: 'CASE_NOT_FOUND', message: '案例不存在', details: { case_id: 'case-e2e' } } }, 404)
      }
      if (!state.caseTrashed) {
        return json(route, { error: { code: 'CASE_PURGE_BLOCKED', message: '案例未在回收站，无法永久删除', details: { case_id: 'case-e2e' } } }, 409)
      }
      if (body.confirmation_name !== state.caseName) {
        return json(route, { error: { code: 'CASE_PURGE_CONFIRMATION_MISMATCH', message: '确认名称与案例名称不匹配', details: { case_id: 'case-e2e' } } }, 422)
      }
      state.casePurged = true
      return json(route, { operation_id: 'op-purge-1', state: 'cleaned' })
    }
    // ---------------------------------- v0.7.0 batch 3：数据集放弃
    if (path === '/datasets/ds-e2e/abandon' && method === 'POST') {
      if (state.datasetStatus === 'validated' || state.datasetStatus === 'abandoned') {
        return json(route, { error: { code: 'DATASET_ABANDON_FORBIDDEN', message: '只有未完成的数据版本可以放弃', details: { dataset_id: 'ds-e2e', status: state.datasetStatus } } }, 409)
      }
      state.datasetStatus = 'abandoned'
      return json(route, {
        id: 'ds-e2e',
        case_id: 'case-e2e',
        version: 1,
        status: 'abandoned',
        profile: { original_filename: 'platform_demo_3d.csv', suffix: 'csv', size_bytes: 4096, source_sha256: SHA },
        created_at: T,
      })
    }
    if (path === '/datasets/ds-e2e' && method === 'GET') {
      return json(route, {
        id: 'ds-e2e',
        case_id: 'case-e2e',
        version: 1,
        status: state.datasetStatus,
        profile: { original_filename: 'platform_demo_3d.csv', suffix: 'csv', size_bytes: 4096, source_sha256: SHA },
        created_at: T,
      })
    }
    if (path === '/datasets/ds-e2e/inspection') {
      return json(route, {
        dataset_id: 'ds-e2e',
        case_id: 'case-e2e',
        suffix: 'csv',
        sheet: null,
        columns: [
          { name: 'x', inferred_type: 'numeric' },
          { name: 'y', inferred_type: 'numeric' },
          { name: 'z', inferred_type: 'numeric' },
          { name: 'rho', inferred_type: 'numeric' },
        ],
        preview_rows: [{ x: -50, y: 300, z: -50, rho: 67.05 }],
        row_count: 144,
        candidate_mapping: { x: 'x', y: 'y', z: 'z', value: 'rho' },
        limits: { max_upload_bytes: 52428800, max_upload_rows: 500000 },
        profile: { original_filename: 'platform_demo_3d.csv', size_bytes: 4096, source_sha256: SHA },
      })
    }
    if (path === '/datasets/ds-e2e/mapping' && method === 'POST') {
      state.datasetStatus = 'mapped'
      return json(route, {
        id: 'ds-e2e',
        case_id: 'case-e2e',
        version: 1,
        status: 'mapped',
        profile: { dimension: '3d', row_count: 144, valid_row_count: 144, invalid_row_count: 0 },
        created_at: T,
      })
    }
    if (path === '/datasets/ds-e2e/validate' && method === 'POST') {
      state.datasetStatus = 'validated'
      return json(route, {
        status: 'passed',
        checks: [],
        issues: [],
        statistics: {
          ranges: { x: [-50, 50], y: [300, 400], z: [-350, -50], value: [67, 240] },
          unique_coordinate_count: 144,
          duplicate_count: 0,
          conflict_count: 0,
        },
        valid_row_count: 144,
        invalid_row_count: 0,
        row_count: 144,
        source_sha256: SHA,
        standardized_sha256: SHA,
        confirmed: true,
        confirmed_issue_codes: [],
      })
    }
    if (path === '/datasets/ds-e2e/points') {
      return json(route, {
        dataset_id: 'ds-e2e',
        dimension: '3d',
        count: 3,
        served: 3,
        decimate: 1,
        x: [-150, -141, -132],
        y: [260, 292, 324],
        z: [-50, -150, -250],
        values: [10, 50, 60],
        value_range: [10, 60],
        value_name: '电阻率',
        source_sha256: SHA,
      })
    }
    if (path === '/experiments' && method === 'POST') {
      const body = route.request().postDataJSON() as {
        name?: string
        algorithm?: string
        professional_confirmation_id?: string
        neighborhood?: unknown
        empirical_uncertainty?: unknown
      }
      // v0.8.0：电阻率散点预置上的 dsi_like 用户实验（单组参数 → 1 候选）
      if (body.algorithm === 'dsi_like') {
        return json(route, {
          id: RHO_DSI_EXPERIMENT_ID,
          case_id: 'resistivity',
          name: body.name ?? '插值实验',
          params: {
            case_id: 'resistivity',
            name: body.name ?? '插值实验',
            algorithm: 'dsi_like',
            dataset_version_id: RHO_DATASET_ID,
            search_mode: 'manual',
            parameters: RHO_DSI_PARAMETERS,
            validation: RHO_VALIDATION,
            grid: null,
          },
          created_at: T,
          updated_at: T,
        }, 201)
      }
      if (body.professional_confirmation_id) {
        return json(route, {
          id: 'exp-pro',
          case_id: 'case-e2e',
          name: '专业 Kriging 实验',
          params: {
            case_id: 'case-e2e',
            name: '专业 Kriging 实验',
            algorithm: 'ordinary_kriging',
            dataset_version_id: 'ds-e2e',
            search_mode: 'grid',
            parameters: { variogram_model: ['spherical'], neighbor_count: [16, 24] },
            validation: { method: 'spatial_kfold', folds: 5, seed: 20260723, holdout_fraction: 0.2 },
            grid: null,
            professional: {
              confirmation_id: body.professional_confirmation_id,
              neighborhood: body.neighborhood ?? null,
              empirical_uncertainty: body.empirical_uncertainty ?? null,
            },
          },
          created_at: T,
          updated_at: T,
        }, 201)
      }
      return json(route, {
        id: 'exp-e2e',
        case_id: 'case-e2e',
        name: 'E2E 实验',
        params: {
          case_id: 'case-e2e',
          name: 'E2E 实验',
          algorithm: 'idw',
          dataset_version_id: 'ds-e2e',
          search_mode: 'manual',
          parameters: { power: 2, neighbor_count: 16 },
          validation: { method: 'spatial_kfold', folds: 5, seed: 20260723, holdout_fraction: 0.2 },
          grid: null,
        },
        created_at: T,
        updated_at: T,
      }, 201)
    }
    if (path === '/experiments/exp-e2e' && method === 'GET') {
      return json(route, {
        id: 'exp-e2e',
        case_id: 'case-e2e',
        name: 'E2E 实验',
        params: {
          case_id: 'case-e2e',
          name: 'E2E 实验',
          algorithm: 'idw',
          dataset_version_id: 'ds-e2e',
          search_mode: 'manual',
          parameters: { power: 2, neighbor_count: 16 },
          validation: { method: 'spatial_kfold', folds: 5, seed: 20260723, holdout_fraction: 0.2 },
          grid: null,
        },
        created_at: T,
        updated_at: T,
      })
    }
    if (path === '/experiments/exp-e2e/runs' && method === 'POST') {
      state.runStarted = true
      state.runPolls = 0
      return json(route, runBody('queued', 0), 201)
    }
    if (path === '/experiments/exp-e2e/candidates') {
      return json(route, candidatesBody(state.runPolls > 1))
    }
    if (path === '/runs/run-e2e' && method === 'GET') {
      state.runPolls += 1
      return json(route, state.runPolls > 1 ? runBody('succeeded', 2) : runBody('running', 1))
    }
    // ------------------------------------------- v0.8.0 电阻率散点预置数据/实验链
    if (path === '/cases/resistivity/datasets' && method === 'GET') {
      return json(route, {
        datasets: [
          {
            id: RHO_DATASET_ID,
            case_id: 'resistivity',
            version: 1,
            status: 'validated',
            created_at: T,
          },
        ],
      })
    }
    if (path === '/datasets/ds-rho' && method === 'GET') {
      return json(route, {
        id: RHO_DATASET_ID,
        case_id: 'resistivity',
        version: 1,
        status: 'validated',
        profile: RHO_DATASET_PROFILE,
        created_at: T,
      })
    }
    if (path === '/datasets/ds-rho/points' && method === 'GET') {
      return json(route, {
        dataset_id: RHO_DATASET_ID,
        dimension: '3d',
        count: 3,
        served: 3,
        decimate: 1,
        x: [-150, -141, -132],
        y: [260, 292, 324],
        z: [-50, -150, -250],
        values: [10.5, 50.2, 60.7],
        value_range: [10.5, 60.7],
        value_name: 'RHO',
        source_sha256: RHO_SHA,
      })
    }
    if (path === '/cases/resistivity/formal-selections' && method === 'GET') {
      // 只读预置：官方正式选择由 seed 写入，用户候选不得顶替
      return json(route, {
        case_id: 'resistivity',
        selections: [
          {
            id: 'sel-rho-official',
            case_id: 'resistivity',
            candidate_result_id: RHO_OFFICIAL_RESULT_ID,
            selected_by: 'preset-seed',
            note: '官方普通克里金基线（v0.8.0 电阻率散点预置，mock 夹具）',
            created_at: T,
          },
        ],
      })
    }
    // ------------------------------------------- v0.8.0 dsi_like 用户实验运行链
    const rhoDsiRunBody = (status: string, completed: number) => ({
      id: RHO_DSI_RUN_ID,
      experiment_id: RHO_DSI_EXPERIMENT_ID,
      status,
      error_code: null,
      metrics: { current_candidate: status === 'succeeded' ? null : 1, completed, total: 1, failed: 0 },
      retry_of_run_id: null,
      created_at: T,
      professional_analysis_supported: false,
      updated_at: T,
      started_at: T,
      finished_at: status === 'succeeded' ? T : null,
    })
    if (path === `/experiments/${RHO_DSI_EXPERIMENT_ID}` && method === 'GET') {
      return json(route, {
        id: RHO_DSI_EXPERIMENT_ID,
        case_id: 'resistivity',
        name: '插值实验',
        params: {
          case_id: 'resistivity',
          name: '插值实验',
          algorithm: 'dsi_like',
          dataset_version_id: RHO_DATASET_ID,
          search_mode: 'manual',
          parameters: RHO_DSI_PARAMETERS,
          validation: RHO_VALIDATION,
          grid: null,
        },
        created_at: T,
        updated_at: T,
      })
    }
    if (path === `/experiments/${RHO_DSI_EXPERIMENT_ID}/runs` && method === 'POST') {
      state.rhoDsiRunPolls = 0
      return json(route, rhoDsiRunBody('queued', 0), 201)
    }
    if (path === `/runs/${RHO_DSI_RUN_ID}` && method === 'GET') {
      state.rhoDsiRunPolls += 1
      return json(
        route,
        state.rhoDsiRunPolls > 1 ? rhoDsiRunBody('succeeded', 1) : rhoDsiRunBody('running', 0),
      )
    }
    if (path === `/experiments/${RHO_DSI_EXPERIMENT_ID}/candidates` && method === 'GET') {
      const done = state.rhoDsiRunPolls > 1
      return json(route, {
        experiment_id: RHO_DSI_EXPERIMENT_ID,
        public_metrics: { common_valid_count: 17041 },
        latest_run: done ? rhoDsiRunBody('succeeded', 1) : rhoDsiRunBody('queued', 0),
        candidates: done
          ? [
              {
                id: RHO_DSI_RESULT_ID,
                fingerprint: 'fp-rho-dsi-1',
                status: 'succeeded',
                parameters: RHO_DSI_PARAMETERS,
                metrics: {
                  total_count: 17549,
                  common_valid_count: 17041,
                  candidate_valid_count: 17041,
                  candidate_nodata_count: 508,
                  coverage: 0.971,
                  mae: 4.013,
                  rmse: 7.82,
                  r2: 0.89,
                  bias: -0.12,
                },
                error: null,
              },
            ]
          : [],
      })
    }
    if (path === '/results/cand-1' && method === 'GET') {
      // 与真实后端一致：未物化 404 RESULT_NOT_MATERIALIZED，POST materialize 后才可读
      if (!state.resultMaterialized) {
        return json(
          route,
          { error: { code: 'RESULT_NOT_MATERIALIZED', message: '成果尚未生成', details: { result_id: 'cand-1' } } },
          404,
        )
      }
      return json(route, {
        result_id: 'cand-1',
        run_id: 'run-e2e',
        experiment_id: 'exp-e2e',
        dataset_version_id: 'ds-e2e',
        algorithm: 'idw',
        parameters: { power: 1.5, neighbor_count: 8 },
        dimension: '3d',
        shape: [11, 11, 11],
        cell_count: 1331,
        bounds: [[-150, -60], [260, 580], [-800, -200]],
        resolution: [9, 32, 60],
        value_range: [10, 60],
        nodata_count: 0,
        grid_sha256: SHA,
        source_sha256: SHA,
        standardized_sha256: SHA,
        fingerprint: 'fp-1',
        validation: { folds: 5 },
        created_at: T,
        professional_analysis_supported: false,
        evaluation_summary: {
          common_valid_count: 96,
          candidate_valid_count: 96,
          candidate_nodata_count: 4,
          total_count: 100,
          coverage: 0.96,
          rmse: 1.2,
          mae: 0.9,
          r2: 0.94,
          bias: 0.05,
          enhanced_evidence_available: false,
        },
      })
    }
    if (path === '/results/cand-1/preview') {
      return json(route, {
        result_id: 'cand-1',
        dimension: '3d',
        original_cell_count: 1331,
        served_cell_count: 1331,
        stride: 1,
        x: [-150, -141],
        y: [260, 292],
        z: [-800, -740],
        values: [10, 20],
        is_nodata: [false, false],
        value_range: [10, 20],
      })
    }
    if (path === '/results/cand-1/slices') {
      const axis = url.searchParams.get('axis') ?? 'z'
      const coordinate = axis === 'x' ? -150 : axis === 'y' ? 260 : -800
      return json(route, sliceBody(axis, coordinate))
    }
    // v0.9.0：成果级只读分析摘要（identity 绑定 cand-1 + SHA）
    if (path === '/results/cand-1/analysis-summary' && method === 'GET') {
      if (!state.resultMaterialized) {
        return json(
          route,
          { error: { code: 'RESULT_NOT_MATERIALIZED', message: '成果尚未生成', details: { result_id: 'cand-1' } } },
          404,
        )
      }
      return json(route, RESULT_ANALYSIS_E2E)
    }
    // v0.9.0：AI 辅助研判（POST 显式生成 / latest 只读；无记录 404）
    if (path === '/results/cand-1/ai-analysis' && method === 'POST') {
      const body = route.request().postDataJSON() as { mode?: string }
      state.aiRecord = aiRecordE2E(body.mode === 'review' ? 'review' : 'quick')
      return json(route, state.aiRecord, 201)
    }
    if (path === '/results/cand-1/ai-analysis/latest' && method === 'GET') {
      if (!state.aiRecord) {
        return json(
          route,
          { error: { code: 'AI_ANALYSIS_NOT_FOUND', message: '尚无 AI 辅助分析记录', details: { result_id: 'cand-1' } } },
          404,
        )
      }
      return json(route, state.aiRecord)
    }
    if (path === '/results/cand-1/select-formal' && method === 'POST') {
      const body = route.request().postDataJSON() as { note: string; selected_by?: string }
      const record = {
        id: `sel-${state.selections.length + 1}`,
        case_id: 'case-e2e',
        candidate_result_id: 'cand-1',
        selected_by: body.selected_by ?? null,
        note: body.note,
        created_at: T,
      }
      state.selections.push(record)
      return json(route, record, 201)
    }
    if (path === '/cases/case-e2e/formal-selections') {
      return json(route, { case_id: 'case-e2e', selections: state.selections })
    }
    if (path === '/results/cand-1/exports' && method === 'POST') {
      state.exported = true
      return json(route, {
        id: 'zip-e2e',
        candidate_result_id: 'cand-1',
        case_id: 'case-e2e',
        package_sha256: 'ef'.repeat(32),
        file_count: 3,
        files: ['manifest.json', 'metadata.json', 'grid.csv'],
        manifest: {},
      }, 201)
    }
    if (path === '/results/cand-1/publications' && method === 'POST') {
      return json(route, {
        id: 'pub-e2e',
        export_id: 'zip-e2e',
        status: 'manual_required',
        evidence: {
          export_id: 'zip-e2e',
          package: 'var/geomodeling/exports/zip-e2e.zip',
          manual_instruction: '请通过 iServer 管理界面手动发布导出的成果包',
          iserver_rest_publish_status: 'unsupported_on_this_build',
        },
      }, 201)
    }
    // ------------------------------------------- v0.8.0 电阻率预置成果（官方/dsi_like 用户候选）
    // 网格/值域为入库公开合同事实；指标为夹具值，绝不冒充真实计算结果。
    const rhoResultMetadata = (
      resultId: string,
      experimentId: string,
      runId: string,
      algorithm: string,
      parameters: Record<string, unknown>,
      fingerprint: string,
      evaluation: Record<string, unknown>,
    ) => ({
      result_id: resultId,
      run_id: runId,
      experiment_id: experimentId,
      dataset_version_id: RHO_DATASET_ID,
      algorithm,
      parameters,
      dimension: '3d',
      shape: RHO_GRID_SHAPE,
      cell_count: 6762,
      bounds: RHO_GRID_BOUNDS,
      resolution: RHO_GRID_RESOLUTION,
      value_range: RHO_VALUE_RANGE,
      nodata_count: 0,
      grid_sha256: RHO_GRID_SHA,
      source_sha256: RHO_SHA,
      standardized_sha256: RHO_SHA,
      fingerprint,
      validation: { folds: 5 },
      created_at: T,
      professional_analysis_supported: false,
      evaluation_summary: evaluation,
    })
    const rhoDsiMetadata = () =>
      rhoResultMetadata(
        RHO_DSI_RESULT_ID,
        RHO_DSI_EXPERIMENT_ID,
        RHO_DSI_RUN_ID,
        'dsi_like',
        RHO_DSI_PARAMETERS,
        'fp-rho-dsi-1',
        {
          common_valid_count: 17041,
          candidate_valid_count: 17041,
          candidate_nodata_count: 508,
          total_count: 17549,
          coverage: 0.971,
          rmse: 7.82,
          mae: 4.013,
          r2: 0.89,
          bias: -0.12,
          enhanced_evidence_available: false,
        },
      )
    const rhoOfficialMetadata = () =>
      rhoResultMetadata(
        RHO_OFFICIAL_RESULT_ID,
        RHO_OFFICIAL_EXPERIMENT_ID,
        RHO_OFFICIAL_RUN_ID,
        'ordinary_kriging',
        { variogram_model: 'exponential', neighbor_count: 24 },
        'fp-rho-official-1',
        // 官方基线指标：config/presets/resistivity-official-baseline.json 入库公开事实
        {
          common_valid_count: 17547,
          candidate_valid_count: 17547,
          candidate_nodata_count: 2,
          total_count: 17549,
          coverage: 1.0,
          rmse: 6.454476,
          mae: 3.251899,
          r2: 0.923093,
          bias: -0.095026,
          enhanced_evidence_available: false,
        },
      )
    const rhoRenderCapability = (resultId: string) => ({
      source_kind: 'candidate_result',
      source_id: resultId,
      supported: true,
      reason_code: null,
      reason: null,
      dimension: '3d',
      grid_kind: 'regular',
      property_name: 'RHO',
      units: RHO_VALUE_UNIT,
      geolocation_status: 'display_anchor_only',
      display_transform: {
        contract: 'wgs84_display_anchor_v1',
        origin_x: -160,
        origin_y: 220,
        anchor_longitude: 120,
        anchor_latitude: 30,
        anchor_height: 0,
        metres_per_degree_lon: 96486.3,
        metres_per_degree_lat: 110852.4,
      },
      // 候选成果默认 linear + viridis（v0.7.0 第二批合同）
      render_profile: {
        property_name: 'RHO',
        unit: RHO_VALUE_UNIT,
        default_scale: 'linear',
        default_palette: 'viridis',
        log_available: true,
        value_range: RHO_VALUE_RANGE,
        filter_range: RHO_VALUE_RANGE,
        lighting: false,
        gradient_opacity: false,
        bounding_box: true,
        opacity: 1,
      },
    })
    const rhoPreview = (resultId: string) => ({
      result_id: resultId,
      dimension: '3d',
      original_cell_count: 6762,
      served_cell_count: 2,
      stride: 1,
      x: [-160, -140],
      y: [220, 240],
      z: [-833.0047143, -813.0047143],
      values: [12.5, 40.2],
      is_nodata: [false, false],
      value_range: [12.5, 40.2],
    })
    const rhoRenderAsset = (resultId: string, assetId: string) => ({
      id: assetId,
      source_kind: 'candidate_result',
      source_id: resultId,
      renderer: 'supermap_voxelgrid_netcdf',
      status: 'ready',
      grid_sha256: RHO_GRID_SHA,
      netcdf_sha256: RHO_NC_SHA,
      manifest_url: `/api/render-assets/${assetId}/manifest`,
      netcdf_url: `/api/render-assets/${assetId}/volume.nc`,
      error: null,
    })
    if (path === `/experiments/${RHO_OFFICIAL_EXPERIMENT_ID}` && method === 'GET') {
      return json(route, {
        id: RHO_OFFICIAL_EXPERIMENT_ID,
        case_id: 'resistivity',
        name: '官方普通克里金基线',
        params: {
          case_id: 'resistivity',
          name: '官方普通克里金基线',
          algorithm: 'ordinary_kriging',
          dataset_version_id: RHO_DATASET_ID,
          search_mode: 'manual',
          parameters: { variogram_model: 'exponential', neighbor_count: 24 },
          validation: RHO_VALIDATION,
          grid: { bounds: RHO_GRID_BOUNDS, resolution: RHO_GRID_RESOLUTION, max_cells: 1000000 },
        },
        created_at: T,
        updated_at: T,
      })
    }
    // 官方成果：seed 即物化（GET 恒 200）；资产懒创建（GET 404 → 显式 POST）
    if (path === `/results/${RHO_OFFICIAL_RESULT_ID}` && method === 'GET') {
      return json(route, rhoOfficialMetadata())
    }
    if (path === `/results/${RHO_OFFICIAL_RESULT_ID}/materialize` && method === 'POST') {
      return json(route, rhoOfficialMetadata())
    }
    // dsi_like 用户候选：未物化 404 RESULT_NOT_MATERIALIZED，POST materialize 后 200
    if (path === `/results/${RHO_DSI_RESULT_ID}` && method === 'GET') {
      if (!state.rhoResultMaterialized) {
        return json(
          route,
          { error: { code: 'RESULT_NOT_MATERIALIZED', message: '成果尚未生成', details: { result_id: RHO_DSI_RESULT_ID } } },
          404,
        )
      }
      return json(route, rhoDsiMetadata())
    }
    if (path === `/results/${RHO_DSI_RESULT_ID}/materialize` && method === 'POST') {
      state.rhoResultMaterialized = true
      return json(route, rhoDsiMetadata())
    }
    if (
      (path === `/results/${RHO_OFFICIAL_RESULT_ID}/preview` ||
        path === `/results/${RHO_DSI_RESULT_ID}/preview`) &&
      method === 'GET'
    ) {
      const resultId = path.includes(RHO_OFFICIAL_RESULT_ID)
        ? RHO_OFFICIAL_RESULT_ID
        : RHO_DSI_RESULT_ID
      return json(route, rhoPreview(resultId))
    }
    if (
      (path === `/results/${RHO_OFFICIAL_RESULT_ID}/slices` ||
        path === `/results/${RHO_DSI_RESULT_ID}/slices`) &&
      method === 'GET'
    ) {
      const resultId = path.includes(RHO_OFFICIAL_RESULT_ID)
        ? RHO_OFFICIAL_RESULT_ID
        : RHO_DSI_RESULT_ID
      const axis = url.searchParams.get('axis') ?? 'z'
      const coordinate = axis === 'x' ? -160 : axis === 'y' ? 220 : -833.0047143
      return json(route, sliceBody(axis, coordinate, resultId))
    }
    if (
      (path === `/results/${RHO_OFFICIAL_RESULT_ID}/render-capability` ||
        path === `/results/${RHO_DSI_RESULT_ID}/render-capability`) &&
      method === 'GET'
    ) {
      const resultId = path.includes(RHO_OFFICIAL_RESULT_ID)
        ? RHO_OFFICIAL_RESULT_ID
        : RHO_DSI_RESULT_ID
      return json(route, rhoRenderCapability(resultId))
    }
    if (
      (path === `/results/${RHO_OFFICIAL_RESULT_ID}/render-assets/netcdf` ||
        path === `/results/${RHO_DSI_RESULT_ID}/render-assets/netcdf`) &&
      method === 'GET'
    ) {
      return json(
        route,
        { error: { code: 'RENDER_ASSET_NOT_FOUND', message: '该渲染源尚未创建渲染资产', details: {} } },
        404,
      )
    }
    if (path === `/results/${RHO_DSI_RESULT_ID}/render-assets/netcdf` && method === 'POST') {
      return json(route, rhoRenderAsset(RHO_DSI_RESULT_ID, `nc-${'d5'.repeat(16)}`), 201)
    }
    if (path === `/results/${RHO_OFFICIAL_RESULT_ID}/render-assets/netcdf` && method === 'POST') {
      return json(route, rhoRenderAsset(RHO_OFFICIAL_RESULT_ID, `nc-${'d6'.repeat(16)}`), 201)
    }
    // ------------------------------------------- v0.8.0 第三批：瓦斯预置数据/成果链
    // 网格/值域/官方指标为入库公开合同事实（gas-official-baseline.json）；
    // 与电阻率同一形态：官方成果 seed 即物化（GET 恒 200），NetCDF 资产懒创建
    // （GET 404 → 显式 POST 201 ready），绝不隐式变异。
    const gasResultMetadata = () => ({
      result_id: GAS_OFFICIAL_RESULT_ID,
      run_id: GAS_OFFICIAL_RUN_ID,
      experiment_id: GAS_OFFICIAL_EXPERIMENT_ID,
      dataset_version_id: GAS_DATASET_ID,
      algorithm: 'ordinary_kriging',
      parameters: GAS_OFFICIAL_PARAMETERS,
      dimension: '3d',
      shape: GAS_GRID_SHAPE,
      cell_count: GAS_GRID_CELL_COUNT,
      bounds: GAS_GRID_BOUNDS,
      resolution: GAS_GRID_RESOLUTION,
      value_range: GAS_VALUE_RANGE,
      nodata_count: 0,
      grid_sha256: GAS_GRID_SHA,
      source_sha256: GAS_SHA,
      standardized_sha256: GAS_SHA,
      fingerprint: 'fp-gas-official-1',
      validation: { folds: 5 },
      created_at: T,
      professional_analysis_supported: false,
      evaluation_summary: {
        common_valid_count: 58,
        candidate_valid_count: 58,
        candidate_nodata_count: 0,
        total_count: 58,
        coverage: 1.0,
        ...GAS_OFFICIAL_METRICS,
        enhanced_evidence_available: false,
      },
    })
    if (path === '/cases/gas/datasets' && method === 'GET') {
      return json(route, {
        datasets: [
          {
            id: GAS_DATASET_ID,
            case_id: 'gas',
            version: 1,
            status: 'validated',
            created_at: T,
          },
        ],
      })
    }
    if (path === `/datasets/${GAS_DATASET_ID}` && method === 'GET') {
      return json(route, {
        id: GAS_DATASET_ID,
        case_id: 'gas',
        version: 1,
        status: 'validated',
        profile: GAS_DATASET_PROFILE,
        created_at: T,
      })
    }
    if (path === `/datasets/${GAS_DATASET_ID}/points` && method === 'GET') {
      return json(route, {
        dataset_id: GAS_DATASET_ID,
        dimension: '3d',
        count: 3,
        served: 3,
        decimate: 1,
        x: [1100.5, 1250.25, 1400.0],
        y: [1300.75, 2500.5, 3700.25],
        z: [130.2, 145.5, 160.8],
        values: [2.4, 11.6, 21.9],
        value_range: [2.4, 21.9],
        value_name: 'CH4_content',
        source_sha256: GAS_SHA,
      })
    }
    if (path === '/cases/gas/formal-selections' && method === 'GET') {
      // 只读预置：官方正式选择由 seed 写入，用户候选不得顶替
      return json(route, {
        case_id: 'gas',
        selections: [
          {
            id: 'sel-gas-official',
            case_id: 'gas',
            candidate_result_id: GAS_OFFICIAL_RESULT_ID,
            selected_by: 'preset-seed',
            note: '官方插值基线（v0.8.0 第三批瓦斯含量预置，mock 夹具）',
            created_at: T,
          },
        ],
      })
    }
    if (path === `/experiments/${GAS_OFFICIAL_EXPERIMENT_ID}` && method === 'GET') {
      return json(route, {
        id: GAS_OFFICIAL_EXPERIMENT_ID,
        case_id: 'gas',
        name: '官方插值基线',
        params: {
          case_id: 'gas',
          name: '官方插值基线',
          algorithm: 'ordinary_kriging',
          dataset_version_id: GAS_DATASET_ID,
          search_mode: 'manual',
          parameters: GAS_OFFICIAL_PARAMETERS,
          validation: GAS_VALIDATION,
          grid: { bounds: GAS_GRID_BOUNDS, resolution: GAS_GRID_RESOLUTION, max_cells: 1000000 },
        },
        created_at: T,
        updated_at: T,
      })
    }
    if (path === `/results/${GAS_OFFICIAL_RESULT_ID}` && method === 'GET') {
      return json(route, gasResultMetadata())
    }
    if (path === `/results/${GAS_OFFICIAL_RESULT_ID}/materialize` && method === 'POST') {
      return json(route, gasResultMetadata())
    }
    if (path === `/results/${GAS_OFFICIAL_RESULT_ID}/preview` && method === 'GET') {
      return json(route, {
        result_id: GAS_OFFICIAL_RESULT_ID,
        dimension: '3d',
        original_cell_count: GAS_GRID_CELL_COUNT,
        served_cell_count: 2,
        stride: 1,
        x: [1023.802, 1043.802],
        y: [1049.716, 1069.716],
        z: [121.0375, 126.0375],
        values: [1.8, 7.4],
        is_nodata: [false, false],
        value_range: [1.8, 7.4],
      })
    }
    if (path === `/results/${GAS_OFFICIAL_RESULT_ID}/slices` && method === 'GET') {
      const axis = url.searchParams.get('axis') ?? 'z'
      const coordinate = axis === 'x' ? 1023.802 : axis === 'y' ? 1049.716 : 121.0375
      return json(route, sliceBody(axis, coordinate, GAS_OFFICIAL_RESULT_ID))
    }
    if (path === `/results/${GAS_OFFICIAL_RESULT_ID}/render-capability` && method === 'GET') {
      return json(route, {
        source_kind: 'candidate_result',
        source_id: GAS_OFFICIAL_RESULT_ID,
        supported: true,
        reason_code: null,
        reason: null,
        dimension: '3d',
        grid_kind: 'regular',
        property_name: 'CH4_content',
        units: GAS_VALUE_UNIT,
        geolocation_status: 'display_anchor_only',
        display_transform: {
          contract: 'wgs84_display_anchor_v1',
          origin_x: 1023.802,
          origin_y: 1049.716,
          anchor_longitude: 120,
          anchor_latitude: 30,
          anchor_height: 0,
          metres_per_degree_lon: 96486.3,
          metres_per_degree_lat: 110852.4,
        },
        // 候选成果默认 linear + viridis（v0.7.0 第二批合同）
        render_profile: {
          property_name: 'CH4_content',
          unit: GAS_VALUE_UNIT,
          default_scale: 'linear',
          default_palette: 'viridis',
          log_available: true,
          value_range: GAS_VALUE_RANGE,
          filter_range: GAS_VALUE_RANGE,
          lighting: false,
          gradient_opacity: false,
          bounding_box: true,
          opacity: 1,
        },
      })
    }
    if (path === `/results/${GAS_OFFICIAL_RESULT_ID}/render-assets/netcdf` && method === 'GET') {
      return json(
        route,
        { error: { code: 'RENDER_ASSET_NOT_FOUND', message: '该渲染源尚未创建渲染资产', details: {} } },
        404,
      )
    }
    if (path === `/results/${GAS_OFFICIAL_RESULT_ID}/render-assets/netcdf` && method === 'POST') {
      const assetId = `nc-${'f3'.repeat(16)}`
      return json(route, {
        id: assetId,
        source_kind: 'candidate_result',
        source_id: GAS_OFFICIAL_RESULT_ID,
        renderer: 'supermap_voxelgrid_netcdf',
        status: 'ready',
        grid_sha256: GAS_GRID_SHA,
        netcdf_sha256: GAS_NC_SHA,
        manifest_url: `/api/render-assets/${assetId}/manifest`,
        netcdf_url: `/api/render-assets/${assetId}/volume.nc`,
        error: null,
      }, 201)
    }
    // ---------------------------------------------------------------- v0.6.1 NetCDF 原生体渲染
    // 物化是唯一显式变异（POST）；能力/资产状态一律纯 GET，绝不隐式 POST。
    if (path === '/results/cand-1/materialize' && method === 'POST') {
      state.resultMaterialized = true
      return json(route, {
        result_id: 'cand-1',
        run_id: 'run-e2e',
        experiment_id: 'exp-e2e',
        dataset_version_id: 'ds-e2e',
        algorithm: 'idw',
        parameters: { power: 1.5, neighbor_count: 8 },
        dimension: '3d',
        shape: [11, 11, 11],
        cell_count: 1331,
        bounds: [[-150, -60], [260, 580], [-800, -200]],
        resolution: [9, 32, 60],
        value_range: [10, 60],
        nodata_count: 0,
        grid_sha256: SHA,
        source_sha256: SHA,
        standardized_sha256: SHA,
        fingerprint: 'fp-1',
        validation: { folds: 5 },
        created_at: T,
        evaluation_summary: {
          common_valid_count: 96,
          candidate_valid_count: 96,
          candidate_nodata_count: 4,
          total_count: 100,
          coverage: 0.96,
          rmse: 1.2,
          mae: 0.9,
          r2: 0.94,
          bias: 0.05,
          enhanced_evidence_available: false,
        },
      })
    }
    if (path === '/results/cand-1/render-capability' && method === 'GET') {
      return json(route, {
        source_kind: 'candidate_result',
        source_id: 'cand-1',
        supported: true,
        reason_code: null,
        reason: null,
        dimension: '3d',
        grid_kind: 'regular',
        property_name: '电阻率',
        units: 'unknown',
        geolocation_status: 'display_anchor_only',
        display_transform: {
          contract: 'wgs84_display_anchor_v1',
          origin_x: -150,
          origin_y: 260,
          anchor_longitude: 120,
          anchor_latitude: 30,
          anchor_height: 0,
          metres_per_degree_lon: 96486.3,
          metres_per_degree_lat: 110852.4,
        },
        // v0.7.0 第二批：候选成果默认 linear + viridis
        render_profile: {
          property_name: '电阻率',
          unit: 'unknown',
          default_scale: 'linear',
          default_palette: 'viridis',
          log_available: true,
          value_range: [10, 60],
          filter_range: [10, 60],
          lighting: false,
          gradient_opacity: false,
          bounding_box: true,
          opacity: 1,
        },
      })
    }
    if (path === '/results/cand-1/render-assets/netcdf' && method === 'GET') {
      return json(
        route,
        { error: { code: 'RENDER_ASSET_NOT_FOUND', message: '该渲染源尚未创建渲染资产', details: {} } },
        404,
      )
    }
    if (path === '/results/cand-1/render-assets/netcdf' && method === 'POST') {
      const assetId = `nc-${'ab'.repeat(16)}`
      return json(route, {
        id: assetId,
        source_kind: 'candidate_result',
        source_id: 'cand-1',
        renderer: 'supermap_voxelgrid_netcdf',
        status: 'ready',
        grid_sha256: SHA,
        netcdf_sha256: MICRO_SHA,
        manifest_url: `/api/render-assets/${assetId}/manifest`,
        netcdf_url: `/api/render-assets/${assetId}/volume.nc`,
        error: null,
      }, 201)
    }
    // ------------------------------------------------- v0.8.0 内置电阻率退役合同
    // 旧 legacy/S3M 渲染注册/资产/体元路由一律 410 LEGACY_RESISTIVITY_RETIRED，
    // 绝不返回旧 S3M 数值（与真实后端 rendering.py/app.py 的退役响应同构）。
    if (
      (path === '/cases/resistivity/render-capability' && method === 'GET') ||
      (path === '/cases/resistivity/render-assets/netcdf' && (method === 'GET' || method === 'POST')) ||
      (path === '/cases/resistivity/render-sources/import' && method === 'POST') ||
      (path === '/cases/resistivity/voxel-cells' && method === 'GET')
    ) {
      return json(
        route,
        {
          error: {
            code: 'LEGACY_RESISTIVITY_RETIRED',
            message:
              '旧电阻率 legacy 渲染入口已退役：电阻率已迁移为散点预置案例，' +
              '体渲染请使用统一案例工作台的候选成果渲染链',
            details: {
              source_kind: 'builtin_legacy',
              source_id: 'resistivity',
              replacement: '/api/cases/resistivity/workspace',
            },
          },
        },
        410,
      )
    }
    // 首页 iServer 探测点仍读取该路由（真实后端保留）：mock 只携带探测结果字段
    if (path === '/cases/resistivity/publish-status' && method === 'GET') {
      return json(route, { case_id: 'resistivity', iserver_available: false })
    }
    // ------------------------------------------- v0.7.0 第二批：RenderAsset 剖面分析/导出
    if (path.startsWith('/render-assets/') && path.endsWith('/slice-analysis') && method === 'GET') {
      const assetId = path.split('/')[2]
      const axis = (url.searchParams.get('axis') ?? 'z') as 'x' | 'y' | 'z'
      const index = Number(url.searchParams.get('index') ?? '0')
      return json(route, sliceAnalysisBody(assetId, axis, index))
    }
    if (path.startsWith('/render-assets/') && path.endsWith('/slice-exports') && method === 'POST') {
      return json(route, {
        id: 'exp-slice-e2e',
        candidate_result_id: 'cand-1',
        case_id: 'case-e2e',
        package_sha256: SHA,
        file_count: 4,
        files: ['slice.csv', 'statistics.json', 'slice.png', 'manifest.json'],
        manifest: {},
      }, 201)
    }
    if (path === '/exports/exp-slice-e2e/download' && method === 'GET') {
      // attachment 语义：浏览器触发下载而非导航离开当前页面
      return route.fulfill({
        status: 200,
        contentType: 'application/zip',
        headers: { 'content-disposition': 'attachment; filename="slice-analysis.zip"' },
        body: 'mock-slice-analysis-zip',
      })
    }
    // ---------------------------------------------------------------- v0.6 专业建模
    if (path === '/datasets/ds-e2e/professional-diagnostics' && method === 'POST') {
      return json(
        route,
        { diagnosis_id: 'diag-pro-1', job_id: 'job-diag-1', status: 'queued', reused: false },
        202,
      )
    }
    // v0.7.0 batch 3：GET 诊断列表（newest-first，含 job 摘要与 view URL）
    if (path === '/datasets/ds-e2e/professional-diagnostics' && method === 'GET') {
      return json(route, {
        dataset_id: 'ds-e2e',
        diagnostics: [
          {
            diagnosis: {
              id: 'diag-pro-1',
              dataset_version_id: 'ds-e2e',
              status: 'succeeded',
              fingerprint: 'fp-diag-pro-1',
              config: {
                variogram: {
                  lag_count: 12,
                  min_pairs_per_bin: 30,
                  max_pairs: 50000,
                  directions: [
                    { dimension: '2d', azimuth_deg: 0, azimuth_tolerance_deg: 15 },
                    { dimension: '2d', azimuth_deg: 90, azimuth_tolerance_deg: 15 },
                  ],
                },
              },
              manifest: PRO_DIAGNOSIS_MANIFEST,
              error: null,
              created_at: T,
              updated_at: T,
              finished_at: T,
            },
            job: {
              id: 'job-diag-1',
              job_kind: 'professional_diagnosis',
              subject_type: 'professional_diagnostic',
              subject_id: 'diag-pro-1',
              request_fingerprint: 'fp-req-diag-1',
              status: 'succeeded',
              retry_of_job_id: null,
              progress: { phase: 'finalize' },
              error: null,
              created_at: T,
              updated_at: T,
              started_at: T,
              finished_at: T,
            },
            url: '/datasets/ds-e2e/professional-diagnosis?diagnosis=diag-pro-1',
            latest_confirmation: {
              id: 'conf-pro-1',
              diagnostic_id: 'diag-pro-1',
              fingerprint: 'fp-conf-pro-1',
              created_at: T,
              applicable: true,
            },
          },
        ],
      })
    }
    // v0.7.0 batch 3：GET 确认快照（含诊断/数据集/案例身份）
    if (path === '/professional-confirmations/conf-pro-1' && method === 'GET') {
      return json(route, {
        confirmation: {
          id: 'conf-pro-1',
          diagnostic_id: 'diag-pro-1',
          fingerprint: 'fp-conf-pro-1',
          note: '采纳诊断候选主方向（mock 夹具）',
          config: { parameter_origin: 'manual_confirmed', prior: 'user_prior' },
          created_at: T,
        },
        diagnosis_id: 'diag-pro-1',
        diagnosis_status: 'succeeded',
        dataset_id: 'ds-e2e',
        case_id: 'case-e2e',
        fingerprint: 'fp-conf-pro-1',
        config_summary: { parameter_origin: 'manual_confirmed', prior: 'user_prior' },
      })
    }
    if (path === '/analysis-jobs/job-diag-1' && method === 'GET') {
      state.diagnosisJobPolls += 1
      const done = state.diagnosisJobPolls > 1
      return json(route, {
        id: 'job-diag-1',
        job_kind: 'professional_diagnosis',
        subject_type: 'professional_diagnostic',
        subject_id: 'diag-pro-1',
        request_fingerprint: 'fp-req-diag-1',
        status: done ? 'succeeded' : 'running',
        retry_of_job_id: null,
        progress: done ? { phase: 'finalize' } : { phase: 'variogram', completed_bins: 4, total_bins: 24 },
        error: null,
        created_at: T,
        updated_at: T,
        started_at: T,
        finished_at: done ? T : null,
      })
    }
    if (path === '/professional-diagnostics/diag-pro-1' && method === 'GET') {
      return json(route, {
        id: 'diag-pro-1',
        dataset_version_id: 'ds-e2e',
        status: 'succeeded',
        fingerprint: 'fp-diag-pro-1',
        config: {
          variogram: {
            lag_count: 12,
            min_pairs_per_bin: 30,
            max_pairs: 50000,
            directions: [
              { dimension: '2d', azimuth_deg: 0, azimuth_tolerance_deg: 15 },
              { dimension: '2d', azimuth_deg: 90, azimuth_tolerance_deg: 15 },
            ],
          },
        },
        manifest: PRO_DIAGNOSIS_MANIFEST,
        error: null,
        created_at: T,
        updated_at: T,
        finished_at: T,
        latest_confirmation: {
          id: 'conf-pro-1',
          diagnostic_id: 'diag-pro-1',
          fingerprint: 'fp-conf-pro-1',
          created_at: T,
          applicable: true,
        },
      })
    }
    if (path === '/professional-diagnostics/diag-pro-1/variogram' && method === 'GET') {
      return json(route, {
        diagnosis_id: 'diag-pro-1',
        omnidirectional: { total: PRO_OMNI_BINS.length, returned: PRO_OMNI_BINS.length, decimate: 1, rows: PRO_OMNI_BINS },
        directional: { total: PRO_DIRECTIONAL_ROWS.length, returned: PRO_DIRECTIONAL_ROWS.length, decimate: 1, rows: PRO_DIRECTIONAL_ROWS },
        fitted_models: PRO_FITTED_MODELS,
        anisotropy_candidates: PRO_SUGGESTION,
        sampling: { total_pair_count: 20100, used_pair_count: 20100, sampling_rate: 1.0, sampled: false, seed: 42 },
        downloads: {
          omnidirectional: '/api/professional-artifacts/art-omni/download',
          directional: '/api/professional-artifacts/art-directional/download',
        },
      })
    }
    if (path === '/professional-diagnostics/diag-pro-1/confirm' && method === 'POST') {
      const body = route.request().postDataJSON() as Record<string, unknown>
      return json(route, {
        id: 'conf-pro-1',
        diagnostic_id: 'diag-pro-1',
        fingerprint: 'fp-conf-pro-1',
        note: body.note,
        config: { ...body, parameter_origin: 'manual_confirmed', prior: 'user_prior' },
        created_at: T,
      }, 201)
    }
    if (path === '/experiments/exp-pro' && method === 'GET') {
      return json(route, {
        id: 'exp-pro',
        case_id: 'case-e2e',
        name: '专业 Kriging 实验',
        params: {
          case_id: 'case-e2e',
          name: '专业 Kriging 实验',
          algorithm: 'ordinary_kriging',
          dataset_version_id: 'ds-e2e',
          search_mode: 'grid',
          parameters: { variogram_model: ['spherical'], neighbor_count: [16, 24] },
          validation: { method: 'spatial_kfold', folds: 5, seed: 20260723, holdout_fraction: 0.2 },
          grid: null,
        },
        created_at: T,
        updated_at: T,
      })
    }
    if (path === '/experiments/exp-pro/runs' && method === 'POST') {
      return json(route, {
        id: 'run-pro',
        experiment_id: 'exp-pro',
        status: 'queued',
        error_code: null,
        metrics: { current_candidate: 1, completed: 0, total: 2, failed: 0 },
        retry_of_run_id: null,
        created_at: T,
        updated_at: T,
        started_at: null,
        finished_at: null,
      }, 201)
    }
    if (path === '/runs/run-pro' && method === 'GET') {
      state.runPolls += 1
      const done = state.runPolls > 1
      return json(route, {
        id: 'run-pro',
        experiment_id: 'exp-pro',
        status: done ? 'succeeded' : 'running',
        error_code: null,
        metrics: { current_candidate: done ? null : 2, completed: done ? 2 : 1, total: 2, failed: 0 },
        retry_of_run_id: null,
        created_at: T,
        updated_at: T,
        started_at: T,
        finished_at: done ? T : null,
      })
    }
    if (path === '/experiments/exp-pro/candidates' && method === 'GET') {
      return json(route, {
        experiment_id: 'exp-pro',
        public_metrics: { common_valid_count: 128 },
        latest_run: {
          id: 'run-pro',
          experiment_id: 'exp-pro',
          status: 'succeeded',
          error_code: null,
          metrics: { current_candidate: null, completed: 2, total: 2, failed: 0 },
          retry_of_run_id: null,
          created_at: T,
          updated_at: T,
          started_at: T,
          finished_at: T,
        },
        candidates: [
          {
            id: 'cand-pro-1',
            fingerprint: 'fp-pro-1',
            status: 'succeeded',
            parameters: { variogram_model: 'spherical', neighbor_count: 16 },
            metrics: { total_count: 128, common_valid_count: 128, candidate_valid_count: 128, candidate_nodata_count: 0, coverage: 1.0, mae: 0.92, rmse: 1.21, r2: 0.93, bias: 0.04 },
            error: null,
          },
          {
            id: 'cand-pro-2',
            fingerprint: 'fp-pro-2',
            status: 'succeeded',
            parameters: { variogram_model: 'spherical', neighbor_count: 24 },
            metrics: { total_count: 128, common_valid_count: 128, candidate_valid_count: 128, candidate_nodata_count: 0, coverage: 1.0, mae: 1.0, rmse: 1.33, r2: 0.91, bias: 0.05 },
            error: null,
          },
        ],
      })
    }
    if (path === '/results/cand-pro-1' && method === 'GET') {
      return json(route, {
        result_id: 'cand-pro-1',
        run_id: 'run-pro',
        experiment_id: 'exp-pro',
        dataset_version_id: 'ds-e2e',
        algorithm: 'ordinary_kriging',
        parameters: { variogram_model: 'spherical', neighbor_count: 16 },
        dimension: '2d',
        shape: [11, 11],
        cell_count: 121,
        bounds: [[0, 100], [0, 100]],
        resolution: [10, 10],
        value_range: [90, 130],
        nodata_count: 0,
        grid_sha256: PRO_SHA,
        source_sha256: SHA,
        standardized_sha256: SHA,
        fingerprint: 'fp-pro-1',
        validation: { folds: 5 },
        created_at: T,
        professional_analysis_supported: true,
        evaluation_summary: {
          common_valid_count: 96,
          candidate_valid_count: 96,
          candidate_nodata_count: 0,
          total_count: 96,
          coverage: 1.0,
          rmse: 1.21,
          mae: 0.92,
          r2: 0.93,
          bias: 0.04,
          enhanced_evidence_available: true,
        },
      })
    }
    if (path === '/results/cand-pro-1/materialize' && method === 'POST') {
      return json(route, {
        result_id: 'cand-pro-1',
        run_id: 'run-pro',
        experiment_id: 'exp-pro',
        dataset_version_id: 'ds-e2e',
        algorithm: 'ordinary_kriging',
        parameters: { variogram_model: 'spherical', neighbor_count: 16 },
        dimension: '2d',
        shape: [11, 11],
        cell_count: 121,
        bounds: [[0, 100], [0, 100]],
        resolution: [10, 10],
        value_range: [90, 130],
        nodata_count: 0,
        grid_sha256: PRO_SHA,
        source_sha256: SHA,
        standardized_sha256: SHA,
        fingerprint: 'fp-pro-1',
        validation: { folds: 5 },
        created_at: T,
        professional_analysis_supported: true,
        evaluation_summary: {
          common_valid_count: 96,
          candidate_valid_count: 96,
          candidate_nodata_count: 0,
          total_count: 96,
          coverage: 1.0,
          rmse: 1.21,
          mae: 0.92,
          r2: 0.93,
          bias: 0.04,
          enhanced_evidence_available: true,
        },
      })
    }
    if (path === '/results/cand-pro-1/render-capability' && method === 'GET') {
      // 二维成果：与真实后端一致 supported=false + 稳定 RENDER_REQUIRES_3D 原因码
      return json(route, {
        source_kind: 'candidate_result',
        source_id: 'cand-pro-1',
        supported: false,
        reason_code: 'RENDER_REQUIRES_3D',
        reason: '原生体渲染要求三维成果网格',
        dimension: '2d',
        grid_kind: null,
        property_name: '电阻率',
        units: 'unknown',
        geolocation_status: 'display_anchor_only',
        display_transform: null,
      })
    }
    if (path === '/results/cand-pro-1/preview' && method === 'GET') {
      return json(route, PRO_PREVIEW)
    }
    if (path === '/results/cand-pro-1/slices' && method === 'GET') {
      return json(route, {
        result_id: 'cand-pro-1',
        fixed_axis: 'z',
        fixed_coordinate: 0,
        axes_names: ['x', 'y'],
        axes: [
          [0, 10, 20],
          [0, 10, 20],
        ],
        matrix: [
          [95, 101, 108],
          [99, null, 112],
        ],
        nodata_mask: [
          [false, false, false],
          [false, true, false],
        ],
        value_range: [95, 112],
      })
    }
    if (path === '/results/cand-pro-1/professional' && method === 'GET') {
      return json(route, {
        result_id: 'cand-pro-1',
        available: true,
        algorithm: 'ordinary_kriging',
        confirmation_id: 'conf-pro-1',
        capabilities: PRO_CAPABILITIES,
        parameter_provenance: {
          validation: { origin: 'legacy_auto_fold_fit', scope: 'training_fold', evidence: 'fold_assignments.parquet' },
          final: { origin: 'final_full_data_fit', scope: 'full_data', variogram: { model: 'spherical', nugget: 0.05, sill: 1.2, range: 42.0 } },
        },
        manifest: {
          version: 1,
          fingerprint: 'fp-pro-1',
          artifacts: {
            fold_assignments: { file: 'fold_assignments.parquet', sha256: PRO_SHA, bytes: 2048 },
            out_of_fold_predictions: { file: 'out_of_fold_predictions.parquet', sha256: PRO_SHA, bytes: 4096 },
            prediction_diagnostics: { file: 'prediction_diagnostics.json', sha256: PRO_SHA, bytes: 1024 },
          },
          created_at: T,
        professional_analysis_supported: true,
        },
      })
    }
    if (path === '/results/cand-pro-1/folds' && method === 'GET') {
      return json(route, PRO_FOLDS)
    }
    if (path === '/results/cand-pro-1/residuals' && method === 'GET') {
      return json(route, {
        result_id: 'cand-pro-1',
        total: PRO_RESIDUAL_ROWS.length,
        returned: PRO_RESIDUAL_ROWS.length,
        decimate: 1,
        source_row: PRO_RESIDUAL_ROWS.map((r) => r.source_row),
        fold_index: PRO_RESIDUAL_ROWS.map((r) => r.fold_index),
        x: PRO_RESIDUAL_ROWS.map((r) => r.x),
        y: PRO_RESIDUAL_ROWS.map((r) => r.y),
        z: PRO_RESIDUAL_ROWS.map(() => null),
        observed: PRO_RESIDUAL_ROWS.map((r) => r.observed),
        predicted: PRO_RESIDUAL_ROWS.map((r) => r.predicted),
        residual: PRO_RESIDUAL_ROWS.map((r) => r.residual),
        absolute_error: PRO_RESIDUAL_ROWS.map((r) => Math.abs(r.residual)),
        squared_error: PRO_RESIDUAL_ROWS.map((r) => r.residual * r.residual),
        is_nodata: PRO_RESIDUAL_ROWS.map(() => false),
        download_url: '/api/professional-artifacts/art-oof/download',
      })
    }
    if (path === '/results/cand-pro-1/uncertainty/empirical_error' && method === 'GET') {
      return json(route, {
        ...PRO_PREVIEW,
        layer: 'empirical_error',
        values: PRO_PREVIEW.values.map((v) => 0.5 + ((v - 90) % 20) / 10),
        value_range: [0.5, 2.4],
      })
    }
    if (path === '/results/cand-pro-1/uncertainty/kriging_std' && method === 'GET') {
      return json(route, {
        ...PRO_PREVIEW,
        layer: 'kriging_std',
        values: PRO_PREVIEW.values.map((v) => 0.3 + ((v - 90) % 9) / 10),
        value_range: [0.3, 1.1],
      })
    }
    if (path === '/results/cand-pro-1/anomaly-extractions' && method === 'POST') {
      return json(
        route,
        { extraction_id: 'ext-pro-1', job_id: 'job-ext-1', status: 'queued', reused: false },
        202,
      )
    }
    if (path === '/analysis-jobs/job-ext-1' && method === 'GET') {
      state.extractionJobPolls += 1
      const done = state.extractionJobPolls > 1
      return json(route, {
        id: 'job-ext-1',
        job_kind: 'anomaly_extraction',
        subject_type: 'anomaly_extraction',
        subject_id: 'ext-pro-1',
        request_fingerprint: 'fp-req-ext-1',
        status: done ? 'succeeded' : 'running',
        retry_of_job_id: null,
        progress: {},
        error: null,
        created_at: T,
        professional_analysis_supported: true,
        updated_at: T,
        started_at: T,
        finished_at: done ? T : null,
      })
    }
    if (path === '/anomaly-extractions/ext-pro-1' && method === 'GET') {
      return json(route, {
        id: 'ext-pro-1',
        candidate_result_id: 'cand-pro-1',
        status: 'succeeded',
        fingerprint: 'fp-ext-pro-1',
        config: { direction: 'high', threshold: 100, connectivity_rule: 'face_2d4_3d6_v1' },
        manifest: {
          version: 1,
          fingerprint: 'fp-ext-pro-1',
          artifacts: {
            components: { file: 'components.csv', sha256: PRO_SHA, bytes: 256 },
            summary: { file: 'summary.json', sha256: PRO_SHA, bytes: 512 },
            mask: { file: 'mask.npz', sha256: PRO_SHA, bytes: 1024 },
          },
          created_at: T,
        professional_analysis_supported: true,
        },
        error: null,
        components: {
          total: 2,
          returned: 2,
          rows: [
            {
              component_id: 1,
              support_node_count: 6,
              support_measure: 540,
              support_unit: 'area_coordinate_unit2',
              bounds: [[60, 100], [60, 100]],
              centroid: [82, 84],
              value_min: 121,
              value_max: 130,
              value_mean: 126.4,
              touches_grid_boundary: true,
            },
            {
              component_id: 2,
              support_node_count: 3,
              support_measure: 270,
              support_unit: 'area_coordinate_unit2',
              bounds: [[0, 20], [0, 20]],
              centroid: [10, 12],
              value_min: 118,
              value_max: 124,
              value_mean: 121.1,
              touches_grid_boundary: true,
            },
          ],
        },
        created_at: T,
      })
    }
    if (path === '/professional-comparisons' && method === 'POST') {
      const body = route.request().postDataJSON() as { first_result_id: string; second_result_id: string }
      return json(route, {
        first_result_id: body.first_result_id,
        second_result_id: body.second_result_id,
        compatible: true,
        mismatches: [],
        common_valid_count: 128,
        metric_deltas: { rmse: -0.12, mae: -0.08, r2: 0.02, bias: -0.01 },
        grid_difference_available: true,
        grid_difference: { common_valid_count: 121, mean: 0.42, max_abs: 2.31 },
        comparison_fingerprint: 'fp-cmp-pro-1',
      }, 201)
    }
    // ---------------------------------------------------------------- v0.5 微震
    if (path === '/cases/case-micro/datasets' && method === 'GET') {
      return json(route, { datasets: [] })
    }
    if (path === '/cases/case-micro/microseismic-imports' && method === 'POST') {
      return json(
        route,
        { id: 'ds-micro', case_id: 'case-micro', version: 1, status: 'mapped', created_at: T, profile: MICRO_IMPORT_PROFILE },
        201,
      )
    }
    if (path === '/datasets/ds-micro' && method === 'GET') {
      return json(route, {
        id: 'ds-micro',
        case_id: 'case-micro',
        version: 1,
        status: 'mapped',
        profile: MICRO_IMPORT_PROFILE,
        created_at: T,
      })
    }
    if (path === '/datasets/ds-micro/derivation' && method === 'GET') {
      return json(route, MICRO_DERIVATION)
    }
    if (path === '/datasets/ds-micro/validate' && method === 'POST') {
      return json(route, {
        status: 'passed',
        checks: [],
        issues: [],
        statistics: {
          ranges: { x: [-750, 960], y: [-995, 1310], z: [-55.556, -50], value: [0.438684, 0.524804] },
          unique_coordinate_count: 44,
          duplicate_count: 0,
          conflict_count: 0,
        },
        valid_row_count: 44,
        invalid_row_count: 0,
        row_count: 44,
        source_sha256: MICRO_SHA,
        standardized_sha256: MICRO_SHA,
        confirmed: true,
        confirmed_issue_codes: [],
      })
    }
    // ---------------------------------- v0.7.0 batch 3：候选目录与多候选比较
    if (path === '/datasets/ds-e2e/comparison-candidates' && method === 'GET') {
      const candidateSummary = (id: string, expId: string, runId: string, algo: string, params: Record<string, unknown>, rmse: number, mae: number, r2: number, bias: number, fp: string) => ({
        candidate_result_id: id,
        experiment_id: expId,
        run_id: runId,
        algorithm: algo,
        parameters: params,
        selectable: true,
        metrics: { rmse, mae, r2, bias },
        result_url: `/results/${id}`,
        configuration_fingerprint: fp,
      })
      return json(route, {
        dataset_id: 'ds-e2e',
        groups: [
          {
            experiment_id: 'exp-e2e',
            experiment_name: 'E2E 实验',
            candidates: [
              candidateSummary('cand-1', 'exp-e2e', 'run-e2e', 'idw', { power: 1.5, neighbor_count: 8 }, 1.2, 0.9, 0.94, 0.05, 'fp-idw-p15-n8'),
              candidateSummary('cand-2', 'exp-e2e', 'run-e2e', 'idw', { power: 2, neighbor_count: 8 }, 2.4, 1.6, 0.88, -0.1, 'fp-idw-p2-n8'),
            ],
          },
          {
            experiment_id: 'exp-pro',
            experiment_name: '专业 Kriging 实验',
            candidates: [
              candidateSummary('cand-pro-1', 'exp-pro', 'run-pro', 'ordinary_kriging', { variogram_model: 'spherical', neighbor_count: 16 }, 1.21, 0.92, 0.93, 0.04, 'fp-krig-sph-n16'),
              candidateSummary('cand-pro-2', 'exp-pro', 'run-pro', 'ordinary_kriging', { variogram_model: 'spherical', neighbor_count: 24 }, 1.33, 1.0, 0.91, 0.05, 'fp-krig-sph-n24'),
            ],
          },
        ],
      })
    }
    if (path === '/candidate-comparisons' && method === 'POST') {
      const body = route.request().postDataJSON() as { candidate_result_ids: string[] }
      const ids = body.candidate_result_ids
      if (ids.length !== new Set(ids).size || ids.length < 2 || ids.length > 4) {
        return json(route, { error: { code: 'COMPARISON_SELECTION_INVALID', message: '比较选择必须为 2-4 个唯一候选', details: { candidate_result_ids: ids } } }, 422)
      }
      state.comparisonCalls += 1
      const catalog: Record<string, { exp: string; run: string; algo: string; params: Record<string, unknown>; rmse: number; mae: number; r2: number; bias: number; fp: string }> = {
        'cand-1': { exp: 'exp-e2e', run: 'run-e2e', algo: 'idw', params: { power: 1.5, neighbor_count: 8 }, rmse: 1.2, mae: 0.9, r2: 0.94, bias: 0.05, fp: 'fp-idw-p15-n8' },
        'cand-2': { exp: 'exp-e2e', run: 'run-e2e', algo: 'idw', params: { power: 2, neighbor_count: 8 }, rmse: 2.4, mae: 1.6, r2: 0.88, bias: -0.1, fp: 'fp-idw-p2-n8' },
        'cand-pro-1': { exp: 'exp-pro', run: 'run-pro', algo: 'ordinary_kriging', params: { variogram_model: 'spherical', neighbor_count: 16 }, rmse: 1.21, mae: 0.92, r2: 0.93, bias: 0.04, fp: 'fp-krig-sph-n16' },
        'cand-pro-2': { exp: 'exp-pro', run: 'run-pro', algo: 'ordinary_kriging', params: { variogram_model: 'spherical', neighbor_count: 24 }, rmse: 1.33, mae: 1.0, r2: 0.91, bias: 0.05, fp: 'fp-krig-sph-n24' },
      }
      const summaries = ids.map((id) => {
        const c = catalog[id]
        return {
          candidate_result_id: id,
          experiment_id: c.exp,
          run_id: c.run,
          algorithm: c.algo,
          parameters: c.params,
          selectable: true,
          metrics: { rmse: c.rmse, mae: c.mae, r2: c.r2, bias: c.bias },
          result_url: `/results/${id}`,
          configuration_fingerprint: c.fp,
        }
      })
      // 首次比较返回 comparable + ranking；后续返回 incompatible 演示不兼容字段
      if (state.comparisonCalls === 1) {
        const ranking = [...summaries].sort((a, b) => a.metrics.rmse! - b.metrics.rmse!).map((s) => s.candidate_result_id)
        return json(route, {
          candidate_result_ids: ids,
          dataset_version_id: 'ds-e2e',
          comparable: true,
          mismatches: [],
          candidates: summaries,
          ranking,
          comparison_fingerprint: 'fp-multi-cmp-1',
        })
      }
      return json(route, {
        candidate_result_ids: ids,
        dataset_version_id: 'ds-e2e',
        comparable: false,
        mismatches: ['candidate_not_succeeded:cand-2'],
        candidates: summaries,
        ranking: null,
        comparison_fingerprint: 'fp-multi-cmp-2',
      })
    }
    // ---------------------------------- v0.8.0 第二批：统计与空间分析中心
    // summary/export 与真实后端合同逐字段对齐；数值为确定性演示合成口径。
    if (
      (path === '/datasets/ds-preset/analysis-summary' ||
        path === '/datasets/ds-rho/analysis-summary' ||
        path === `/datasets/${GAS_DATASET_ID}/analysis-summary` ||
        path === '/datasets/ds-e2e/analysis-summary') &&
      method === 'GET'
    ) {
      const datasetId = path.split('/')[2]
      if (datasetId === 'ds-e2e' && state.datasetStatus !== 'validated') {
        // 与真实后端一致：未验证 409 DATASET_NOT_VALIDATED（fail-closed）
        return json(
          route,
          {
            error: {
              code: 'DATASET_NOT_VALIDATED',
              message: '数据版本尚未通过验证，分析摘要不可用',
              details: { dataset_id: 'ds-e2e', status: state.datasetStatus },
            },
          },
          409,
        )
      }
      return json(route, analysisSummaryFor(datasetId))
    }
    const analysisExportMatch = /^\/datasets\/(ds-preset|ds-rho|ds-gas|ds-e2e)\/analysis-export$/.exec(
      path,
    )
    if (analysisExportMatch && method === 'GET') {
      const format = url.searchParams.get('format') ?? 'json'
      if (format !== 'json' && format !== 'csv') {
        return json(
          route,
          {
            error: {
              code: 'ANALYSIS_EXPORT_FORMAT_INVALID',
              message: '不支持的导出格式（仅支持 json/csv）',
              details: { format, supported: ['json', 'csv'] },
            },
          },
          422,
        )
      }
      const summary = analysisSummaryFor(analysisExportMatch[1])
      // Content-Disposition 文件名形态与后端一致：analysis-{dataset}-{profile}.{format}
      const filename = `analysis-${summary.dataset_id}-${summary.analysis_profile}.${format}`
      const disposition = `attachment; filename="${filename}"`
      if (format === 'csv') {
        return route.fulfill({
          status: 200,
          contentType: 'text/csv',
          headers: { 'content-disposition': disposition },
          body: analysisCsvExport(summary),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'content-disposition': disposition },
        body: JSON.stringify(summary),
      })
    }
    return json(route, { error: { code: 'MOCK_NOT_FOUND', message: `未 mock 的端点：${method} ${path}`, details: {} } }, 404)
  })
}

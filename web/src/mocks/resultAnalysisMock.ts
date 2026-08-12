// v0.9.0：成果级分析 + 权威切片响应的类型化夹具。
// 内容逐字段复制自后端合同夹具 tests/fixtures_result_analysis/*.json
// （tsconfig 未开 resolveJsonModule，不能直接 import 仓库根 JSON；
// 合同演进时必须与后端夹具同步修改，禁止添加合同外字段）。
import type { ResultAnalysisSummary, SliceAnalysisResponse } from '../api/types'

export const RESULT_ANALYSIS_MOCK_3D: ResultAnalysisSummary = {
  identity: {
    result_id: 'r-3d-normal',
    grid_sha256: 'a64charhexhash00000000000000000000000000000000000000000000000000',
    analysis_version: 'result_analysis.v1',
    dimension: '3d',
    coordinate_type: 'local_linear',
  },
  variable: { name: 'RHO', unit: 'ohm_m' },
  grid: {
    shape: [4, 4, 4],
    valid_count: 60,
    nodata_count: 4,
    min: 1.0,
    max: 100.0,
    mean: 45.0,
    median: 42.0,
    p25: 25.0,
    p75: 70.0,
  },
  thresholds: {
    low: 25.0,
    high: 70.0,
    source: 'full_grid_quartile',
    method: 'numpy_linear_p25_p75',
  },
  composition: {
    buckets: [
      { category: 'low', count: 15, ratio: 0.25 },
      { category: 'normal', count: 30, ratio: 0.5 },
      { category: 'high', count: 15, ratio: 0.25 },
    ],
  },
  depth_profile: {
    status: 'applicable',
    bins: [
      { z_lower: 0.0, z_upper: 10.0, valid_count: 16, mean: 30.0, high_count: 2, high_ratio: 0.125 },
      { z_lower: 10.0, z_upper: 20.0, valid_count: 15, mean: 45.0, high_count: 4, high_ratio: 0.267 },
      { z_lower: 20.0, z_upper: 30.0, valid_count: 15, mean: 55.0, high_count: 5, high_ratio: 0.333 },
      { z_lower: 30.0, z_upper: 40.0, valid_count: 14, mean: 50.0, high_count: 4, high_ratio: 0.286 },
    ],
  },
  components_preview: {
    threshold: 70.0,
    connectivity_rule: 'face_2d4_3d6_v1',
    total: 3,
    returned: 3,
    rows: [
      {
        rank: 1, label: 'A', component_id: 1,
        support_node_count: 8, support_measure: 500.0,
        support_unit: 'volume_coordinate_unit3',
        bounds: [[10.0, 20.0], [10.0, 20.0], [20.0, 30.0]],
        centroid: [15.0, 15.0, 25.0],
        value_min: 72.0, value_max: 100.0, value_mean: 85.0,
        touches_grid_boundary: false,
        empirical_error_scale_mean: 0.3,
        kriging_std_mean: 2.5,
      },
      {
        rank: 2, label: 'B', component_id: 2,
        support_node_count: 4, support_measure: 250.0,
        support_unit: 'volume_coordinate_unit3',
        bounds: [[0.0, 10.0], [10.0, 20.0], [10.0, 20.0]],
        centroid: [5.0, 15.0, 15.0],
        value_min: 71.0, value_max: 80.0, value_mean: 75.0,
        touches_grid_boundary: true,
      },
      {
        rank: 3, label: 'C', component_id: 3,
        support_node_count: 3, support_measure: 150.0,
        support_unit: 'volume_coordinate_unit3',
        bounds: [[20.0, 30.0], [0.0, 10.0], [30.0, 40.0]],
        centroid: [25.0, 5.0, 35.0],
        value_min: 70.0, value_max: 78.0, value_mean: 74.0,
        touches_grid_boundary: true,
      },
    ],
  },
  model_evidence: {
    algorithm: 'ordinary_kriging',
    metrics: { rmse: 5.2, mae: 3.8, r2: 0.92, coverage: 0.95, common_valid_count: 50 },
    common_valid_count: 50,
    formal_selection_id: 'fs-001',
    formal_selection_note: '最佳候选',
  },
  findings: [
    {
      id: 'finding-dominant-depth',
      kind: 'dominant_depth_interval',
      title: '高值主要集中在 20-30m 深度层段',
      statement: '第三层段高值占比 33.3%，为所有层段最高',
      evidence: [{ name: 'depth_bin_index', value: 2 }, { name: 'high_ratio', value: 0.333 }],
      confidence: 'medium',
      limitations: ['局部坐标系'],
      spatial_target: { kind: 'depth_bin', depth_bin_index: 2, component_id: null },
    },
    {
      id: 'finding-largest-component',
      kind: 'largest_high_component',
      title: '最大高值连通区为 A 区',
      statement: 'A 区网格支持体积估计 500.0，为最大连通区',
      evidence: [{ name: 'label', value: 'A' }, { name: 'support_measure', value: 500.0 }],
      confidence: 'high',
      limitations: ['网格支持体积估计非真实地质体积'],
      spatial_target: { kind: 'component', component_id: 1, depth_bin_index: null },
    },
    {
      id: 'finding-boundary-contact',
      kind: 'boundary_contact',
      title: '主要连通区 B 和 C 接触网格边界',
      statement: 'B 区和 C 区均接触网格边界，需注意外推影响',
      evidence: [{ name: 'boundary_components', value: 'B,C' }],
      confidence: 'high',
      limitations: ['边界接触不代表异常延伸范围'],
      spatial_target: null,
    },
    {
      id: 'finding-formal-model',
      kind: 'formal_model',
      title: '正式模型为 Ordinary Kriging',
      statement: '公共有效点 50，RMSE 5.2，R² 0.92',
      evidence: [{ name: 'algorithm', value: 'ordinary_kriging' }, { name: 'rmse', value: 5.2 }, { name: 'r2', value: 0.92 }],
      confidence: 'high',
      limitations: ['指标基于交叉验证'],
      spatial_target: null,
    },
    {
      id: 'finding-uncertainty',
      kind: 'uncertainty_availability',
      title: '不确定性证据可用',
      statement: '经验误差尺度和 Kriging 标准差均已物化',
      evidence: [{ name: 'availability', value: 'available' }],
      confidence: 'high',
      limitations: [],
      spatial_target: null,
    },
  ],
  provenance: {
    grid_sha256: 'a64charhexhash00000000000000000000000000000000000000000000000000',
    calculation_version: 'result_analysis.v1',
    threshold_method: 'numpy_linear_p25_p75',
  },
}

export const RESULT_ANALYSIS_MOCK_2D: ResultAnalysisSummary = {
  identity: {
    result_id: 'r-2d-na',
    grid_sha256: 'b64charhexhash00000000000000000000000000000000000000000000000000',
    analysis_version: 'result_analysis.v1',
    dimension: '2d',
    coordinate_type: 'local_linear',
  },
  variable: { name: 'RHO', unit: 'ohm_m' },
  grid: {
    shape: [10, 10],
    valid_count: 95,
    nodata_count: 5,
    min: 2.0,
    max: 80.0,
    mean: 35.0,
    median: 32.0,
    p25: 18.0,
    p75: 55.0,
  },
  thresholds: {
    low: 18.0,
    high: 55.0,
    source: 'full_grid_quartile',
    method: 'numpy_linear_p25_p75',
  },
  composition: {
    buckets: [
      { category: 'low', count: 24, ratio: 0.253 },
      { category: 'normal', count: 47, ratio: 0.495 },
      { category: 'high', count: 24, ratio: 0.253 },
    ],
  },
  depth_profile: { status: 'not_applicable', bins: [] },
  components_preview: {
    threshold: 55.0,
    connectivity_rule: 'face_2d4_3d6_v1',
    total: 2,
    returned: 2,
    rows: [
      {
        rank: 1, label: 'A', component_id: 1,
        support_node_count: 15, support_measure: 375.0,
        support_unit: 'area_coordinate_unit2',
        bounds: [[20.0, 40.0], [20.0, 40.0]],
        centroid: [30.0, 30.0],
        value_min: 56.0, value_max: 80.0, value_mean: 68.0,
        touches_grid_boundary: false,
      },
      {
        rank: 2, label: 'B', component_id: 2,
        support_node_count: 9, support_measure: 225.0,
        support_unit: 'area_coordinate_unit2',
        bounds: [[0.0, 10.0], [0.0, 10.0]],
        centroid: [5.0, 5.0],
        value_min: 55.0, value_max: 70.0, value_mean: 62.0,
        touches_grid_boundary: true,
      },
    ],
  },
  model_evidence: {
    algorithm: 'idw',
    metrics: { rmse: 4.1, mae: 2.9, r2: 0.88, coverage: 0.91 },
    common_valid_count: 45,
    formal_selection_id: null,
    formal_selection_note: null,
  },
  findings: [
    {
      id: 'finding-largest-component',
      kind: 'largest_high_component',
      title: '最大高值连通区为 A 区',
      statement: 'A 区网格支持面积估计 375.0，为最大连通区',
      evidence: [{ name: 'label', value: 'A' }, { name: 'support_measure', value: 375.0 }],
      confidence: 'high',
      limitations: ['网格支持面积估计非真实地质面积'],
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
      statement: '公共有效点 45，RMSE 4.1，R² 0.88',
      evidence: [{ name: 'algorithm', value: 'idw' }, { name: 'rmse', value: 4.1 }, { name: 'r2', value: 0.88 }],
      confidence: 'high',
      limitations: ['指标基于交叉验证'],
      spatial_target: null,
    },
    {
      id: 'finding-uncertainty',
      kind: 'uncertainty_availability',
      title: '不确定性证据不适用',
      statement: '2D 成果无深度分层；不确定性状态为 not_applicable',
      evidence: [{ name: 'availability', value: 'not_applicable' }],
      confidence: 'high',
      limitations: [],
      spatial_target: null,
    },
  ],
  provenance: {
    grid_sha256: 'b64charhexhash00000000000000000000000000000000000000000000000000',
    calculation_version: 'result_analysis.v1',
    threshold_method: 'numpy_linear_p25_p75',
  },
}

// ---------------------------------------------------------------------------
// 权威切片响应夹具（SliceAnalysisResponse）：z=2（坐标 -400），4×3 矩阵
// 恰好 1 个 NoData；共享完整网格阈值 [25, 70] → 低 3 / 正常 5 / 高 3。
// 计数字段与夹具自身形状一致，绝不冒充真实数据统计。
// ---------------------------------------------------------------------------
const SLICE_MOCK_VALUES: Array<Array<number | null>> = [
  [10, 15, 20],
  [30, null, 40],
  [50, 55, 60],
  [70, 80, 90],
]
const SLICE_MOCK_NODATA = [
  [false, false, false],
  [false, true, false],
  [false, false, false],
  [false, false, false],
]

function sliceAnalysisMock(withThresholds: boolean): SliceAnalysisResponse {
  return {
    asset_identity: {
      asset_id: 'asset-1',
      source_kind: 'candidate_result',
      source_id: 'r-3d-normal',
      grid_sha256: 'a64charhexhash00000000000000000000000000000000000000000000000000',
      netcdf_sha256: 'f64charhexhash00000000000000000000000000000000000000000000000000',
    },
    property: { name: 'RHO', unit: 'ohm_m' },
    axes: {
      x: { length: 3, coordinates: [-150, -141, -132], unit: 'm' },
      y: { length: 4, coordinates: [260, 292, 324, 356], unit: 'm' },
      z: { length: 5, coordinates: [-800, -600, -400, -200, 0], unit: 'm' },
    },
    slice: {
      fixed_axis: 'z',
      index: 2,
      coordinate: -400,
      sdk_relative_position: 0.5,
      row_axis: 'y',
      column_axis: 'x',
      row_coordinates: [260, 292, 324, 356],
      column_coordinates: [-150, -141, -132],
      values: SLICE_MOCK_VALUES,
      nodata_mask: SLICE_MOCK_NODATA,
    },
    statistics: {
      total_count: 12,
      valid_count: 11,
      nodata_count: 1,
      min: 10,
      max: 90,
      mean: 47.3,
      std_population: 26.1,
      p10: 14.5,
      p50: 50,
      p90: 85,
      low_count: withThresholds ? 3 : null,
      normal_count: withThresholds ? 5 : null,
      high_count: withThresholds ? 3 : null,
      low_ratio: withThresholds ? 3 / 11 : null,
      normal_ratio: withThresholds ? 5 / 11 : null,
      high_ratio: withThresholds ? 3 / 11 : null,
      thresholds: withThresholds
        ? {
            low: 25,
            high: 70,
            source: 'full_grid_quartile',
            method: 'numpy_linear_p25_p75',
          }
        : null,
    },
    render_profile: null,
  }
}

export const SLICE_ANALYSIS_MOCK: SliceAnalysisResponse = sliceAnalysisMock(true)
export const SLICE_ANALYSIS_MOCK_NO_THRESHOLDS: SliceAnalysisResponse = sliceAnalysisMock(false)

// ---------------------------------------------------------------------------
// AI 辅助研判记录夹具（AIAnalysisRecord）：未配置降级 / 成功 / 服务错误。
// 与 ai_analysis_contracts.py 逐字段一致；evidence_refs 只指向合法证据 ID。
// ---------------------------------------------------------------------------
import type { AIAnalysisRecord } from '../api/types'

const AI_EVIDENCE_HASH = 'e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6'

export const AI_RECORD_UNAVAILABLE: AIAnalysisRecord = {
  id: 'ai-unavailable-1',
  result_id: 'r-3d-normal',
  grid_sha256: 'a64charhexhash00000000000000000000000000000000000000000000000000',
  evidence_hash: AI_EVIDENCE_HASH,
  prompt_version: 'ai_review.v1',
  provider: 'deepseek',
  model: 'deepseek-chat',
  mode: 'quick',
  status: 'unavailable',
  review: null,
  error_code: 'DEEPSEEK_NOT_CONFIGURED',
  error_message: '服务端未配置 DEEPSEEK_API_KEY 环境变量',
  usage_prompt_tokens: null,
  usage_completion_tokens: null,
  latency_ms: null,
  created_at: '2026-08-11T02:00:00+00:00',
}

export const AI_RECORD_ERROR: AIAnalysisRecord = {
  id: 'ai-error-1',
  result_id: 'r-3d-normal',
  grid_sha256: 'a64charhexhash00000000000000000000000000000000000000000000000000',
  evidence_hash: AI_EVIDENCE_HASH,
  prompt_version: 'ai_review.v1',
  provider: 'deepseek',
  model: 'deepseek-chat',
  mode: 'quick',
  status: 'error',
  review: null,
  error_code: 'DEEPSEEK_TIMEOUT',
  error_message: 'DeepSeek 请求超时（30 秒）',
  usage_prompt_tokens: null,
  usage_completion_tokens: null,
  latency_ms: 30012,
  created_at: '2026-08-11T02:05:00+00:00',
}

export const AI_RECORD_SUCCEEDED: AIAnalysisRecord = {
  id: 'ai-succeeded-1',
  result_id: 'r-3d-normal',
  grid_sha256: 'a64charhexhash00000000000000000000000000000000000000000000000000',
  evidence_hash: AI_EVIDENCE_HASH,
  prompt_version: 'ai_review.v1',
  provider: 'deepseek',
  model: 'deepseek-chat',
  mode: 'quick',
  status: 'succeeded',
  review: {
    spatial_pattern: {
      summary: '高值体元集中在 20-30m 层段，A 区为最大高值连通区，B/C 区接触网格边界',
      evidence_refs: ['result_grid', 'depth_profile', 'component-1', 'depth_bin-2'],
    },
    model_reliability: {
      summary: '公共有效点 50，RMSE 5.2，R² 0.92，正式模型为 Ordinary Kriging',
      evidence_refs: ['model_evidence'],
    },
    uncertainty_and_risk: {
      summary: '不确定性证据已物化；B/C 区边界接触提示外推风险',
      evidence_refs: ['uncertainty', 'component-2', 'component-3'],
    },
    review_and_next_checks: {
      summary: '建议复核 20-30m 层段切片组成与备选候选模型指标',
      evidence_refs: ['current_slice', 'depth_bin-2', 'model_evidence'],
    },
    consensus: {
      consensus: '四个视角一致支持：高值集中于中部层段，正式模型指标可接受',
      disagreements: ['当前切片高值占比与完整场存在轻微口径差异'],
      recommended_checks: ['复核 20-30m 层段切片', '对比备选候选模型公共有效指标'],
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
    evidence_hash: AI_EVIDENCE_HASH,
    prompt_version: 'ai_review.v1',
    provider: 'deepseek',
    model: 'deepseek-chat',
    mode: 'quick',
  },
  error_code: null,
  error_message: null,
  usage_prompt_tokens: 812,
  usage_completion_tokens: 346,
  latency_ms: 4321,
  created_at: '2026-08-11T02:10:00+00:00',
}

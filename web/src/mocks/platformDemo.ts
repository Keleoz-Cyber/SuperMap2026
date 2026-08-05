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
  datasetStatus: 'uploaded' | 'mapped' | 'validated'
  diagnosisJobPolls: number
  extractionJobPolls: number
  // v0.6.1：cand-1 物化状态机——GET /results 未物化 404，POST materialize 后 200
  resultMaterialized: boolean
  // v0.6.1：内置电阻率 legacy 渲染源登记状态机——导入 POST 前未登记，导入后 supported
  legacyRenderSourceRegistered: boolean
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
    legacyRenderSourceRegistered: false,
  }

  const runBody = (status: string, completed: number) => ({
    id: 'run-e2e',
    experiment_id: 'exp-e2e',
    status,
    error_code: null,
    metrics: { current_candidate: 1, completed, total: 2, failed: 0 },
    retry_of_run_id: null,
    created_at: T,
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

  const sliceBody = (axis: string, coordinate: number) => ({
    result_id: 'cand-1',
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

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace(/^\/api/, '')
    const method = route.request().method()

    if (path === '/health') return json(route, { status: 'ok', version: WEB_VERSION, time: T })
    // v0.7.0：统一工作台 DTO（mock 与 /api/cases 卡片身份一致）
    if (path === '/cases/resistivity/workspace' && method === 'GET') {
      return json(route, {
        case_id: 'resistivity',
        title: '地下电阻率',
        status: 'active',
        source_kind: 'builtin_legacy',
        workspace_kind: 'builtin_legacy',
        capabilities: {
          data_summary: true,
          experiments: false,
          official_result: false,
          native_volume: true,
        },
        primary_dataset: null,
        official_result: null,
        provenance_summary: {
          data_form: '三维 X/Y/Z/RHO（局部工程坐标）',
          coordinate: '局部工程坐标',
          unit_note: 'RHO 单位待来源确认',
        },
        links: { detail: '/api/cases/resistivity', publish_status: '/api/cases/resistivity/publish-status' },
      })
    }
    if (path === '/cases/builtin-microseismic-vx-1911/workspace' && method === 'GET') {
      return json(route, {
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
      return json(route, {
        cases: [
          {
            case_id: 'resistivity',
            title: '地下电阻率',
            data_form: '三维 X/Y/Z/RHO（局部工程坐标）',
            status: 'active',
            coordinate: '局部工程坐标',
            unit_note: 'RHO 单位待来源确认',
            v03_stage: 'iServer 纵向闭环',
            source_kind: 'builtin_legacy',
            links: { detail: '/api/cases/resistivity', publish_status: '/api/cases/resistivity/publish-status' },
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
        ],
      })
    }
    if (path === '/cases' && method === 'POST') {
      const body = route.request().postDataJSON() as { name: string; case_type?: string }
      if (body.case_type === 'microseismic') {
        return json(
          route,
          { id: 'case-micro', name: body.name, case_type: 'microseismic', config: {}, created_at: T, updated_at: T },
          201,
        )
      }
      return json(route, { id: 'case-e2e', name: 'E2E 案例', case_type: 'generic', config: {}, created_at: T, updated_at: T }, 201)
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
        professional_confirmation_id?: string
        neighborhood?: unknown
        empirical_uncertainty?: unknown
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
    // ------------------------------------------------- v0.6.1 内置电阻率案例
    // legacy 渲染源登记状态机：导入 POST 前 LEGACY_RENDER_SOURCE_NOT_REGISTERED，
    // 导入后 capability 翻转 supported，资产创建走既有 NetCDF 流程
    if (path === '/cases/resistivity' && method === 'GET') {
      return json(route, {
        case_id: 'resistivity',
        title: '地下电阻率',
        coordinate: { type: 'local', epsg: null, note: '局部工程坐标 · EPSG 未确认 · Z 向下为负' },
        datasets: [],
        validation_split: { spatial_column_overlap: 0, seed: 'e2e-seed' },
        metric_expectations: { common_valid: 100, common_nodata: 0, coverage_rate: 1 },
        models: [],
        baseline_comparison: null,
        metric_source: 'e2e-mock',
        supermap: { version: '12.1.0', datasource_alias: 'rho', dataset_api: '', results: [] },
        views: [],
        issues: [],
      })
    }
    if (path === '/cases/resistivity/publish-status' && method === 'GET') {
      return json(route, {
        case_id: 'resistivity',
        result_id: 'RHO_KRIG_FINAL_20M_40',
        iserver_available: false,
        iserver: { base_url: 'http://localhost:8090/iserver', reachable: false, http_status: null, services: [] },
        service_checks: [],
        evidence_chain: { result_id: 'RHO_KRIG_FINAL_20M_40', states: [] },
        failed_results: [],
        planned_services: {
          data: 'http://localhost:8090/iserver/services/data-rho/rest/data',
          map: 'http://localhost:8090/iserver/services/map-rho/rest/maps/rho',
          realspace: 'http://localhost:8090/iserver/services/3D-WorkSpace/rest/realspace',
          scene_name: 'RHO_三维全值域',
          volume: {
            url: 'http://localhost:8090/iserver/services/3D-WorkSpace/rest/realspace/datas/rho',
            service_name: 'rho-volume',
            scene_name: 'RHO_三维全值域',
            available: false,
            layers: [],
            note: 'S3M 缓存未发布',
          },
        },
      })
    }
    if (path === '/cases/resistivity/points' && method === 'GET') {
      return json(route, {
        case_id: 'resistivity',
        source: 'csv',
        source_label: 'rho_measurements.csv',
        sha256: SHA,
        decimate: 40,
        count: 1000,
        served: 0,
        value_field: 'rho',
        unit_note: 'Ω·m',
        x: [],
        y: [],
        z: [],
        values: [],
        value_range: [10, 120],
        x_range: [-150, -60],
        y_range: [260, 580],
        z_range: [-300, -100],
      })
    }
    if (path === '/cases/resistivity/render-capability' && method === 'GET') {
      const transform = {
        contract: 'wgs84_display_anchor_v1',
        origin_x: -105,
        origin_y: 420,
        anchor_longitude: 120,
        anchor_latitude: 30,
        anchor_height: 0,
        metres_per_degree_lon: 96486.3,
        metres_per_degree_lat: 110852.4,
      }
      if (!state.legacyRenderSourceRegistered) {
        return json(route, {
          source_kind: 'builtin_legacy',
          source_id: 'resistivity',
          supported: false,
          reason_code: 'LEGACY_RENDER_SOURCE_NOT_REGISTERED',
          reason: '内置案例尚未登记权威规则网格，请先运行 render-grid import-csv',
          dimension: '3d',
          grid_kind: null,
          property_name: 'RHO',
          units: 'unknown',
          geolocation_status: 'display_anchor_only',
          display_transform: transform,
        })
      }
      return json(route, {
        source_kind: 'builtin_legacy',
        source_id: 'resistivity',
        supported: true,
        reason_code: null,
        reason: null,
        dimension: '3d',
        grid_kind: 'regular',
        property_name: 'RHO',
        units: 'unknown',
        geolocation_status: 'display_anchor_only',
        display_transform: transform,
      })
    }
    if (path === '/cases/resistivity/render-sources/import' && method === 'POST') {
      state.legacyRenderSourceRegistered = true
      return json(route, {
        source_kind: 'builtin_legacy',
        source_id: 'resistivity',
        grid_sha256: SHA,
        property_name: 'RHO',
        units: 'unknown',
        shape: [3, 4, 5],
        artifact_dir: `builtin_legacy/resistivity/${SHA}`,
        import_source_sha256: MICRO_SHA,
      }, 201)
    }
    if (path === '/cases/resistivity/render-assets/netcdf' && method === 'GET') {
      return json(
        route,
        { error: { code: 'RENDER_ASSET_NOT_FOUND', message: '该渲染源尚未创建渲染资产', details: {} } },
        404,
      )
    }
    if (path === '/cases/resistivity/render-assets/netcdf' && method === 'POST') {
      const assetId = `nc-${'ef'.repeat(16)}`
      return json(route, {
        id: assetId,
        source_kind: 'builtin_legacy',
        source_id: 'resistivity',
        renderer: 'supermap_voxelgrid_netcdf',
        status: 'ready',
        grid_sha256: SHA,
        netcdf_sha256: MICRO_SHA,
        manifest_url: `/api/render-assets/${assetId}/manifest`,
        netcdf_url: `/api/render-assets/${assetId}/volume.nc`,
        error: null,
      }, 201)
    }
    // ---------------------------------------------------------------- v0.6 专业建模
    if (path === '/datasets/ds-e2e/professional-diagnostics' && method === 'POST') {
      return json(
        route,
        { diagnosis_id: 'diag-pro-1', job_id: 'job-diag-1', status: 'queued', reused: false },
        202,
      )
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
    return json(route, { error: { code: 'MOCK_NOT_FOUND', message: `未 mock 的端点：${method} ${path}`, details: {} } }, 404)
  })
}

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
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

export async function installMockApi(page: Page): Promise<void> {
  const state: MockState = { runPolls: 0, runStarted: false, selections: [], exported: false }

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
            case_id: 'microseismic',
            title: '微震速度',
            data_form: '三维 X/Y/Z/Vx（局部测线坐标）',
            status: 'audit_only',
            coordinate: '局部测线坐标（W16 原点）',
            unit_note: 'Vx 单位 km/s',
            v03_stage: '第二案例：v0.5 原始 DAT 导入',
            source_kind: 'builtin_legacy',
            links: { detail: null, publish_status: null },
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
        status: 'uploaded',
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
      return json(route, {
        result_id: 'cand-1',
        run_id: 'run-e2e',
        experiment_id: 'exp-e2e',
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

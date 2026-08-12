import { describe, expect, it } from 'vitest'
import type { AnalysisSummaryResponse } from '../../api/types'
import { buildPresentationFindings } from '../findings'

// 完整电阻率分析摘要夹具：质量 + 模型对比（含正式选择）+ 空间异常 + 深度切片
const SUMMARY: AnalysisSummaryResponse = {
  dataset_id: 'ds-1',
  case_id: 'resistivity',
  analysis_profile: 'resistivity',
  profile_version: 1,
  variable: { name: 'RHO', unit: 'Ω·m' },
  quality: {
    row_count: 100,
    valid_count: 96,
    invalid_count: 4,
    duplicate_coordinate_count: 0,
    bounds: { x: [0, 100], y: [0, 80], z: [-50, 0] },
  },
  statistics: {
    count: 96,
    min: 1.4,
    max: 133.1,
    mean: 22.5,
    median: 18.2,
    std: 15.6,
    quantiles: { p05: 2.1, p25: 8.4, p50: 18.2, p75: 30.9, p95: 88.3 },
  },
  modules: [
    {
      module_id: 'model_comparison',
      status: 'ok',
      message: null,
      payload: {
        candidates: [
          {
            result_id: 'r-formal',
            algorithm: 'ordinary_kriging',
            parameters: { variogram_model: 'exponential', neighbor_count: 24 },
            metrics: { rmse: 6.454476, mae: 3.251899, r2: 0.923093, bias: -0.095026 },
            materialized: true,
            formal_selection: true,
            result_url: '/results/r-formal',
          },
          {
            result_id: 'r-other',
            algorithm: 'idw',
            parameters: { power: 2 },
            metrics: { rmse: 9.1 },
            materialized: true,
            formal_selection: false,
            result_url: '/results/r-other',
          },
        ],
      },
    },
    {
      module_id: 'spatial_anomaly',
      status: 'ok',
      message: null,
      payload: {
        grid_size: 2,
        thresholds: { high: 80, low: 20, method: 'cell_mean_quantiles_p25_p75' },
        high_volume_ratio: 0.125,
        low_volume_ratio: 0.0625,
        bins: [
          { x_lower: 0, x_upper: 50, y_lower: 0, y_upper: 40, count: 30, mean: 95, region: 'high' },
          { x_lower: 50, x_upper: 100, y_lower: 0, y_upper: 40, count: 20, mean: 15, region: 'low' },
          { x_lower: 0, x_upper: 50, y_lower: 40, y_upper: 80, count: 26, mean: 40, region: 'normal' },
          { x_lower: 50, x_upper: 100, y_lower: 40, y_upper: 80, count: 20, mean: 45, region: 'normal' },
        ],
      },
    },
    {
      module_id: 'depth_slices',
      status: 'ok',
      message: null,
      payload: {
        thresholds: { high: 80, low: 20, source: 'valid_value_quantiles_p25_p75', method: 'm' },
        slice_count: 2,
        slices: [
          { z_lower: -50, z_upper: -25, count: 40, high_count: 2, low_count: 20, high_ratio: 0.05, low_ratio: 0.5 },
          { z_lower: -25, z_upper: 0, count: 56, high_count: 30, low_count: 2, high_ratio: 0.5357, low_ratio: 0.0357 },
        ],
      },
    },
  ],
  provenance: {
    source_sha256: 'abc123',
    dataset_version: 3,
    generated_at: '2026-08-10T00:00:00+00:00',
    calculation_version: 'analysis.v1',
  },
}

describe('buildPresentationFindings', () => {
  it('builds ordered evidence-backed findings from a complete summary', () => {
    const findings = buildPresentationFindings(SUMMARY)
    expect(findings.map((x) => x.id)).toEqual([
      'quality',
      'formal-model',
      'spatial-anomaly',
      'profile-depth-slices',
    ])
    expect(findings[0].source.sourceSha256).toBe(SUMMARY.provenance.source_sha256)
    expect(findings[0].source.datasetId).toBe('ds-1')
    expect(findings[0].source.calculationVersion).toBe('analysis.v1')
    expect(findings[2].confidence).toBe('exploratory')
    expect(findings[2].statement).not.toMatch(/危险|安全|储量/)
    expect(findings.every((x) => x.limitations.length > 0)).toBe(true)
  })

  it('quality statement carries finite counts and verified confidence', () => {
    const findings = buildPresentationFindings(SUMMARY)
    expect(findings[0].statement).toBe('有效数据 96/100（96%）')
    expect(findings[0].confidence).toBe('verified')
  })

  it('formal model uses only the formal_selection candidate with finite metrics', () => {
    const findings = buildPresentationFindings(SUMMARY)
    const formal = findings.find((x) => x.id === 'formal-model')
    expect(formal?.statement).toContain('普通克里金')
    expect(formal?.statement).not.toContain('ordinary_kriging')
    expect(formal?.evidence.join(' ')).toContain('RMSE')
    expect(formal?.confidence).toBe('verified')
  })

  it('anomaly finding carries an xy spatial target union of high regions', () => {
    const findings = buildPresentationFindings(SUMMARY)
    const anomaly = findings.find((x) => x.id === 'spatial-anomaly')
    expect(anomaly?.spatialTarget?.axis).toBe('xy')
    expect(anomaly?.spatialTarget?.xRange).toEqual([0, 50])
    expect(anomaly?.spatialTarget?.yRange).toEqual([0, 40])
  })

  it('profile finding localizes the strongest depth slice on z', () => {
    const findings = buildPresentationFindings(SUMMARY)
    const profile = findings.find((x) => x.id === 'profile-depth-slices')
    expect(profile?.spatialTarget?.axis).toBe('z')
    expect(profile?.spatialTarget?.range).toEqual([-25, 0])
  })

  it('generic_3d returns quality/distribution findings without official semantics', () => {
    const generic: AnalysisSummaryResponse = {
      ...SUMMARY,
      analysis_profile: 'generic_3d',
      modules: [
        {
          module_id: 'distribution',
          status: 'ok',
          message: null,
          payload: { bins: [{ lower: 0, upper: 10, count: 5 }] },
        },
      ],
    }
    const findings = buildPresentationFindings(generic)
    expect(findings.map((x) => x.id)).toEqual(['quality', 'distribution'])
    expect(findings.some((x) => x.id.startsWith('profile-'))).toBe(false)
  })

  it('missing or malformed modules produce no finding, never fake evidence', () => {
    const broken: AnalysisSummaryResponse = {
      ...SUMMARY,
      quality: {
        row_count: null,
        valid_count: null,
        invalid_count: null,
        duplicate_coordinate_count: null,
        bounds: null,
      },
      modules: [
        { module_id: 'model_comparison', status: 'error', message: 'x', payload: {} },
        { module_id: 'spatial_anomaly', status: 'ok', message: null, payload: { bins: 'bad' } },
      ],
    }
    expect(buildPresentationFindings(broken)).toEqual([])
  })

  it('no formal selection means no formal-model finding (never inferred by sorting)', () => {
    const noFormal: AnalysisSummaryResponse = {
      ...SUMMARY,
      modules: SUMMARY.modules.map((m) =>
        m.module_id === 'model_comparison'
          ? {
              ...m,
              payload: {
                candidates: (m.payload.candidates as Array<Record<string, unknown>>).map((c) => ({
                  ...c,
                  formal_selection: false,
                })),
              },
            }
          : m,
      ),
    }
    const ids = buildPresentationFindings(noFormal).map((x) => x.id)
    expect(ids).not.toContain('formal-model')
    expect(ids).toContain('quality')
  })

  it('gas findings never emit hazard/reserve wording', () => {
    const gas: AnalysisSummaryResponse = {
      ...SUMMARY,
      analysis_profile: 'gas_content',
      variable: { name: 'CH4_content', unit: 'ml/g' },
    }
    const findings = buildPresentationFindings(gas)
    for (const f of findings) {
      expect(f.statement).not.toMatch(/危险|安全|储量/)
      expect(f.evidence.join(' ')).not.toMatch(/危险|安全|储量/)
    }
  })
})

import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import type { AnalysisSummaryResponse } from '../../../api/types'
import CommandCenterEvidence from '../CommandCenterEvidence.vue'

const SUMMARY: AnalysisSummaryResponse = {
  dataset_id: 'dataset-uuid',
  case_id: 'resistivity',
  analysis_profile: 'resistivity',
  profile_version: 1,
  variable: { name: 'RHO', unit: 'Ω·m' },
  quality: {
    row_count: 100,
    valid_count: 96,
    invalid_count: 4,
    duplicate_coordinate_count: 0,
    bounds: { x: [0, 1], y: [0, 1], z: [0, 1] },
  },
  statistics: null,
  modules: [],
  provenance: {
    source_sha256: 'abcdef0123456789',
    dataset_version: 1,
    generated_at: '2026-08-10T00:00:00+00:00',
    calculation_version: 'analysis.v1',
  },
}

describe('CommandCenterEvidence', () => {
  it('keeps the donut legend separate and fits a three-digit percentage inside the ring', () => {
    const source = String(readFileSync('src/components/home/CommandCenterEvidence.vue'))
    expect(source).toMatch(/\.donut\s*\{[^}]*flex:\s*none;/s)
    expect(source).toMatch(/\.donut-legend[^\{]*\{[^}]*min-width:\s*0;/s)
    expect(source).toMatch(/\.donut-text\s*\{[^}]*font-size:\s*(?:8\.5|9)px;/s)
  })

  it('uses the available desktop footer space for a readable evidence dashboard', () => {
    const source = String(readFileSync('src/components/home/CommandCenterEvidence.vue'))
    expect(source).toMatch(/\.evidence-band\s*\{[^}]*min-height:\s*148px;/s)
    expect(source).toMatch(/\.donut\s*\{[^}]*width:\s*72px;[^}]*height:\s*72px;/s)
    expect(source).toMatch(/\.metric-track\s*\{[^}]*height:\s*8px;/s)
    expect(source).toMatch(/@media \(max-width: 900px\)[\s\S]*?\.evidence-band\s*\{[^}]*min-height:\s*0;/s)
  })

  it('keeps user-facing property copy outside collapsed technical provenance', () => {
    const wrapper = mount(CommandCenterEvidence, {
      props: { summary: SUMMARY, loading: false },
    })

    expect(wrapper.get('[data-test="evidence-property"]').text()).toBe('电阻率（Ω·m）')
    const details = wrapper.get('[data-test="evidence-technical-details"]')
    expect(details.element).toBeInstanceOf(HTMLDetailsElement)
    expect(details.attributes('open')).toBeUndefined()
    expect(details.get('summary').text()).toBe('技术详情')
    expect(details.text()).toContain('abcdef01')
    expect(details.text()).toContain('analysis.v1')
  })
})

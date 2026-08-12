import { describe, expect, it } from 'vitest'
import { CASE_PRESENTATION, resolveCaseProfile } from '../casePresentation'

describe('case presentation contracts', () => {
  it('keeps official cases visually distinct without changing their units or claims', () => {
    expect(CASE_PRESENTATION.resistivity.accent).toBe('gold')
    expect(CASE_PRESENTATION.microseismic_velocity.accent).toBe('violet')
    expect(CASE_PRESENTATION.gas_content.accent).toBe('jade')
    expect(CASE_PRESENTATION.gas_content.forbiddenClaims).toContain('危险等级')
    expect(new Set(Object.values(CASE_PRESENTATION).map((x) => x.accent)).size).toBe(4)
  })

  it('maps every analysis profile to a presentation entry with labels', () => {
    for (const profile of ['resistivity', 'microseismic_velocity', 'gas_content', 'generic_3d'] as const) {
      const entry = CASE_PRESENTATION[profile]
      expect(entry.profile).toBe(profile)
      expect(entry.variableLabel.length).toBeGreaterThan(0)
      expect(entry.narrativeLabel.length).toBeGreaterThan(0)
      expect(entry.forbiddenClaims.length).toBeGreaterThan(0)
    }
  })

  it('keeps generic_3d free of official-case semantic claims', () => {
    expect(CASE_PRESENTATION.generic_3d.accent).toBe('cyan')
    expect(CASE_PRESENTATION.generic_3d.forbiddenClaims).toContain('专业地质结论')
  })

  it('resolves presentation profile from data fields, never from case id', () => {
    // 上传案例：value_name 驱动（与后端 analysis profile 判定同源）
    expect(resolveCaseProfile({ value_name: 'RHO', value_unit: 'Ω·m' })).toBe('resistivity')
    expect(resolveCaseProfile({ value_name: 'Vx', value_unit: 'km/s' })).toBe(
      'microseismic_velocity',
    )
    expect(resolveCaseProfile({ value_name: 'CH4_content', value_unit: 'ml/g' })).toBe(
      'gas_content',
    )
    // 预置卡：无 value_name 时按单位兜底
    expect(resolveCaseProfile({ value_unit: 'Ω·m' })).toBe('resistivity')
    expect(resolveCaseProfile({ value_unit: 'km/s' })).toBe('microseismic_velocity')
    expect(resolveCaseProfile({ value_unit: 'ml/g' })).toBe('gas_content')
    // 未知与缺失一律 generic_3d
    expect(resolveCaseProfile({ value_name: 'density', value_unit: 'g/cm³' })).toBe('generic_3d')
    expect(resolveCaseProfile(null)).toBe('generic_3d')
    expect(resolveCaseProfile(undefined)).toBe('generic_3d')
    // Vx 但单位不符不静默换算，降级 generic
    expect(resolveCaseProfile({ value_name: 'Vx', value_unit: 'm/s' })).toBe('generic_3d')
  })
})

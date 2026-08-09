import { describe, expect, it } from 'vitest'
import { CASE_PRESENTATION } from '../casePresentation'

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
})

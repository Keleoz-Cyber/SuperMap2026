import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  RESULT_ANALYSIS_MOCK_2D,
  RESULT_ANALYSIS_MOCK_3D,
} from '../resultAnalysisMock'

function readBackendFixture(name: string): unknown {
  const cwd = (globalThis as unknown as { process: { cwd(): string } }).process.cwd()
  const path = resolve(cwd, '..', 'tests', 'fixtures_result_analysis', name)
  return JSON.parse(new TextDecoder().decode(readFileSync(path)))
}

function omitNullObjectFields(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(omitNullObjectFields)
  if (value === null || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.entries(value)
      .filter(([, item]) => item !== null)
      .map(([key, item]) => [key, omitNullObjectFields(item)]),
  )
}

describe('result analysis mock parity', () => {
  it('keeps the 3D TypeScript mock synchronized with the backend JSON fixture', () => {
    expect(omitNullObjectFields(RESULT_ANALYSIS_MOCK_3D)).toEqual(
      omitNullObjectFields(readBackendFixture('3d_normal.json')),
    )
  })

  it('keeps the 2D TypeScript mock synchronized with the backend JSON fixture', () => {
    expect(omitNullObjectFields(RESULT_ANALYSIS_MOCK_2D)).toEqual(
      omitNullObjectFields(readBackendFixture('2d_not_applicable.json')),
    )
  })
})

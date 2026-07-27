import { describe, expect, it } from 'vitest'
import { buildSourceVolume, SOURCE_COUNT, SOURCE_SHAPE } from '../../components/volume/volumeGrid'
import { buildVoxelDemoFixture } from '../voxelDemo'

describe('buildVoxelDemoFixture', () => {
  it('generates 7,056 rows on 7 x 21 x 48 unique axes', () => {
    const fixture = buildVoxelDemoFixture()
    expect(fixture.count).toBe(SOURCE_COUNT)
    expect(fixture.x).toHaveLength(SOURCE_COUNT)
    expect(fixture.y).toHaveLength(SOURCE_COUNT)
    expect(fixture.z).toHaveLength(SOURCE_COUNT)
    expect(fixture.values).toHaveLength(SOURCE_COUNT)
    expect(new Set(fixture.x).size).toBe(SOURCE_SHAPE[0])
    expect(new Set(fixture.y).size).toBe(SOURCE_SHAPE[1])
    expect(new Set(fixture.z).size).toBe(SOURCE_SHAPE[2])
  })

  it('passes the real buildSourceVolume contract without mocks', () => {
    const grid = buildSourceVolume(buildVoxelDemoFixture())
    expect(grid.shape).toEqual(SOURCE_SHAPE)
    expect(grid.values).toHaveLength(SOURCE_COUNT)
  })
})

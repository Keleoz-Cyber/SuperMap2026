import { describe, expect, it } from 'vitest'
import type { VoxelCells } from '../../../api/types'
import {
  SOURCE_COUNT,
  SOURCE_SHAPE,
  buildSourceVolume,
  volumeIndex,
} from '../volumeGrid'

function sourceFixture(): VoxelCells {
  const xs = Array.from({ length: 7 }, (_, i) => -160 + i * 20)
  const ys = Array.from({ length: 21 }, (_, i) => 240 + i * 20)
  const zs = Array.from({ length: 48 }, (_, i) => -840 + i * 18)
  const x: number[] = []
  const y: number[] = []
  const z: number[] = []
  const values: number[] = []
  for (const zv of zs) {
    for (const yv of ys) {
      for (const xv of xs) {
        x.push(xv)
        y.push(yv)
        z.push(zv)
        values.push(xv * 0.1 + yv * 0.01 - zv * 0.001)
      }
    }
  }
  return {
    case_id: 'resistivity',
    result_id: 'RHO_KRIG_FINAL_20M_40',
    source: 'iserver_s3m_cache',
    local_cache_label: 'cache',
    local_cache_present: false,
    local_cache_note: 'diagnostic only',
    service_url: 'http://example.test/iserver/services/voxel/rest/realspace',
    tile_files: 26,
    fetched_bytes: 53487,
    count: SOURCE_COUNT,
    value_field: 'RHO',
    unit_note: 'RHO 单位待来源确认',
    x,
    y,
    z,
    values,
    x_range: [xs[0], xs.at(-1)!],
    y_range: [ys[0], ys.at(-1)!],
    z_range: [zs[0], zs.at(-1)!],
    value_range: [Math.min(...values), Math.max(...values)],
    registry_facts: {
      rows_columns_bands: [7, 23, 42],
      cell_exact_value_range: [1.418283, 133.146194],
      note: 'registry metadata',
    },
  }
}

describe('buildSourceVolume', () => {
  it('reindexes a complete 7 x 21 x 48 Cartesian source grid', () => {
    const grid = buildSourceVolume(sourceFixture())
    expect(grid.shape).toEqual(SOURCE_SHAPE)
    expect(grid.values).toHaveLength(SOURCE_COUNT)
    expect(grid.values[volumeIndex(0, 0, 0, 7, 21)]).toBeCloseTo(-12.76)
  })

  it.each([
    ['wrong result id', (d: VoxelCells) => { d.result_id = 'wrong' }],
    ['mismatched arrays', (d: VoxelCells) => { d.values.pop() }],
    ['non-finite value', (d: VoxelCells) => { d.values[4] = Number.NaN }],
    ['duplicate coordinate', (d: VoxelCells) => {
      d.x[1] = d.x[0]
      d.y[1] = d.y[0]
      d.z[1] = d.z[0]
    }],
  ])('rejects %s', (_name, mutate) => {
    const data = sourceFixture()
    mutate(data)
    expect(() => buildSourceVolume(data)).toThrow()
  })
})

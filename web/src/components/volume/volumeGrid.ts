import type { VoxelCells } from '../../api/types'

export const VOLUME_RESULT_ID = 'RHO_KRIG_FINAL_20M_40'
export const SOURCE_SHAPE = [7, 21, 48] as const
export const SOURCE_COUNT = 7056
export const TARGET_SHAPE = [7, 23, 42] as const
export const TARGET_COUNT = 6762

export interface SourceVolume {
  shape: readonly [number, number, number]
  axes: readonly [number[], number[], number[]]
  values: Float32Array
  valueRange: readonly [number, number]
  ranges: readonly [
    readonly [number, number],
    readonly [number, number],
    readonly [number, number],
  ]
}

export function volumeIndex(ix: number, iy: number, iz: number, nx: number, ny: number): number {
  return iz * nx * ny + iy * nx + ix
}

function finiteArray(name: string, values: number[]): void {
  if (values.some((value) => !Number.isFinite(value))) {
    throw new Error(`${name} contains a non-finite value`)
  }
}

function sortedUnique(values: number[]): number[] {
  return [...new Set(values)].sort((a, b) => a - b)
}

export function buildSourceVolume(data: VoxelCells): SourceVolume {
  if (data.result_id !== VOLUME_RESULT_ID) {
    throw new Error(`unexpected result_id: ${data.result_id}`)
  }
  if (data.source !== 'iserver_s3m_cache') {
    throw new Error(`unexpected source: ${data.source}`)
  }
  if (data.count !== SOURCE_COUNT) {
    throw new Error(`unexpected source count: ${data.count}`)
  }
  if (![data.x.length, data.y.length, data.z.length, data.values.length].every((n) => n === data.count)) {
    throw new Error('voxel coordinate/value array lengths do not match count')
  }
  finiteArray('x', data.x)
  finiteArray('y', data.y)
  finiteArray('z', data.z)
  finiteArray('values', data.values)

  const axes = [sortedUnique(data.x), sortedUnique(data.y), sortedUnique(data.z)] as const
  if (axes[0].length !== SOURCE_SHAPE[0] || axes[1].length !== SOURCE_SHAPE[1] || axes[2].length !== SOURCE_SHAPE[2]) {
    throw new Error(`unexpected source shape: ${axes.map((axis) => axis.length).join('x')}`)
  }
  const xIndex = new Map(axes[0].map((value, index) => [value, index]))
  const yIndex = new Map(axes[1].map((value, index) => [value, index]))
  const zIndex = new Map(axes[2].map((value, index) => [value, index]))
  const packed = new Float32Array(SOURCE_COUNT)
  const seen = new Uint8Array(SOURCE_COUNT)

  for (let row = 0; row < data.count; row += 1) {
    const ix = xIndex.get(data.x[row])
    const iy = yIndex.get(data.y[row])
    const iz = zIndex.get(data.z[row])
    if (ix === undefined || iy === undefined || iz === undefined) {
      throw new Error(`coordinate lookup failed at row ${row}`)
    }
    const index = volumeIndex(ix, iy, iz, SOURCE_SHAPE[0], SOURCE_SHAPE[1])
    if (seen[index] === 1) {
      throw new Error(`duplicate Cartesian coordinate at row ${row}`)
    }
    seen[index] = 1
    packed[index] = data.values[row]
  }
  if (seen.some((value) => value !== 1)) {
    throw new Error('source Cartesian grid contains missing coordinates')
  }

  const min = Math.min(...data.values)
  const max = Math.max(...data.values)
  if (Math.abs(min - data.value_range[0]) > 1e-3 || Math.abs(max - data.value_range[1]) > 1e-3) {
    throw new Error(`source value_range mismatch: calculated ${min}..${max}`)
  }

  return {
    shape: SOURCE_SHAPE,
    axes,
    values: packed,
    valueRange: [min, max],
    ranges: [
      [axes[0][0], axes[0].at(-1)!],
      [axes[1][0], axes[1].at(-1)!],
      [axes[2][0], axes[2].at(-1)!],
    ],
  }
}

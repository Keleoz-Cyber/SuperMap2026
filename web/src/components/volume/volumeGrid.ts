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
  valueRange: [number, number]
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

export interface ResampledVolume extends SourceVolume {
  shape: typeof TARGET_SHAPE
}

export interface PackedVolume {
  shape: typeof TARGET_SHAPE
  bytes: Uint8Array
  floatValues: Float32Array
  axes: readonly [number[], number[], number[]]
  ranges: SourceVolume['ranges']
  valueRange: [number, number]
}

function linspace(min: number, max: number, count: number): number[] {
  if (count < 2) throw new Error('linspace count must be at least 2')
  return Array.from({ length: count }, (_, index) => min + (max - min) * index / (count - 1))
}

function bracket(axis: number[], value: number): [number, number, number] {
  if (value <= axis[0]) return [0, 0, 0]
  if (value >= axis.at(-1)!) {
    const last = axis.length - 1
    return [last, last, 0]
  }
  let low = 0
  let high = axis.length - 1
  while (high - low > 1) {
    const mid = Math.floor((low + high) / 2)
    if (axis[mid] <= value) low = mid
    else high = mid
  }
  const span = axis[high] - axis[low]
  if (!(span > 0)) throw new Error('source axis is not strictly increasing')
  return [low, high, (value - axis[low]) / span]
}

function mix(a: number, b: number, t: number): number {
  return a + (b - a) * t
}

function sampleTrilinear(source: SourceVolume, x: number, y: number, z: number): number {
  const [x0, x1, tx] = bracket(source.axes[0], x)
  const [y0, y1, ty] = bracket(source.axes[1], y)
  const [z0, z1, tz] = bracket(source.axes[2], z)
  const [nx, ny] = source.shape
  const at = (ix: number, iy: number, iz: number) =>
    source.values[volumeIndex(ix, iy, iz, nx, ny)]
  const c00 = mix(at(x0, y0, z0), at(x1, y0, z0), tx)
  const c10 = mix(at(x0, y1, z0), at(x1, y1, z0), tx)
  const c01 = mix(at(x0, y0, z1), at(x1, y0, z1), tx)
  const c11 = mix(at(x0, y1, z1), at(x1, y1, z1), tx)
  return mix(mix(c00, c10, ty), mix(c01, c11, ty), tz)
}

export function resampleVolume(source: SourceVolume): ResampledVolume {
  const axes = [
    linspace(source.ranges[0][0], source.ranges[0][1], TARGET_SHAPE[0]),
    linspace(source.ranges[1][0], source.ranges[1][1], TARGET_SHAPE[1]),
    linspace(source.ranges[2][0], source.ranges[2][1], TARGET_SHAPE[2]),
  ] as const
  const values = new Float32Array(TARGET_COUNT)
  let output = 0
  for (const z of axes[2]) {
    for (const y of axes[1]) {
      for (const x of axes[0]) {
        const value = sampleTrilinear(source, x, y, z)
        if (!Number.isFinite(value)) throw new Error(`resampling produced a non-finite value at ${output}`)
        values[output] = value
        output += 1
      }
    }
  }
  const tolerance = 1e-4
  if ([...values].some((value) =>
    value < source.valueRange[0] - tolerance || value > source.valueRange[1] + tolerance)) {
    throw new Error('resampled value escaped the source value envelope')
  }
  return {
    shape: TARGET_SHAPE,
    axes,
    values,
    valueRange: source.valueRange,
    ranges: source.ranges,
  }
}

export function packVolumeTexture(volume: ResampledVolume): PackedVolume {
  const [min, max] = volume.valueRange
  if (!Number.isFinite(min) || !Number.isFinite(max) || !(max > min)) {
    throw new Error(`volume value range must be finite and non-degenerate: ${min}..${max}`)
  }
  const bytes = new Uint8Array(volume.values.length)
  for (let index = 0; index < volume.values.length; index += 1) {
    const normalized = Math.min(1, Math.max(0, (volume.values[index] - min) / (max - min)))
    bytes[index] = Math.round(normalized * 255)
  }
  return {
    shape: TARGET_SHAPE,
    bytes,
    floatValues: volume.values,
    axes: volume.axes,
    ranges: volume.ranges,
    valueRange: volume.valueRange,
  }
}

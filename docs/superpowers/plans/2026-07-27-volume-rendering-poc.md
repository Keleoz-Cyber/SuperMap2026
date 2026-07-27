# Continuous Volume Rendering Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated `/volume-demo` page that renders the registered resistivity S3M cache samples as a continuous semi-transparent volume and proves the result in a real Chromium browser.

**Architecture:** Reuse the existing fail-closed `/api/cases/resistivity/voxel-cells` endpoint without backend changes. Validate and reindex its `7 × 21 × 48` Cartesian samples, resample only for visualization to the registered `7 × 23 × 42` shape, upload a normalized 8-bit `Data3DTexture`, and render it with a bounded WebGL2 ray-marching shader. Keep the page outside the home navigation and persist nothing.

**Tech Stack:** Vue 3, TypeScript, Three.js `0.185.1`, WebGL2/GLSL ES 3.00, Vitest, Vue Test Utils, Playwright Chromium.

---

## File map

| File | Responsibility |
|---|---|
| `web/package.json` | Exact-pinned Three.js runtime and type dependencies |
| `web/package-lock.json` | Reproducible dependency lock |
| `web/src/router/index.ts` | Direct-only `/volume-demo` route |
| `web/src/views/VolumeDemoView.vue` | API loading, fail-closed status, two rendering controls and source disclosure |
| `web/src/components/volume/volumeGrid.ts` | Source contract, Cartesian indexing, physical-axis trilinear resampling, normalization and 8-bit packing |
| `web/src/components/volume/volumeShaders.ts` | Bounded WebGL2 ray-marching vertex and fragment shaders |
| `web/src/components/volume/volumeRuntime.ts` | Three.js renderer, texture, camera, controls, animation and deterministic disposal |
| `web/src/components/volume/VolumeRenderer.vue` | Vue lifecycle wrapper around `volumeRuntime.ts` |
| `web/src/components/volume/__tests__/volumeGrid.spec.ts` | Grid-contract and numerical resampling tests |
| `web/src/components/volume/__tests__/VolumeRenderer.spec.ts` | WebGL support/error and disposal lifecycle tests |
| `web/src/components/volume/__tests__/VolumeDemoView.spec.ts` | Page loading, disclosure, control and fail-closed tests |
| `web/src/mocks/voxelDemo.ts` | Public deterministic `7 × 21 × 48` browser fixture; contains no private source bytes |
| `web/src/mocks/platformDemo.ts` | Mock endpoint registration |
| `web/e2e/volume-demo.spec.ts` | Real Chromium WebGL2 pixel-change proof |
| `docs/evidence/volume-rendering-poc/verification.md` | Machine, browser, counts, value ranges, frame observation and evidence record |
| `docs/evidence/volume-rendering-poc/volume-demo.png` | Real local-browser screenshot |
| `docs/status/current-status.md` | Explicit POC result and non-claim boundary |

## Fixed public contracts

Use these constants in `volumeGrid.ts`; do not duplicate them in components:

```ts
export const VOLUME_RESULT_ID = 'RHO_KRIG_FINAL_20M_40'
export const SOURCE_SHAPE = [7, 21, 48] as const
export const SOURCE_COUNT = 7056
export const TARGET_SHAPE = [7, 23, 42] as const
export const TARGET_COUNT = 6762
```

The source axes are ordered `(x, y, z)`. The packed array index is:

```ts
export function volumeIndex(ix: number, iy: number, iz: number, nx: number, ny: number): number {
  return iz * nx * ny + iy * nx + ix
}
```

No task may modify the backend endpoint, S3MB parser, cache manifest, UDBX, iServer service or formal-result registry.

### Task 1: Pin Three.js and register the direct-only route

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Modify: `web/src/router/index.ts`
- Create: `web/src/router/__tests__/volumeRoute.spec.ts`
- Create: `web/src/views/VolumeDemoView.vue`

- [ ] **Step 1: Write the route test**

Create `web/src/router/__tests__/volumeRoute.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import router from '../index'

describe('volume demo route', () => {
  it('resolves by direct URL but is not a home navigation entry', () => {
    const resolved = router.resolve('/volume-demo')
    expect(resolved.name).toBe('volume-demo')
    expect(resolved.matched).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
npm --prefix web run test:unit -- src/router/__tests__/volumeRoute.spec.ts
```

Expected: FAIL because `/volume-demo` is unmatched.

- [ ] **Step 3: Install exact dependencies**

Run:

```powershell
npm --prefix web install --save-exact three@0.185.1
npm --prefix web install --save-dev --save-exact @types/three@0.185.1
```

Expected: `web/package.json` contains exact versions without `^` or `~`, and `web/package-lock.json` changes.

- [ ] **Step 4: Add a minimal view and lazy route**

Create `web/src/views/VolumeDemoView.vue`:

```vue
<template>
  <main class="volume-demo-page" data-test="volume-demo-page">
    <h1>连续体渲染验证</h1>
    <p>正在准备体元缓存数据。</p>
  </main>
</template>

<style scoped>
.volume-demo-page {
  min-height: 100%;
  padding: 20px;
}
</style>
```

Add this route immediately after `rho-case` in `web/src/router/index.ts`:

```ts
{
  path: '/volume-demo',
  name: 'volume-demo',
  component: () => import('../views/VolumeDemoView.vue'),
},
```

Do not add a link in `HomeView.vue`, `App.vue`, case cards or `PageNavigation`.

- [ ] **Step 5: Run focused and build checks**

Run:

```powershell
npm --prefix web run test:unit -- src/router/__tests__/volumeRoute.spec.ts
npm --prefix web run type-check
npm --prefix web run build
```

Expected: route test PASS; type-check and build exit 0.

- [ ] **Step 6: Commit**

```powershell
git add web/package.json web/package-lock.json web/src/router/index.ts web/src/router/__tests__/volumeRoute.spec.ts web/src/views/VolumeDemoView.vue
git commit -m "feat: add isolated volume rendering demo route"
```

### Task 2: Validate and index the S3M sample grid

**Files:**
- Create: `web/src/components/volume/volumeGrid.ts`
- Create: `web/src/components/volume/__tests__/volumeGrid.spec.ts`

- [ ] **Step 1: Write source-contract tests**

Create the test fixture and initial tests in `web/src/components/volume/__tests__/volumeGrid.spec.ts`:

```ts
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
npm --prefix web run test:unit -- src/components/volume/__tests__/volumeGrid.spec.ts
```

Expected: FAIL because `volumeGrid.ts` does not exist.

- [ ] **Step 3: Implement strict source indexing**

Create `web/src/components/volume/volumeGrid.ts` with these exported types and functions:

```ts
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
```

- [ ] **Step 4: Run the tests**

Run:

```powershell
npm --prefix web run test:unit -- src/components/volume/__tests__/volumeGrid.spec.ts
```

Expected: all focused tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add web/src/components/volume/volumeGrid.ts web/src/components/volume/__tests__/volumeGrid.spec.ts
git commit -m "feat: validate and index voxel cache samples"
```

### Task 3: Resample by physical axes and pack the 3D texture

**Files:**
- Modify: `web/src/components/volume/volumeGrid.ts`
- Modify: `web/src/components/volume/__tests__/volumeGrid.spec.ts`

- [ ] **Step 1: Add constant-field and linear-field tests**

Append tests that create `SourceVolume` values from physical coordinates and assert:

```ts
import {
  TARGET_COUNT,
  TARGET_SHAPE,
  packVolumeTexture,
  resampleVolume,
} from '../volumeGrid'

it('preserves a constant field through 7 x 23 x 42 resampling', () => {
  const source = buildSourceVolume(sourceFixture())
  source.values.fill(42)
  source.valueRange = [42, 42]
  const target = resampleVolume(source)
  expect(target.shape).toEqual(TARGET_SHAPE)
  expect(target.values).toHaveLength(TARGET_COUNT)
  expect([...target.values].every((value) => value === 42)).toBe(true)
})

it('preserves a physical linear gradient within float tolerance', () => {
  const source = buildSourceVolume(sourceFixture())
  const target = resampleVolume(source)
  const nx = TARGET_SHAPE[0]
  const ny = TARGET_SHAPE[1]
  const center = target.values[volumeIndex(3, 11, 21, nx, ny)]
  const x = target.axes[0][3]
  const y = target.axes[1][11]
  const z = target.axes[2][21]
  expect(center).toBeCloseTo(x * 0.1 + y * 0.01 - z * 0.001, 4)
})

it('packs source extrema to 0 and 255', () => {
  const target = resampleVolume(buildSourceVolume(sourceFixture()))
  const packed = packVolumeTexture(target)
  expect(packed.bytes).toHaveLength(TARGET_COUNT)
  expect(Math.min(...packed.bytes)).toBe(0)
  expect(Math.max(...packed.bytes)).toBe(255)
})
```

Change `SourceVolume.valueRange` from readonly tuple property to mutable tuple so the constant-field test is type-correct:

```ts
valueRange: [number, number]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
npm --prefix web run test:unit -- src/components/volume/__tests__/volumeGrid.spec.ts
```

Expected: FAIL because `resampleVolume` and `packVolumeTexture` are missing.

- [ ] **Step 3: Implement non-uniform-axis trilinear sampling**

Add these interfaces and helpers to `volumeGrid.ts`:

```ts
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
```

Add the public functions:

```ts
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
```

For the constant-field test only, call `resampleVolume` and skip `packVolumeTexture`; degenerate ranges must remain a packing error.

- [ ] **Step 4: Run focused tests and type-check**

```powershell
npm --prefix web run test:unit -- src/components/volume/__tests__/volumeGrid.spec.ts
npm --prefix web run type-check
```

Expected: focused tests PASS; type-check exits 0.

- [ ] **Step 5: Commit**

```powershell
git add web/src/components/volume/volumeGrid.ts web/src/components/volume/__tests__/volumeGrid.spec.ts
git commit -m "feat: resample voxel samples for volume texture"
```

### Task 4: Implement bounded WebGL2 ray marching and deterministic disposal

**Files:**
- Create: `web/src/components/volume/volumeShaders.ts`
- Create: `web/src/components/volume/volumeRuntime.ts`
- Create: `web/src/components/volume/VolumeRenderer.vue`
- Create: `web/src/components/volume/__tests__/VolumeRenderer.spec.ts`

- [ ] **Step 1: Write lifecycle tests with a mocked runtime**

Create `VolumeRenderer.spec.ts`:

```ts
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import VolumeRenderer from '../VolumeRenderer.vue'
import type { PackedVolume } from '../volumeGrid'

const runtimeMocks = vi.hoisted(() => ({
  dispose: vi.fn(),
  setThreshold: vi.fn(),
  setOpacity: vi.fn(),
  createVolumeRuntime: vi.fn(),
}))

vi.mock('../volumeRuntime', () => ({ createVolumeRuntime: runtimeMocks.createVolumeRuntime }))

const grid: PackedVolume = {
  shape: [7, 23, 42],
  bytes: new Uint8Array(6762),
  floatValues: new Float32Array(6762),
  axes: [
    Array.from({ length: 7 }, (_, i) => i),
    Array.from({ length: 23 }, (_, i) => i),
    Array.from({ length: 42 }, (_, i) => i),
  ],
  ranges: [[0, 6], [0, 22], [0, 41]],
  valueRange: [1, 2],
}

describe('VolumeRenderer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    runtimeMocks.createVolumeRuntime.mockReturnValue({
      dispose: runtimeMocks.dispose,
      setThreshold: runtimeMocks.setThreshold,
      setOpacity: runtimeMocks.setOpacity,
    })
  })

  it('creates the runtime and disposes it on unmount', () => {
    const wrapper = mount(VolumeRenderer, { props: { grid, threshold: 0.25, opacity: 0.6 } })
    expect(runtimeMocks.createVolumeRuntime).toHaveBeenCalledOnce()
    wrapper.unmount()
    expect(runtimeMocks.dispose).toHaveBeenCalledOnce()
  })

  it('forwards threshold and opacity changes', async () => {
    const wrapper = mount(VolumeRenderer, { props: { grid, threshold: 0.25, opacity: 0.6 } })
    await wrapper.setProps({ threshold: 0.5, opacity: 0.8 })
    expect(runtimeMocks.setThreshold).toHaveBeenLastCalledWith(0.5)
    expect(runtimeMocks.setOpacity).toHaveBeenLastCalledWith(0.8)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

```powershell
npm --prefix web run test:unit -- src/components/volume/__tests__/VolumeRenderer.spec.ts
```

Expected: FAIL because the component and runtime do not exist.

- [ ] **Step 3: Add complete shader contracts**

Create `volumeShaders.ts` with:

```ts
export const volumeVertexShader = /* glsl */ `
  out vec3 vPosition;
  void main() {
    vPosition = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`

export const volumeFragmentShader = /* glsl */ `
  precision highp float;
  precision highp sampler3D;

  uniform sampler3D uVolume;
  uniform float uThreshold;
  uniform float uOpacity;
  uniform float uStepCount;
  in vec3 vPosition;
  out vec4 outColor;

  vec2 intersectBox(vec3 origin, vec3 direction) {
    vec3 inverseDirection = 1.0 / direction;
    vec3 t0 = (-0.5 - origin) * inverseDirection;
    vec3 t1 = ( 0.5 - origin) * inverseDirection;
    vec3 tMin = min(t0, t1);
    vec3 tMax = max(t0, t1);
    return vec2(max(max(tMin.x, tMin.y), tMin.z),
                min(min(tMax.x, tMax.y), tMax.z));
  }

  vec3 transferColor(float value) {
    vec3 low = vec3(0.08, 0.22, 0.55);
    vec3 middle = vec3(0.10, 0.75, 0.58);
    vec3 high = vec3(0.96, 0.32, 0.08);
    return value < 0.5
      ? mix(low, middle, value * 2.0)
      : mix(middle, high, (value - 0.5) * 2.0);
  }

  void main() {
    vec3 rayOrigin = (inverse(modelMatrix) * vec4(cameraPosition, 1.0)).xyz;
    vec3 rayDirection = normalize(vPosition - rayOrigin);
    vec2 bounds = intersectBox(rayOrigin, rayDirection);
    if (bounds.x > bounds.y) discard;

    float start = max(bounds.x, 0.0);
    float distanceInVolume = max(bounds.y - start, 0.0);
    float stepLength = distanceInVolume / max(uStepCount, 1.0);
    vec3 position = rayOrigin + rayDirection * start;
    vec3 stepVector = rayDirection * stepLength;
    vec4 accumulated = vec4(0.0);

    for (int step = 0; step < 384; step += 1) {
      if (float(step) >= uStepCount || accumulated.a >= 0.985) break;
      vec3 texturePosition = position + vec3(0.5);
      float value = texture(uVolume, texturePosition).r;
      if (value >= uThreshold) {
        float density = smoothstep(uThreshold, 1.0, value);
        float alpha = density * uOpacity * 0.055;
        vec3 color = transferColor(value);
        accumulated.rgb += (1.0 - accumulated.a) * alpha * color;
        accumulated.a += (1.0 - accumulated.a) * alpha;
      }
      position += stepVector;
    }
    if (accumulated.a <= 0.001) discard;
    outColor = accumulated;
  }
`
```

The fixed `384` loop bound is mandatory. `uStepCount` must be clamped to `[64, 256]` in TypeScript.

- [ ] **Step 4: Implement the Three.js runtime**

Create `volumeRuntime.ts` with the public interface:

```ts
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import type { PackedVolume } from './volumeGrid'
import { volumeFragmentShader, volumeVertexShader } from './volumeShaders'

export interface VolumeRuntime {
  setThreshold(value: number): void
  setOpacity(value: number): void
  dispose(): void
}

export function createVolumeRuntime(
  container: HTMLElement,
  grid: PackedVolume,
  threshold: number,
  opacity: number,
): VolumeRuntime {
  const canvas = document.createElement('canvas')
  canvas.dataset.test = 'volume-canvas'
  const context = canvas.getContext('webgl2', {
    alpha: true,
    antialias: true,
    preserveDrawingBuffer: true,
  })
  if (!context) throw new Error('当前浏览器或显卡不支持 WebGL2')
  container.appendChild(canvas)

  const renderer = new THREE.WebGLRenderer({ canvas, context, alpha: true, antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setClearColor(0x05070a, 1)

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100)
  camera.position.set(1.65, -2.2, 1.45)

  const controls = new OrbitControls(camera, canvas)
  controls.enableDamping = true
  controls.target.set(0, 0, 0)

  const [nx, ny, nz] = grid.shape
  const texture = new THREE.Data3DTexture(grid.bytes, nx, ny, nz)
  texture.format = THREE.RedFormat
  texture.type = THREE.UnsignedByteType
  texture.minFilter = THREE.LinearFilter
  texture.magFilter = THREE.LinearFilter
  texture.unpackAlignment = 1
  texture.needsUpdate = true

  const uniforms = {
    uVolume: { value: texture },
    uThreshold: { value: THREE.MathUtils.clamp(threshold, 0, 0.99) },
    uOpacity: { value: THREE.MathUtils.clamp(opacity, 0.01, 1) },
    uStepCount: { value: THREE.MathUtils.clamp(Math.max(nx, ny, nz) * 3, 64, 256) },
  }
  const material = new THREE.ShaderMaterial({
    glslVersion: THREE.GLSL3,
    vertexShader: volumeVertexShader,
    fragmentShader: volumeFragmentShader,
    uniforms,
    side: THREE.BackSide,
    transparent: true,
    depthWrite: false,
  })

  const spans = grid.ranges.map(([min, max]) => max - min)
  if (spans.some((span) => !Number.isFinite(span) || !(span > 0))) {
    throw new Error(`invalid physical volume spans: ${spans.join(',')}`)
  }
  const scale = Math.max(...spans)
  const geometry = new THREE.BoxGeometry(1, 1, 1)
  const mesh = new THREE.Mesh(geometry, material)
  mesh.scale.set(spans[0] / scale, spans[1] / scale, spans[2] / scale)
  scene.add(mesh)

  let frame = 0
  let disposed = false
  const resize = () => {
    const width = Math.max(container.clientWidth, 1)
    const height = Math.max(container.clientHeight, 1)
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
  }
  const animate = () => {
    if (disposed) return
    controls.update()
    renderer.render(scene, camera)
    frame = requestAnimationFrame(animate)
  }
  const observer = new ResizeObserver(resize)
  observer.observe(container)
  resize()
  animate()

  return {
    setThreshold(value) {
      uniforms.uThreshold.value = THREE.MathUtils.clamp(value, 0, 0.99)
    },
    setOpacity(value) {
      uniforms.uOpacity.value = THREE.MathUtils.clamp(value, 0.01, 1)
    },
    dispose() {
      if (disposed) return
      disposed = true
      cancelAnimationFrame(frame)
      observer.disconnect()
      controls.dispose()
      geometry.dispose()
      material.dispose()
      texture.dispose()
      renderer.dispose()
      canvas.remove()
    },
  }
}
```

Wrap all allocations after renderer creation in `try/catch`; on construction failure dispose every object already created, remove the canvas, then rethrow the original error. Do not let cleanup errors replace the construction error.

- [ ] **Step 5: Implement the Vue lifecycle wrapper**

Create `VolumeRenderer.vue`:

```vue
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { PackedVolume } from './volumeGrid'
import { createVolumeRuntime, type VolumeRuntime } from './volumeRuntime'

const props = defineProps<{
  grid: PackedVolume
  threshold: number
  opacity: number
}>()
const emit = defineEmits<{ error: [message: string] }>()
const container = ref<HTMLElement | null>(null)
let runtime: VolumeRuntime | null = null

onMounted(() => {
  if (!container.value) return
  try {
    runtime = createVolumeRuntime(container.value, props.grid, props.threshold, props.opacity)
  } catch (error) {
    emit('error', error instanceof Error ? error.message : String(error))
  }
})

watch(() => props.threshold, (value) => runtime?.setThreshold(value))
watch(() => props.opacity, (value) => runtime?.setOpacity(value))

onBeforeUnmount(() => {
  runtime?.dispose()
  runtime = null
})
</script>

<template>
  <div ref="container" class="volume-renderer" data-test="volume-renderer"></div>
</template>

<style scoped>
.volume-renderer {
  min-height: 560px;
  width: 100%;
}
</style>
```

- [ ] **Step 6: Run tests and build**

```powershell
npm --prefix web run test:unit -- src/components/volume/__tests__/VolumeRenderer.spec.ts
npm --prefix web run type-check
npm --prefix web run build
```

Expected: tests PASS; type-check and build exit 0 with no new warning.

- [ ] **Step 7: Commit**

```powershell
git add web/src/components/volume
git commit -m "feat: render continuous volume with WebGL2 ray marching"
```

### Task 5: Integrate the fail-closed demo page

**Files:**
- Modify: `web/src/views/VolumeDemoView.vue`
- Create: `web/src/components/volume/__tests__/VolumeDemoView.spec.ts`

- [ ] **Step 1: Write page-state tests**

Mock `fetchVoxelCells`, `buildSourceVolume`, `resampleVolume`, and
`packVolumeTexture` only through their public module boundaries. Start the test
file with:

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { VoxelCells } from '../../../api/types'
import * as client from '../../../api/client'
import VolumeRenderer from '../VolumeRenderer.vue'
import type { PackedVolume, SourceVolume } from '../volumeGrid'
import * as volumeGrid from '../volumeGrid'
import VolumeDemoView from '../../../views/VolumeDemoView.vue'

vi.mock('../../../api/client', () => ({ fetchVoxelCells: vi.fn() }))
vi.mock('../volumeGrid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../volumeGrid')>()
  return {
    ...actual,
    buildSourceVolume: vi.fn(),
    resampleVolume: vi.fn(),
    packVolumeTexture: vi.fn(),
  }
})

const voxelFixture = {
  result_id: 'RHO_KRIG_FINAL_20M_40',
  count: 7056,
  value_range: [2.2913, 127.2808],
} as VoxelCells

const sourceFixture = {
  shape: [7, 21, 48],
  axes: [[], [], []],
  values: new Float32Array(7056),
  valueRange: [2.2913, 127.2808],
  ranges: [[-160, -57.143], [239.13, 660], [-840, -34.286]],
} as SourceVolume

const packedFixture = {
  shape: [7, 23, 42],
  bytes: new Uint8Array(6762),
  floatValues: new Float32Array(6762),
  axes: [[], [], []],
  ranges: sourceFixture.ranges,
  valueRange: sourceFixture.valueRange,
} as PackedVolume

function mountView() {
  return mount(VolumeDemoView, {
    global: {
      stubs: {
        VolumeRenderer: {
          name: 'VolumeRenderer',
          props: ['grid', 'threshold', 'opacity'],
          template: '<div data-test="volume-renderer-stub"></div>',
        },
      },
    },
  })
}

describe('VolumeDemoView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(volumeGrid.buildSourceVolume).mockReturnValue(sourceFixture)
    vi.mocked(volumeGrid.resampleVolume).mockReturnValue({
      ...sourceFixture,
      shape: [7, 23, 42] as const,
      values: packedFixture.floatValues,
    })
    vi.mocked(volumeGrid.packVolumeTexture).mockReturnValue(packedFixture)
  })

it('discloses source and target shapes after successful loading', async () => {
  vi.mocked(client.fetchVoxelCells).mockResolvedValue(voxelFixture)
  const wrapper = mountView()
  await flushPromises()
  expect(wrapper.get('[data-test="source-shape"]').text()).toContain('7 × 21 × 48')
  expect(wrapper.get('[data-test="target-shape"]').text()).toContain('7 × 23 × 42')
  expect(wrapper.get('[data-test="visualization-disclaimer"]').text())
    .toContain('可视化重采样')
  expect(wrapper.findComponent(VolumeRenderer).exists()).toBe(true)
})

it('shows an explicit error and no renderer when the contract fails', async () => {
  vi.mocked(client.fetchVoxelCells).mockRejectedValue(new Error('S3M 缓存契约校验失败'))
  const wrapper = mountView()
  await flushPromises()
  expect(wrapper.get('[data-test="volume-error"]').text()).toContain('S3M 缓存契约校验失败')
  expect(wrapper.findComponent(VolumeRenderer).exists()).toBe(false)
})

it('forwards the two presentation controls to the renderer', async () => {
  vi.mocked(client.fetchVoxelCells).mockResolvedValue(voxelFixture)
  const wrapper = mountView()
  await flushPromises()
  await wrapper.get('[data-test="volume-threshold"]').setValue('0.42')
  await wrapper.get('[data-test="volume-opacity"]').setValue('0.80')
  const renderer = wrapper.findComponent({ name: 'VolumeRenderer' })
  expect(renderer.props('threshold')).toBe(0.42)
  expect(renderer.props('opacity')).toBe(0.8)
})
})
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
npm --prefix web run test:unit -- src/components/volume/__tests__/VolumeDemoView.spec.ts
```

Expected: FAIL because the minimal page has no loading states or renderer.

- [ ] **Step 3: Implement the final page**

Use this state model in `VolumeDemoView.vue`:

```ts
type LoadState = 'loading' | 'ready' | 'failed'
const state = ref<LoadState>('loading')
const error = ref('')
const packed = shallowRef<PackedVolume | null>(null)
const sourceData = shallowRef<VoxelCells | null>(null)
const threshold = ref(0.18)
const opacity = ref(0.55)

onMounted(async () => {
  try {
    const data = await fetchVoxelCells()
    const source = buildSourceVolume(data)
    const target = resampleVolume(source)
    sourceData.value = data
    packed.value = packVolumeTexture(target)
    state.value = 'ready'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    state.value = 'failed'
  }
})

function onRendererError(message: string) {
  error.value = message
  state.value = 'failed'
  packed.value = null
}
```

The template must render:

```vue
<main class="volume-demo-page" data-test="volume-demo-page">
  <header>
    <h1>连续体渲染验证</h1>
    <p data-test="visualization-disclaimer">
      数据来自 RHO_KRIG_FINAL_20M_40 的 S3M 缓存采样；纹理经过仅用于显示的三线性重采样，
      不是新的正式模型，也不是 VOLUME 精确逐单元导出。
    </p>
  </header>

  <el-skeleton v-if="state === 'loading'" :rows="8" animated data-test="volume-loading" />
  <el-alert
    v-else-if="state === 'failed'"
    type="error"
    :closable="false"
    :title="error"
    data-test="volume-error"
  />
  <section v-else-if="packed && sourceData" class="volume-layout">
    <div class="volume-canvas-panel">
      <VolumeRenderer
        :grid="packed"
        :threshold="threshold"
        :opacity="opacity"
        @error="onRendererError"
      />
    </div>
    <aside class="volume-controls">
      <p><strong>成果：</strong>{{ sourceData.result_id }}</p>
      <p data-test="source-shape"><strong>源采样：</strong>7 × 21 × 48 / 7,056</p>
      <p data-test="target-shape"><strong>显示纹理：</strong>7 × 23 × 42 / 6,762</p>
      <p><strong>采样值域：</strong>{{ sourceData.value_range[0] }}–{{ sourceData.value_range[1] }}</p>
      <p><strong>坐标：</strong>局部坐标，不可跨案例叠加</p>
      <label for="volume-threshold">强度阈值 {{ threshold.toFixed(2) }}</label>
      <input id="volume-threshold" v-model.number="threshold" type="range" min="0" max="0.95" step="0.01" data-test="volume-threshold" />
      <label for="volume-opacity">总体透明度 {{ opacity.toFixed(2) }}</label>
      <input id="volume-opacity" v-model.number="opacity" type="range" min="0.05" max="1" step="0.05" data-test="volume-opacity" />
    </aside>
  </section>
</main>
```

Use existing CSS variables from `web/src/styles/index.css`; do not introduce a second design system. At widths below 900 px, stack the controls below the canvas.

- [ ] **Step 4: Run focused and all frontend checks**

```powershell
npm --prefix web run test:unit -- src/components/volume/__tests__/VolumeDemoView.spec.ts
npm --prefix web run test:unit
npm --prefix web run type-check
npm --prefix web run build
```

Expected: focused and full Vitest suites PASS; type-check/build exit 0.

- [ ] **Step 5: Commit**

```powershell
git add web/src/views/VolumeDemoView.vue web/src/components/volume/__tests__/VolumeDemoView.spec.ts
git commit -m "feat: add fail-closed volume demo page"
```

### Task 6: Prove rendering in Chromium with a public generated fixture

**Files:**
- Create: `web/src/mocks/voxelDemo.ts`
- Modify: `web/src/mocks/platformDemo.ts`
- Create: `web/e2e/volume-demo.spec.ts`

- [ ] **Step 1: Add a deterministic generated fixture**

Create `voxelDemo.ts`:

```ts
import type { VoxelCells } from '../api/types'

export function buildVoxelDemoFixture(): VoxelCells {
  const xs = Array.from({ length: 7 }, (_, i) => -160 + i * (720 / 42))
  const fullY = Array.from({ length: 23 }, (_, i) => 239.13 + i * (420.87 / 22))
  const ys = fullY.filter((_, i) => i !== 1 && i !== 15)
  const zs = Array.from({ length: 48 }, (_, i) => -840 + i * (805.714 / 47))
  const x: number[] = []
  const y: number[] = []
  const z: number[] = []
  const values: number[] = []
  for (const zv of zs) {
    for (const yv of ys) {
      for (const xv of xs) {
        const dx = (xv + 105) / 38
        const dy = (yv - 455) / 125
        const dz = (zv + 420) / 270
        const first = 88 * Math.exp(-(dx * dx + dy * dy + dz * dz))
        const second = 42 * Math.exp(-((dx + 0.8) ** 2 + (dy - 0.6) ** 2 + (dz + 0.4) ** 2))
        x.push(Number(xv.toFixed(3)))
        y.push(Number(yv.toFixed(3)))
        z.push(Number(zv.toFixed(3)))
        values.push(Number((3 + first + second).toFixed(4)))
      }
    }
  }
  return {
    case_id: 'resistivity',
    result_id: 'RHO_KRIG_FINAL_20M_40',
    source: 'iserver_s3m_cache',
    local_cache_label: 'public_generated_fixture',
    local_cache_present: false,
    local_cache_note: 'E2E public generated fixture',
    service_url: 'http://mock.test/iserver/services/volume/rest/realspace',
    tile_files: 26,
    fetched_bytes: 53487,
    count: values.length,
    value_field: 'RHO',
    unit_note: 'RHO 单位待来源确认',
    x,
    y,
    z,
    values,
    x_range: [Math.min(...x), Math.max(...x)],
    y_range: [Math.min(...y), Math.max(...y)],
    z_range: [Math.min(...z), Math.max(...z)],
    value_range: [Math.min(...values), Math.max(...values)],
    registry_facts: {
      rows_columns_bands: [7, 23, 42],
      cell_exact_value_range: [1.418283, 133.146194],
      note: 'public registry facts only',
    },
  }
}
```

Assert in a small Vitest test that this fixture has `7,056` rows and `7/21/48` unique axes. This prevents a mock that bypasses the real contract.

- [ ] **Step 2: Register the mock endpoint**

In `platformDemo.ts`, import `buildVoxelDemoFixture` and add this branch before the generic not-found response:

```ts
if (path === '/cases/resistivity/voxel-cells' && method === 'GET') {
  return json(route, buildVoxelDemoFixture())
}
```

- [ ] **Step 3: Write the real Chromium proof**

Create `web/e2e/volume-demo.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { installMockApi } from '../src/mocks/platformDemo'

test.use({ launchOptions: { args: ['--use-angle=swiftshader'] } })

test('renders a continuous volume and reacts to transfer controls', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })
  await installMockApi(page)
  await page.goto('/#/volume-demo')

  await expect(page.getByTestId('source-shape')).toContainText('7 × 21 × 48')
  await expect(page.getByTestId('target-shape')).toContainText('7 × 23 × 42')
  const canvas = page.locator('canvas[data-test="volume-canvas"]')
  await expect(canvas).toBeVisible()

  const before = await canvas.screenshot()
  await page.getByTestId('volume-threshold').evaluate((node) => {
    const input = node as HTMLInputElement
    input.value = '0.62'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await page.getByTestId('volume-opacity').evaluate((node) => {
    const input = node as HTMLInputElement
    input.value = '0.90'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await page.waitForTimeout(250)
  const after = await canvas.screenshot()

  expect(before.length).toBeGreaterThan(1000)
  expect(after.length).toBeGreaterThan(1000)
  expect(Buffer.compare(before, after)).not.toBe(0)
  expect(errors).toEqual([])
})
```

If Chromium cannot create WebGL2 with SwiftShader on CI, fail the job with the explicit page error. Do not skip the test and do not replace it with a mocked renderer.

- [ ] **Step 4: Run browser and frontend verification**

```powershell
npm --prefix web run test:unit
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e -- volume-demo.spec.ts
```

Expected: all commands exit 0; the Playwright test proves a visible canvas and changed pixel output.

- [ ] **Step 5: Commit**

```powershell
git add web/src/mocks/voxelDemo.ts web/src/mocks/platformDemo.ts web/e2e/volume-demo.spec.ts
git commit -m "test: prove volume rendering in Chromium"
```

### Task 7: Run the real-cache acceptance and document only measured evidence

**Files:**
- Create: `docs/evidence/volume-rendering-poc/verification.md`
- Create: `docs/evidence/volume-rendering-poc/volume-demo.png`
- Modify: `docs/status/current-status.md`
- Modify: `docs/plans/2026-07-27-volume-rendering-minimal-design.md`

- [ ] **Step 1: Start the existing real services without changing them**

Use the repository's documented v0.4.1 startup flow and current local iServer service. First run:

```powershell
python -m geomodeling.cli demo-check
```

Expected: platform blockers are zero. The optional iServer/S3M checks must be reachable for this real-cache acceptance; otherwise record the unavailable service and stop this task without claiming real-data rendering.

Start the platform through the existing script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_demo.ps1
```

Expected: FastAPI serves the built frontend and `/api/cases/resistivity/voxel-cells` returns HTTP 200 with `count=7056`.

- [ ] **Step 2: Perform the real browser check**

Open:

```text
http://127.0.0.1:8000/#/volume-demo
```

Verify and record:

- source identity;
- source and target shapes;
- source sample value range;
- browser version;
- GPU renderer from `chrome://gpu`;
- continuous appearance during rotation;
- threshold and opacity visible changes;
- browser console contains no error;
- enter/leave the route ten times and confirm no steadily increasing animation loops or detached canvases.

Do not infer frame rate. Measure it only if browser tooling reports it.

- [ ] **Step 3: Save authentic evidence**

Save a browser screenshot as:

```text
docs/evidence/volume-rendering-poc/volume-demo.png
```

Create `verification.md` containing the exact date, Git SHA, endpoint response counts, browser/GPU facts, observed result, and the statement:

```text
This proves browser-side continuous rendering of the validated S3M cache sample field.
It does not prove a cell-exact VOLUME export, a new interpolation result, geological accuracy,
native SuperMap GPU volume rendering, or cross-case coordinate alignment.
```

- [ ] **Step 4: Update status and design outcome**

In `docs/status/current-status.md`, add a short “Continuous volume rendering POC” entry with only the measured result and its boundary.

At the end of the design document, add an `## 13. 实施结果` section. Populate its
Git SHA from `git rev-parse HEAD`, copy the exact test counts from the command
outputs in Step 5, set the real-cache browser result to either `通过` or
`未完成`, and link `docs/evidence/volume-rendering-poc/verification.md`.
Do not commit the section if any value is blank. An unavailable real service
must be written as `未完成`; it must not be converted into a pass.

- [ ] **Step 5: Run the full regression gate**

```powershell
python -m pytest -q
npm --prefix web run test:unit
npm --prefix web run type-check
npm --prefix web run build
npm --prefix web run test:e2e
npm --prefix web run test:e2e:live
git diff --check
git status --short
```

Expected:

- backend suite passes without reducing the v0.6 baseline;
- frontend suite includes the new volume tests and passes;
- mock and live Playwright suites pass;
- `git diff --check` prints nothing;
- no UDBX, S3M cache, private raw data, credentials, runtime DB or generated `dist` file is tracked.

- [ ] **Step 6: Commit documentation and evidence**

```powershell
git add docs/evidence/volume-rendering-poc docs/status/current-status.md docs/plans/2026-07-27-volume-rendering-minimal-design.md
git commit -m "docs: record continuous volume rendering proof"
```

- [ ] **Step 7: Final review and PR**

Review:

```powershell
git log --oneline origin/main..HEAD
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
git status --short --branch
```

Confirm the diff contains no backend production change and no homepage/navigation entry. Push a feature branch and open a non-draft PR. Keep the PR open, do not merge, do not create a tag or Release, and report:

- branch and commit chain;
- exact test counts;
- Chromium proof result;
- real-cache result;
- screenshot path;
- all non-claim boundaries.

## Plan self-review

- Spec coverage: source identity, `7×21×48 → 7×23×42`, physical-axis interpolation, 8-bit texture packing, WebGL2 ray marching, two controls, direct-only route, explicit failure, cleanup, browser pixels, authentic screenshot and non-claim boundaries each map to a task.
- Scope: no backend, iServer, cache, formal model, database, homepage, task system, slice, isosurface or export change.
- Type consistency: `SourceVolume`, `ResampledVolume`, `PackedVolume`, `VolumeRuntime`, prop names and `(x,y,z)` index order are consistent across tasks.
- Completeness check: implementation steps define the required functions, commands and expected results; runtime evidence is populated from explicit commands and cannot be committed blank.

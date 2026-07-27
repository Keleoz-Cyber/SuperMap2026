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

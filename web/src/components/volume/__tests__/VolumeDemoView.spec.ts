import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
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
      plugins: [ElementPlus],
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

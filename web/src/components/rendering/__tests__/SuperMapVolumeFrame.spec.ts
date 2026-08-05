import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DisplayTransform, RenderAssetRecord } from '../../../api/types'
import { VOLUME_FRAME_PROTOCOL } from '../renderProtocol'
import SuperMapVolumeFrame from '../SuperMapVolumeFrame.vue'

const TRANSFORM: DisplayTransform = {
  contract: 'wgs84_display_anchor_v1',
  origin_x: 0,
  origin_y: 0,
  anchor_longitude: 120,
  anchor_latitude: 30,
  anchor_height: 0,
  metres_per_degree_lon: 96486.3,
  metres_per_degree_lat: 110852.4,
}

const ASSET: RenderAssetRecord = {
  id: `nc-${'a'.repeat(32)}`,
  source_kind: 'candidate_result',
  source_id: 'r1',
  renderer: 'supermap_voxelgrid_netcdf',
  status: 'ready',
  grid_sha256: 'g'.repeat(64),
  netcdf_sha256: 'n'.repeat(64),
  manifest_url: `/api/render-assets/nc-${'a'.repeat(32)}/manifest`,
  netcdf_url: `/api/render-assets/nc-${'a'.repeat(32)}/volume.nc`,
  error: null,
}

const IDENTITY = {
  sourceKind: 'candidate_result' as const,
  sourceId: 'r1',
  gridSha256: 'g'.repeat(64),
  netcdfSha256: 'n'.repeat(64),
}

interface Mounted {
  wrapper: ReturnType<typeof mount>
  iframe: HTMLIFrameElement
  postSpy: ReturnType<typeof vi.spyOn>
  requestId: string
}

function mountFrame(asset: RenderAssetRecord | null = ASSET): Mounted {
  const wrapper = mount(SuperMapVolumeFrame, {
    props: { asset, displayTransform: TRANSFORM },
    attachTo: document.body,
  })
  const iframe = wrapper.find('iframe').element as HTMLIFrameElement
  expect(iframe.contentWindow).toBeTruthy()
  const postSpy = vi.spyOn(iframe.contentWindow as Window, 'postMessage')
  const src = iframe.getAttribute('src') ?? ''
  const requestId = new URLSearchParams(src.slice(src.indexOf('?'))).get('request_id') ?? ''
  return { wrapper, iframe, postSpy, requestId }
}

function emitChild(
  iframe: HTMLIFrameElement,
  requestId: string,
  msg: Record<string, unknown>,
  overrides: { origin?: string; source?: MessageEventSource | null; dataOverride?: unknown } = {},
) {
  const event = new MessageEvent('message', {
    data: overrides.dataOverride ?? { protocol: VOLUME_FRAME_PROTOCOL, requestId, ...msg },
    origin: overrides.origin ?? window.location.origin,
    source: overrides.source === undefined ? iframe.contentWindow : overrides.source,
  })
  window.dispatchEvent(event)
}

function frameReady(iframe: HTMLIFrameElement, requestId: string) {
  emitChild(iframe, requestId, { type: 'FRAME_READY', sdkVersion: '12.1.0', contextType: 2 })
}

afterEach(() => {
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('SuperMapVolumeFrame 握手', () => {
  it('iframe src 含 URL 编码的活动 requestId', () => {
    const { iframe, requestId } = mountFrame()
    expect(requestId).not.toBe('')
    expect(iframe.getAttribute('src')).toBe(
      `/supermap-volume-frame/index.html?request_id=${encodeURIComponent(requestId)}`,
    )
  })

  it('匹配 query ID 的 FRAME_READY 恰好触发一次 INIT（目标 origin 为本源）', () => {
    const { wrapper, iframe, postSpy, requestId } = mountFrame()
    frameReady(iframe, requestId)
    expect(postSpy).toHaveBeenCalledTimes(1)
    const [msg, targetOrigin] = postSpy.mock.calls[0] as unknown as [
      Record<string, unknown>,
      string,
    ]
    expect(targetOrigin).toBe(window.location.origin)
    expect(targetOrigin).not.toBe('*')
    expect(msg).toMatchObject({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'INIT',
      requestId,
      asset: ASSET,
      displayTransform: TRANSFORM,
    })
    expect(wrapper.emitted('ready')).toHaveLength(1)
    expect(wrapper.emitted('ready')?.[0]).toEqual([{ sdkVersion: '12.1.0', contextType: 2 }])
  })

  it('INIT 仅在新的 FRAME_READY 后重发（第二次握手 → 第二次 INIT）', () => {
    const { iframe, postSpy, requestId } = mountFrame()
    frameReady(iframe, requestId)
    frameReady(iframe, requestId)
    expect(postSpy).toHaveBeenCalledTimes(2)
    for (const call of postSpy.mock.calls) {
      expect((call[0] as Record<string, unknown>).type).toBe('INIT')
    }
  })

  it('origin 错误的消息被忽略', () => {
    const { iframe, postSpy, requestId } = mountFrame()
    emitChild(
      iframe,
      requestId,
      { type: 'FRAME_READY', sdkVersion: '12.1.0', contextType: 2 },
      { origin: 'https://evil.example' },
    )
    expect(postSpy).not.toHaveBeenCalled()
  })

  it('source 错误的消息被忽略', () => {
    const { iframe, postSpy, requestId } = mountFrame()
    emitChild(
      iframe,
      requestId,
      { type: 'FRAME_READY', sdkVersion: '12.1.0', contextType: 2 },
      { source: window },
    )
    expect(postSpy).not.toHaveBeenCalled()
  })

  it('protocol 错误的消息被忽略', () => {
    const { iframe, postSpy, requestId } = mountFrame()
    emitChild(iframe, requestId, { type: 'FRAME_READY', sdkVersion: '12.1.0', contextType: 2 }, {
      dataOverride: {
        protocol: 'gmp-supermap-volume/v0',
        type: 'FRAME_READY',
        requestId,
        sdkVersion: '12.1.0',
        contextType: 2,
      },
    })
    expect(postSpy).not.toHaveBeenCalled()
  })

  it('requestId 错误的消息被忽略', () => {
    const { iframe, postSpy, requestId } = mountFrame()
    emitChild(iframe, 'rvf-attacker', { type: 'FRAME_READY', sdkVersion: '12.1.0', contextType: 2 })
    expect(postSpy).not.toHaveBeenCalled()
    // 合法 ID 仍然可用：先坏后好不得污染握手
    frameReady(iframe, requestId)
    expect(postSpy).toHaveBeenCalledTimes(1)
  })

  it('asset=null 时 INIT 发送 asset=null（点云专用初始化）', () => {
    const { iframe, postSpy, requestId } = mountFrame(null)
    frameReady(iframe, requestId)
    expect(postSpy).toHaveBeenCalledTimes(1)
    expect((postSpy.mock.calls[0] as unknown as [Record<string, unknown>])[0].asset).toBeNull()
  })

  it('RENDER_STATE rendered 触发 rendered emit 并携带 identity', () => {
    const { wrapper, iframe, requestId } = mountFrame()
    frameReady(iframe, requestId)
    emitChild(iframe, requestId, { type: 'RENDER_STATE', phase: 'rendered', identity: IDENTITY })
    expect(wrapper.emitted('rendered')).toHaveLength(1)
    expect(wrapper.emitted('rendered')?.[0]).toEqual([IDENTITY])
  })

  it('ERROR 触发 failed emit（code + message）', () => {
    const { wrapper, iframe, requestId } = mountFrame()
    frameReady(iframe, requestId)
    emitChild(iframe, requestId, {
      type: 'ERROR',
      code: 'MANIFEST_IDENTITY_MISMATCH',
      message: 'manifest 身份与资产记录不一致',
    })
    expect(wrapper.emitted('failed')).toHaveLength(1)
    expect(wrapper.emitted('failed')?.[0]).toEqual([
      { code: 'MANIFEST_IDENTITY_MISMATCH', message: 'manifest 身份与资产记录不一致' },
    ])
  })

  it('unmount 移除 message 监听（卸载后消息不再触发任何动作）', () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    const { wrapper, iframe, postSpy, requestId } = mountFrame()
    wrapper.unmount()
    expect(removeSpy).toHaveBeenCalledWith('message', expect.any(Function))
    frameReady(iframe, requestId)
    expect(postSpy).not.toHaveBeenCalled()
  })
})

describe('SuperMapVolumeFrame 命令方法', () => {
  function lastPost(postSpy: ReturnType<typeof vi.spyOn>): Record<string, unknown> {
    const calls = postSpy.mock.calls
    return calls[calls.length - 1][0] as Record<string, unknown>
  }

  it('setMode / resetView 发送对应命令', () => {
    const { wrapper, iframe, postSpy, requestId } = mountFrame()
    frameReady(iframe, requestId)
    ;(wrapper.vm as unknown as { setMode: (m: string) => void }).setMode('slice')
    expect(lastPost(postSpy)).toMatchObject({ type: 'SET_MODE', requestId, mode: 'slice' })
    ;(wrapper.vm as unknown as { resetView: () => void }).resetView()
    expect(lastPost(postSpy)).toMatchObject({ type: 'RESET_VIEW', requestId })
  })

  it('setMode 可携带 Slice/Contour 的 SDK 参数', () => {
    const { wrapper, iframe, postSpy, requestId } = mountFrame()
    frameReady(iframe, requestId)
    ;(wrapper.vm as unknown as {
      setMode: (m: string, options: Record<string, unknown>) => void
    }).setMode('slice', { sliceCoordinate: { x: 0.5, y: 0.5, z: 0.25 } })
    expect(lastPost(postSpy)).toMatchObject({
      type: 'SET_MODE',
      mode: 'slice',
      sliceCoordinate: { x: 0.5, y: 0.5, z: 0.25 },
    })
    ;(wrapper.vm as unknown as {
      setMode: (m: string, options: Record<string, unknown>) => void
    }).setMode('contour', { contourValue: 42 })
    expect(lastPost(postSpy)).toMatchObject({ type: 'SET_MODE', mode: 'contour', contourValue: 42 })
  })

  it('setOpacity clamp 到 0..1', () => {
    const { wrapper, iframe, postSpy, requestId } = mountFrame()
    frameReady(iframe, requestId)
    const vm = wrapper.vm as unknown as { setOpacity: (o: number) => void }
    vm.setOpacity(1.7)
    expect(lastPost(postSpy)).toMatchObject({ type: 'SET_OPACITY', opacity: 1 })
    vm.setOpacity(-0.3)
    expect(lastPost(postSpy)).toMatchObject({ type: 'SET_OPACITY', opacity: 0 })
    vm.setOpacity(0.4)
    expect(lastPost(postSpy)).toMatchObject({ type: 'SET_OPACITY', opacity: 0.4 })
  })

  it('setOpacity 非有限值不发送', () => {
    const { wrapper, iframe, postSpy, requestId } = mountFrame()
    frameReady(iframe, requestId)
    postSpy.mockClear()
    ;(wrapper.vm as unknown as { setOpacity: (o: number) => void }).setOpacity(Number.NaN)
    expect(postSpy).not.toHaveBeenCalled()
  })

  it('setFilter 要求 min <= max 且有限，否则不发送', () => {
    const { wrapper, iframe, postSpy, requestId } = mountFrame()
    frameReady(iframe, requestId)
    const vm = wrapper.vm as unknown as { setFilter: (min: number, max: number) => void }
    postSpy.mockClear()
    vm.setFilter(10, 2)
    expect(postSpy).not.toHaveBeenCalled()
    vm.setFilter(Number.POSITIVE_INFINITY, 20)
    expect(postSpy).not.toHaveBeenCalled()
    vm.setFilter(2, 10)
    expect(postSpy).toHaveBeenCalledTimes(1)
    expect(lastPost(postSpy)).toMatchObject({ type: 'SET_FILTER', min: 2, max: 10 })
  })

  it('setPointLayer 透传点层载荷', () => {
    const { wrapper, iframe, postSpy, requestId } = mountFrame()
    frameReady(iframe, requestId)
    const layer = {
      id: 'grid-samples' as const,
      visible: true,
      role: 'auxiliary' as const,
      coordinates: 'local' as const,
      x: [0, 10],
      y: [0, 10],
      z: [0, -5],
      style: { color: '#22d3ee', pixelSize: 4 },
    }
    ;(wrapper.vm as unknown as { setPointLayer: (l: typeof layer) => void }).setPointLayer(layer)
    expect(lastPost(postSpy)).toMatchObject({ type: 'SET_POINT_LAYER', requestId, layer })
  })
})

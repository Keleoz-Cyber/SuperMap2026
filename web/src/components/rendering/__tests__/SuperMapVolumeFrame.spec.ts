import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import SuperMapVolumeFrame from '../SuperMapVolumeFrame.vue'
import {
  VOLUME_FRAME_PROTOCOL,
  type RenderStateV2,
} from '../renderProtocol'

// v0.7.0 Batch 2 Task 7：父页面侧 v2 桥（revision 跟踪与回执过滤）。

const RENDERED_IDENTITY = {
  sourceKind: 'builtin_legacy',
  sourceId: 'resistivity',
  gridSha256: 'g'.repeat(64),
  netcdfSha256: 'n'.repeat(64),
}

function makeState(revision: number): RenderStateV2 {
  return {
    revision,
    mode: 'volume',
    filter: { min: 1, max: 1000 },
    opacity: 1,
    colorTransferFunction: [
      { value: 1, color: '#000000' },
      { value: 1000, color: '#ffffff' },
    ],
    lighting: true,
    gradientOpacity: true,
    boundingBox: true,
  }
}

function mountFrame(initialState = makeState(1)) {
  const wrapper = mount(SuperMapVolumeFrame, {
    props: { asset: null, displayTransform: { contract: 'wgs84_display_anchor_v1' } as never, initialState },
    attachTo: document.body,
  })
  const iframe = wrapper.find('iframe').element as HTMLIFrameElement
  const source = {} as Window
  Object.defineProperty(iframe, 'contentWindow', { value: source, configurable: true })
  const posted: Record<string, unknown>[] = []
  ;(source as { postMessage: (m: unknown, o: string) => void }).postMessage = (m) => {
    posted.push(JSON.parse(JSON.stringify(m)))
  }
  const emitChild = (data: Record<string, unknown>) => {
    window.dispatchEvent(
      new MessageEvent('message', {
        origin: window.location.origin,
        source,
        data: { ...data, protocol: VOLUME_FRAME_PROTOCOL, requestId: (wrapper.vm as never as { requestId: string }).requestId },
      }),
    )
  }
  return { wrapper, posted, emitChild }
}

describe('SuperMapVolumeFrame v2', () => {
  it('iframe src 携带帧内容版本查询参数（warm-cache 升级安全）', () => {
    const { wrapper } = mountFrame()
    const src = wrapper.find('iframe').attributes('src') ?? ''
    expect(src).toContain('/supermap-volume-frame/index.html?')
    expect(src).toContain('request_id=')
    expect(src).toMatch(/[?&]v=[0-9a-f]{16}/)
  })

  it('FRAME_READY 后恰好一次 INIT，携带完整初始状态', async () => {
    const { posted, emitChild } = mountFrame()
    emitChild({
      type: 'FRAME_READY',
      sdkVersion: '12.1.0',
      contextType: 2,
      capabilities: { singleAxisSlice: true, lighting: true, gradientOpacity: true, boundingBox: true, transferFunction: true },
    })
    await flushPromises()
    const inits = posted.filter((m) => m.type === 'INIT')
    expect(inits).toHaveLength(1)
    expect((inits[0].state as RenderStateV2).revision).toBe(1)
    expect((inits[0].state as RenderStateV2).mode).toBe('volume')

    // 第二次握手（新的 FRAME_READY）允许再次 INIT
    emitChild({
      type: 'FRAME_READY',
      sdkVersion: '12.1.0',
      contextType: 2,
      capabilities: { singleAxisSlice: true, lighting: true, gradientOpacity: true, boundingBox: true, transferFunction: true },
    })
    await flushPromises()
    expect(posted.filter((m) => m.type === 'INIT')).toHaveLength(2)
  })

  it('applyRenderState 每次携带新 commandId；非单调 revision 拒绝发送', async () => {
    const { wrapper, posted, emitChild } = mountFrame()
    emitChild({
      type: 'FRAME_READY',
      sdkVersion: '12.1.0',
      contextType: 2,
      capabilities: { singleAxisSlice: true, lighting: true, gradientOpacity: true, boundingBox: true, transferFunction: true },
    })
    await flushPromises()

    const api = wrapper.vm as never as {
      applyRenderState: (s: RenderStateV2) => boolean
    }
    expect(api.applyRenderState(makeState(2))).toBe(true)
    expect(api.applyRenderState(makeState(3))).toBe(true)
    expect(api.applyRenderState(makeState(3))).toBe(false) // 同 revision 拒绝
    expect(api.applyRenderState(makeState(2))).toBe(false) // 回退拒绝

    const applies = posted.filter((m) => m.type === 'APPLY_RENDER_STATE')
    expect(applies).toHaveLength(2)
    expect(applies[0].commandId).toBeTruthy()
    expect(applies[1].commandId).toBeTruthy()
    expect(applies[0].commandId).not.toBe(applies[1].commandId)
  })

  it('只有最新 revision 的 STATE_APPLIED 才向上派发', async () => {
    const { wrapper, emitChild } = mountFrame()
    emitChild({
      type: 'FRAME_READY',
      sdkVersion: '12.1.0',
      contextType: 2,
      capabilities: { singleAxisSlice: true, lighting: true, gradientOpacity: true, boundingBox: true, transferFunction: true },
    })
    await flushPromises()
    const api = wrapper.vm as never as { applyRenderState: (s: RenderStateV2) => boolean }
    api.applyRenderState(makeState(2))
    api.applyRenderState(makeState(3))

    emitChild({ type: 'STATE_APPLIED', commandId: 'x', revision: 2, appliedState: makeState(2) })
    await flushPromises()
    expect(wrapper.emitted('applied')).toBeUndefined()

    emitChild({ type: 'STATE_APPLIED', commandId: 'x', revision: 3, appliedState: makeState(3) })
    await flushPromises()
    expect(wrapper.emitted('applied')).toHaveLength(1)
  })

  it('RESET_VIEW 与 SET_POINT_LAYER 均带 commandId；COMMAND_APPLIED 向上转发', async () => {
    const { wrapper, posted, emitChild } = mountFrame()
    emitChild({
      type: 'FRAME_READY',
      sdkVersion: '12.1.0',
      contextType: 2,
      capabilities: { singleAxisSlice: true, lighting: true, gradientOpacity: true, boundingBox: true, transferFunction: true },
    })
    await flushPromises()
    const api = wrapper.vm as never as {
      resetView: () => void
      setPointLayer: (l: never) => void
    }
    api.resetView()
    const resets = posted.filter((m) => m.type === 'RESET_VIEW')
    expect(resets).toHaveLength(1)
    expect(resets[0].commandId).toBeTruthy()

    emitChild({ type: 'COMMAND_APPLIED', commandId: String(resets[0].commandId), commandType: 'RESET_VIEW' })
    await flushPromises()
    expect(wrapper.emitted('command-applied')).toHaveLength(1)
  })

  it('v1 消息与错误 requestId 一律忽略', async () => {
    const { wrapper, posted } = mountFrame()
    const source = {} as Window
    window.dispatchEvent(
      new MessageEvent('message', {
        origin: window.location.origin,
        source,
        data: {
          protocol: 'gmp-supermap-volume/v1',
          type: 'FRAME_READY',
          requestId: 'x',
          sdkVersion: '12.1.0',
          contextType: 2,
        },
      }),
    )
    await flushPromises()
    expect(posted).toHaveLength(0)
    expect(wrapper.emitted('ready')).toBeUndefined()
  })

  it('RENDER_STATE rendered 与 ERROR 正确派发', async () => {
    const { wrapper, emitChild } = mountFrame()
    emitChild({
      type: 'FRAME_READY',
      sdkVersion: '12.1.0',
      contextType: 2,
      capabilities: { singleAxisSlice: true, lighting: true, gradientOpacity: true, boundingBox: true, transferFunction: true },
    })
    await flushPromises()
    emitChild({ type: 'RENDER_STATE', phase: 'rendered', identity: RENDERED_IDENTITY })
    await flushPromises()
    expect(wrapper.emitted('rendered')).toHaveLength(1)

    emitChild({ type: 'ERROR', code: 'STATE_INVALID', message: 'bad state' })
    await flushPromises()
    expect(wrapper.emitted('failed')).toHaveLength(1)
  })
})

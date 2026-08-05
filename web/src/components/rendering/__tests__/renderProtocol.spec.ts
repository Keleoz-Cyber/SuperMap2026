import { describe, expect, it } from 'vitest'
import {
  VOLUME_FRAME_PROTOCOL,
  buildApplyRenderState,
  buildInitMessage,
  buildFrameUrl,
  isVolumeFrameEvent,
  parseChildMessage,
  validateRenderState,
  type RenderStateV2,
} from '../renderProtocol'

// v0.7.0 Batch 2 Task 7：iframe v2 线协议（完整状态 + revision + 回执）。

function makeState(revision = 1): RenderStateV2 {
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

describe('renderProtocol v2', () => {
  it('协议标识升级为 v2，v1 消息被拒绝', () => {
    expect(VOLUME_FRAME_PROTOCOL).toBe('gmp-supermap-volume/v2')
    const v1 = {
      protocol: 'gmp-supermap-volume/v1',
      type: 'FRAME_READY',
      requestId: 'r1',
      sdkVersion: '12.1.0',
      contextType: 2,
    }
    expect(parseChildMessage(v1)).toBeNull()
  })

  it('FRAME_READY 携带能力面；能力缺失/畸形返回 null', () => {
    const ready = parseChildMessage({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'FRAME_READY',
      requestId: 'r1',
      sdkVersion: '12.1.0',
      contextType: 2,
      capabilities: {
        singleAxisSlice: true,
        lighting: true,
        gradientOpacity: true,
        boundingBox: true,
        transferFunction: true,
      },
    })
    expect(ready).toMatchObject({ type: 'FRAME_READY', sdkVersion: '12.1.0', contextType: 2 })
    expect(
      parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'FRAME_READY',
        requestId: 'r1',
        sdkVersion: '12.1.0',
        contextType: 2,
      }),
    ).toBeNull()
    expect(
      parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'FRAME_READY',
        requestId: 'r1',
        sdkVersion: '12.1.0',
        contextType: 2,
        capabilities: { singleAxisSlice: 'yes' },
      }),
    ).toBeNull()
  })

  it('INIT 携带完整初始状态；APPLY_RENDER_STATE 携带 commandId 与状态', () => {
    const init = buildInitMessage('r1', null, { contract: 'wgs84_display_anchor_v1' } as never, makeState(1))
    expect(init.type).toBe('INIT')
    expect(init.protocol).toBe(VOLUME_FRAME_PROTOCOL)
    expect(init.state.revision).toBe(1)
    expect(init.state.mode).toBe('volume')

    const apply = buildApplyRenderState('r1', 'cmd-9', makeState(2))
    expect(apply.type).toBe('APPLY_RENDER_STATE')
    expect(apply.commandId).toBe('cmd-9')
    expect(apply.state.revision).toBe(2)
  })

  it('状态校验：非有限值、越界色带节点、非法切片、非法 revision 全部拒绝', () => {
    expect(() => validateRenderState({ ...makeState(), opacity: Number.NaN })).toThrow()
    expect(() =>
      validateRenderState({
        ...makeState(),
        colorTransferFunction: [{ value: Number.POSITIVE_INFINITY, color: '#fff' }],
      }),
    ).toThrow()
    expect(() =>
      validateRenderState({
        ...makeState(),
        colorTransferFunction: [{ value: 1, color: 'red' }],
      }),
    ).toThrow()
    expect(() =>
      validateRenderState({
        ...makeState(),
        mode: 'slice',
        slice: { axis: 'w' as never, index: 1, coordinate: 1, relativePosition: 0.5 },
      }),
    ).toThrow()
    expect(() =>
      validateRenderState({
        ...makeState(),
        mode: 'slice',
        slice: { axis: 'x', index: 1, coordinate: 1, relativePosition: 1.5 },
      }),
    ).toThrow()
    expect(() =>
      validateRenderState({
        ...makeState(),
        mode: 'slice',
        slice: { axis: 'x', index: -1, coordinate: 1, relativePosition: 0.5 },
      }),
    ).toThrow()
    expect(() => validateRenderState({ ...makeState(), revision: 0 })).toThrow()
    expect(() => validateRenderState({ ...makeState(), revision: 1.5 })).toThrow()
    expect(() => validateRenderState({ ...makeState(), filter: { min: 10, max: 1 } })).toThrow()
  })

  it('STATE_APPLIED/COMMAND_APPLIED/ERROR 子消息严格解析', () => {
    const applied = parseChildMessage({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'STATE_APPLIED',
      requestId: 'r1',
      commandId: 'cmd-1',
      revision: 3,
      appliedState: makeState(3),
    })
    expect(applied).toMatchObject({ type: 'STATE_APPLIED', revision: 3 })

    const ack = parseChildMessage({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'COMMAND_APPLIED',
      requestId: 'r1',
      commandId: 'cmd-2',
      commandType: 'RESET_VIEW',
    })
    expect(ack).toMatchObject({ type: 'COMMAND_APPLIED', commandType: 'RESET_VIEW' })

    const error = parseChildMessage({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'ERROR',
      requestId: 'r1',
      commandId: 'cmd-3',
      revision: 4,
      code: 'STATE_INVALID',
      message: 'bad',
    })
    expect(error).toMatchObject({ type: 'ERROR', code: 'STATE_INVALID' })

    expect(
      parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'STATE_APPLIED',
        requestId: 'r1',
        commandId: 'cmd-1',
        revision: '3',
        appliedState: makeState(3),
      }),
    ).toBeNull()
    expect(
      parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'COMMAND_APPLIED',
        requestId: 'r1',
        commandType: 'RESET_VIEW',
      }),
    ).toBeNull()
  })

  it('事件四重校验：origin/source/protocol/requestId 缺一不可', () => {
    const source = {} as Window
    const base = {
      origin: window.location.origin,
      source,
      data: { protocol: VOLUME_FRAME_PROTOCOL, requestId: 'r1', type: 'RENDER_STATE' },
    } as MessageEvent
    expect(isVolumeFrameEvent(base, source, 'r1')).toBe(true)
    expect(isVolumeFrameEvent({ ...base, origin: 'https://evil.example' } as MessageEvent, source, 'r1')).toBe(false)
    expect(isVolumeFrameEvent(base, {} as Window, 'r1')).toBe(false)
    expect(
      isVolumeFrameEvent(
        { ...base, data: { ...base.data, protocol: 'gmp-supermap-volume/v1' } } as MessageEvent,
        source,
        'r1',
      ),
    ).toBe(false)
    expect(
      isVolumeFrameEvent(
        { ...base, data: { ...base.data, requestId: 'r2' } } as MessageEvent,
        source,
        'r1',
      ),
    ).toBe(false)
  })

  it('buildFrameUrl 携带 requestId', () => {
    expect(buildFrameUrl('abc-123')).toContain('request_id=abc-123')
  })
})

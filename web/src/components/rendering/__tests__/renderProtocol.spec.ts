import { describe, expect, it } from 'vitest'
import {
  VOLUME_FRAME_PROTOCOL,
  isVolumeFrameEvent,
  parseChildMessage,
} from '../renderProtocol'

const REQUEST_ID = 'rvf-test-1234'

function makeEvent(overrides: {
  data?: unknown
  origin?: string
  source?: MessageEventSource | null
}): MessageEvent {
  return {
    data: overrides.data,
    origin: overrides.origin ?? window.location.origin,
    source: overrides.source === undefined ? window : overrides.source,
  } as MessageEvent
}

describe('isVolumeFrameEvent 四重校验（§2.4）', () => {
  const validData = {
    protocol: VOLUME_FRAME_PROTOCOL,
    type: 'FRAME_READY',
    requestId: REQUEST_ID,
    sdkVersion: '12.1.0',
    contextType: 2,
  }

  it('origin / source / protocol / requestId 全部匹配才接受', () => {
    expect(isVolumeFrameEvent(makeEvent({ data: validData }), window, REQUEST_ID)).toBe(true)
  })

  it('origin 不匹配被忽略', () => {
    expect(
      isVolumeFrameEvent(
        makeEvent({ data: validData, origin: 'https://evil.example' }),
        window,
        REQUEST_ID,
      ),
    ).toBe(false)
  })

  it('source 不匹配被忽略', () => {
    const other = {} as Window
    expect(isVolumeFrameEvent(makeEvent({ data: validData }), other, REQUEST_ID)).toBe(false)
    expect(isVolumeFrameEvent(makeEvent({ data: validData, source: null }), window, REQUEST_ID)).toBe(
      false,
    )
  })

  it('protocol 不匹配被忽略', () => {
    expect(
      isVolumeFrameEvent(
        makeEvent({ data: { ...validData, protocol: 'gmp-supermap-volume/v0' } }),
        window,
        REQUEST_ID,
      ),
    ).toBe(false)
    expect(isVolumeFrameEvent(makeEvent({ data: null }), window, REQUEST_ID)).toBe(false)
    expect(isVolumeFrameEvent(makeEvent({ data: 'FRAME_READY' }), window, REQUEST_ID)).toBe(false)
  })

  it('requestId 不匹配被忽略', () => {
    expect(
      isVolumeFrameEvent(makeEvent({ data: { ...validData, requestId: 'rvf-other' } }), window, REQUEST_ID),
    ).toBe(false)
    expect(isVolumeFrameEvent(makeEvent({ data: validData }), window, 'rvf-other')).toBe(false)
  })
})

describe('parseChildMessage 运行时守卫', () => {
  it('接受合法 FRAME_READY', () => {
    const msg = parseChildMessage({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'FRAME_READY',
      requestId: REQUEST_ID,
      sdkVersion: '12.1.0',
      contextType: 2,
    })
    expect(msg).toEqual({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'FRAME_READY',
      requestId: REQUEST_ID,
      sdkVersion: '12.1.0',
      contextType: 2,
    })
  })

  it('接受合法 RENDER_STATE（含 identity）', () => {
    const identity = {
      sourceKind: 'candidate_result',
      sourceId: 'r1',
      gridSha256: 'g'.repeat(64),
      netcdfSha256: 'n'.repeat(64),
    }
    const msg = parseChildMessage({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'RENDER_STATE',
      requestId: REQUEST_ID,
      phase: 'rendered',
      identity,
    })
    expect(msg).toMatchObject({ type: 'RENDER_STATE', phase: 'rendered', identity })
  })

  it('接受 asset=null 点云模式的 RENDER_STATE unsupported', () => {
    const msg = parseChildMessage({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'RENDER_STATE',
      requestId: REQUEST_ID,
      phase: 'unsupported',
      identity: null,
    })
    expect(msg).toMatchObject({ type: 'RENDER_STATE', phase: 'unsupported', identity: null })
  })

  it('接受合法 ERROR', () => {
    const msg = parseChildMessage({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'ERROR',
      requestId: REQUEST_ID,
      code: 'MANIFEST_HTTP_FAILED',
      message: 'HTTP 404',
    })
    expect(msg).toMatchObject({ type: 'ERROR', code: 'MANIFEST_HTTP_FAILED' })
  })

  it('拒绝未知 type / 缺字段 / 非法相位', () => {
    expect(
      parseChildMessage({ protocol: VOLUME_FRAME_PROTOCOL, type: 'PWNED', requestId: REQUEST_ID }),
    ).toBeNull()
    expect(
      parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'FRAME_READY',
        requestId: REQUEST_ID,
        sdkVersion: 121,
        contextType: 2,
      }),
    ).toBeNull()
    expect(
      parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'RENDER_STATE',
        requestId: REQUEST_ID,
        phase: 'hacked',
        identity: null,
      }),
    ).toBeNull()
    expect(
      parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'RENDER_STATE',
        requestId: REQUEST_ID,
        phase: 'rendered',
        identity: { sourceKind: 'candidate_result' },
      }),
    ).toBeNull()
    expect(
      parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'ERROR',
        requestId: REQUEST_ID,
        code: 'X',
      }),
    ).toBeNull()
  })
})

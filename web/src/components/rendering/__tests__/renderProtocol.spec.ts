import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  VOLUME_FRAME_PROTOCOL,
  buildApplyRenderState,
  buildFocusAnnotation,
  buildFrameUrl,
  buildInitMessage,
  buildSetCameraPreset,
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

  it('buildFrameUrl 携带 requestId 与帧内容版本（缓存升级即换 URL）', () => {
    const url = buildFrameUrl('abc-123')
    expect(url).toContain('request_id=abc-123')
    // 版本化：帧运行时（index/app/styles）内容哈希 + SDK 钉住哈希进入查询串，
    // 升级即换 URL，旧缓存条目永不命中（warm-cache 黑屏修复）
    expect(url).toMatch(/[?&]v=[0-9a-f]{16}/)
    expect(url).toMatch(/[?&]sdk=([0-9a-f]{16}|unpinned)/)
  })

  it('帧版本与 public/supermap-volume-frame 三文件内容哈希一致', () => {
    const hash = createHash('sha256')
    for (const name of ['index.html', 'app.js', 'styles.css']) {
      hash.update(
        readFileSync(resolve(__dirname, '../../../../public/supermap-volume-frame', name)),
      )
    }
    expect(buildFrameUrl('x')).toContain(`v=${hash.digest('hex').slice(0, 16)}`)
  })
})

// v0.9.0 Task 7：异常标注与相机协议扩展（设计 §6）。
// 标注进入完整渲染状态（INIT/APPLY 可选字段，v2 向后兼容）；相机预设与
// 组件聚焦是带 commandId 的父命令；三维标注点击由子帧 ANNOTATION_SELECTED 回报。
describe('renderProtocol v2 异常标注与相机（v0.9.0 Task 7）', () => {
  const ANNOTATION = {
    id: 'component-1',
    label: 'A',
    localPosition: [1, 2, 3],
    bounds: [
      [0, 2],
      [1, 3],
      [2, 4],
    ],
    valueMax: 10,
    supportMeasure: 8,
    supportUnit: 'volume_coordinate_unit3',
    color: '#64dab1',
    visible: true,
  }

  it('合法 annotations/focusedAnnotationId/sceneAids 通过校验且保持可选兼容', () => {
    // 缺省（v2 旧形态）仍通过
    expect(() => validateRenderState(makeState())).not.toThrow()
    const state = {
      ...makeState(),
      annotations: [ANNOTATION, { ...ANNOTATION, id: 'component-2', label: 'B' }],
      focusedAnnotationId: 'component-2',
      sceneAids: { axes: true, depthTicks: false },
    }
    expect(validateRenderState(state as never)).toBe(state)
  })

  it('非法标注一律拒绝：非有限坐标/越界 bounds/负支持量/非法色值/未知单位', () => {
    const bad = (mutate: (a: Record<string, unknown>) => void) => {
      const annotation = JSON.parse(JSON.stringify(ANNOTATION)) as Record<string, unknown>
      mutate(annotation)
      return { ...makeState(), annotations: [annotation] }
    }
    expect(() => validateRenderState(bad((a) => (a.localPosition = [1, Number.NaN, 3])) as never)).toThrow()
    expect(() => validateRenderState(bad((a) => (a.localPosition = [1, 2])) as never)).toThrow()
    expect(() => validateRenderState(bad((a) => (a.bounds = [[0, 2], [5, 3], [2, 4]])) as never)).toThrow()
    expect(() => validateRenderState(bad((a) => (a.bounds = [[0, Number.POSITIVE_INFINITY], [1, 3], [2, 4]])) as never)).toThrow()
    expect(() => validateRenderState(bad((a) => (a.supportMeasure = -1)) as never)).toThrow()
    expect(() => validateRenderState(bad((a) => (a.supportMeasure = Number.NaN)) as never)).toThrow()
    expect(() => validateRenderState(bad((a) => (a.valueMax = Number.NaN)) as never)).toThrow()
    expect(() => validateRenderState(bad((a) => (a.color = 'red')) as never)).toThrow()
    expect(() => validateRenderState(bad((a) => (a.supportUnit = 'real_volume_m3')) as never)).toThrow()
    expect(() => validateRenderState(bad((a) => (a.visible = 'yes')) as never)).toThrow()
    expect(() => validateRenderState(bad((a) => (a.id = '')) as never)).toThrow()
  })

  it('重复标注 id 与悬空 focusedAnnotationId 拒绝', () => {
    expect(() =>
      validateRenderState({ ...makeState(), annotations: [ANNOTATION, ANNOTATION] } as never),
    ).toThrow()
    expect(() =>
      validateRenderState({
        ...makeState(),
        annotations: [ANNOTATION],
        focusedAnnotationId: 'component-99',
      } as never),
    ).toThrow()
    // annotations 缺省时 focusedAnnotationId 不得非空
    expect(() =>
      validateRenderState({ ...makeState(), focusedAnnotationId: 'component-1' } as never),
    ).toThrow()
    // focusedAnnotationId: null 合法（清除聚焦）
    expect(() =>
      validateRenderState({ ...makeState(), annotations: [ANNOTATION], focusedAnnotationId: null } as never),
    ).not.toThrow()
  })

  it('sceneAids 非布尔拒绝', () => {
    expect(() =>
      validateRenderState({ ...makeState(), sceneAids: { axes: 'yes', depthTicks: true } } as never),
    ).toThrow()
  })

  it('SET_CAMERA_PRESET 父命令：四种预设合法，未知预设拒绝', () => {
    for (const preset of ['isometric', 'top-xy', 'front-xz', 'front-yz'] as const) {
      const msg = buildSetCameraPreset('r1', 'cmd-1', preset)
      expect(msg).toMatchObject({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'SET_CAMERA_PRESET',
        requestId: 'r1',
        commandId: 'cmd-1',
        preset,
      })
    }
    expect(() => buildSetCameraPreset('r1', 'cmd-1', 'orbit' as never)).toThrow()
  })

  it('FOCUS_ANNOTATION 父命令：合法 id 通过，空 id 拒绝', () => {
    const msg = buildFocusAnnotation('r1', 'cmd-2', 'component-1')
    expect(msg).toMatchObject({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'FOCUS_ANNOTATION',
      requestId: 'r1',
      commandId: 'cmd-2',
      annotationId: 'component-1',
    })
    expect(() => buildFocusAnnotation('r1', 'cmd-2', '')).toThrow()
  })

  it('ANNOTATION_SELECTED 子消息严格解析；COMMAND_APPLIED 扩展命令类型', () => {
    const selected = parseChildMessage({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'ANNOTATION_SELECTED',
      requestId: 'r1',
      annotationId: 'component-2',
    })
    expect(selected).toMatchObject({ type: 'ANNOTATION_SELECTED', annotationId: 'component-2' })
    expect(
      parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'ANNOTATION_SELECTED',
        requestId: 'r1',
        annotationId: '',
      }),
    ).toBeNull()
    expect(
      parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'ANNOTATION_SELECTED',
        requestId: 'r1',
      }),
    ).toBeNull()

    for (const commandType of ['SET_CAMERA_PRESET', 'FOCUS_ANNOTATION'] as const) {
      const ack = parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'COMMAND_APPLIED',
        requestId: 'r1',
        commandId: 'cmd-3',
        commandType,
      })
      expect(ack).toMatchObject({ type: 'COMMAND_APPLIED', commandType })
    }
    expect(
      parseChildMessage({
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'COMMAND_APPLIED',
        requestId: 'r1',
        commandId: 'cmd-3',
        commandType: 'FLY_TO_MOON',
      }),
    ).toBeNull()
  })

  it('STATE_APPLIED 回执中的扩展状态字段完整保留', () => {
    const state = {
      ...makeState(3),
      annotations: [ANNOTATION],
      focusedAnnotationId: null,
      sceneAids: { axes: true, depthTicks: true },
    }
    const ack = parseChildMessage({
      protocol: VOLUME_FRAME_PROTOCOL,
      type: 'STATE_APPLIED',
      requestId: 'r1',
      commandId: 'cmd-1',
      revision: 3,
      appliedState: state,
    })
    expect(ack).toMatchObject({ type: 'STATE_APPLIED', revision: 3 })
    const applied = (ack as { appliedState: RenderStateV2 }).appliedState
    expect(applied.annotations).toHaveLength(1)
    expect(applied.sceneAids).toEqual({ axes: true, depthTicks: true })
  })
})

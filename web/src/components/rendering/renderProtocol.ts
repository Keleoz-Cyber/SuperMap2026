/**
 * v0.7.0 Batch 2 Task 7：父页面（Vue）与隔离 SuperMap3D iframe 之间的 v2
 * 类型化协议桥（设计 §8，消息字段名与 web/public/supermap-volume-frame/app.js
 * 逐字一致）。
 *
 *   parent → INIT（完整初始状态）/ APPLY_RENDER_STATE（revision 完整状态）
 *            / SET_POINT_LAYER / RESET_VIEW（均带 commandId）
 *   child  → FRAME_READY（capabilities）/ RENDER_STATE / STATE_APPLIED
 *            / COMMAND_APPLIED / ERROR
 *
 * 双向都强制四重校验：
 *   event.origin === window.location.origin
 *   event.source === 预期窗口
 *   message.protocol === 'gmp-supermap-volume/v2'
 *   message.requestId === 活动 requestId
 * postMessage 目标 origin 恒为 window.location.origin，绝不 "*"。
 * v1 与任何畸形消息一律静默忽略；父侧出站状态先完整校验再发送。
 */

import type {
  DisplayTransform,
  PointLayerPayload,
  RenderAssetRecord,
  RenderIdentity,
} from '../../api/types'

export const VOLUME_FRAME_PROTOCOL = 'gmp-supermap-volume/v2' as const

export type VolumeMode = 'volume' | 'slice' | 'contour'
export type SliceAxis = 'x' | 'y' | 'z'
export type RenderPhase = 'loading' | 'rendered' | 'failed' | 'unsupported'

// ---------------------------------------------------------------------------
// 完整渲染状态（设计 §8.1）
// ---------------------------------------------------------------------------

export interface ColorStopWire {
  value: number
  color: string
}

export interface SliceStateV2 {
  axis: SliceAxis
  index: number
  coordinate: number
  relativePosition: number
}

export interface RenderStateV2 {
  revision: number
  mode: VolumeMode
  filter: { min: number; max: number }
  opacity: number
  colorTransferFunction: ColorStopWire[]
  lighting: boolean
  gradientOpacity: boolean
  boundingBox: boolean
  slice?: SliceStateV2
  contourValue?: number
}

export class ProtocolError extends Error {}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isHexColor(value: unknown): value is string {
  return typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value)
}

/** 出站状态完整校验：通过返回原对象（调用方负责克隆），失败抛 ProtocolError。 */
export function validateRenderState(state: RenderStateV2): RenderStateV2 {
  if (!state || typeof state !== 'object') throw new ProtocolError('STATE_INVALID')
  if (!Number.isInteger(state.revision) || state.revision < 1) {
    throw new ProtocolError('REVISION_INVALID')
  }
  if (!['volume', 'slice', 'contour'].includes(state.mode)) {
    throw new ProtocolError('MODE_INVALID')
  }
  const { filter, opacity } = state
  if (
    !filter ||
    !isFiniteNumber(filter.min) ||
    !isFiniteNumber(filter.max) ||
    filter.min > filter.max
  ) {
    throw new ProtocolError('FILTER_INVALID')
  }
  if (!isFiniteNumber(opacity) || opacity < 0 || opacity > 1) {
    throw new ProtocolError('OPACITY_INVALID')
  }
  if (
    !Array.isArray(state.colorTransferFunction) ||
    state.colorTransferFunction.length < 2 ||
    !state.colorTransferFunction.every(
      (stop) =>
        stop &&
        isFiniteNumber(stop.value) &&
        isHexColor(stop.color),
    )
  ) {
    throw new ProtocolError('COLOR_STOPS_INVALID')
  }
  for (const flag of ['lighting', 'gradientOpacity', 'boundingBox'] as const) {
    if (typeof state[flag] !== 'boolean') throw new ProtocolError(`${flag.toUpperCase()}_INVALID`)
  }
  if (state.slice !== undefined) {
    const slice = state.slice
    if (
      !slice ||
      !['x', 'y', 'z'].includes(slice.axis) ||
      !Number.isInteger(slice.index) ||
      slice.index < 0 ||
      !isFiniteNumber(slice.coordinate) ||
      !isFiniteNumber(slice.relativePosition) ||
      slice.relativePosition < 0 ||
      slice.relativePosition > 1
    ) {
      throw new ProtocolError('SLICE_INVALID')
    }
  }
  if (state.contourValue !== undefined && !isFiniteNumber(state.contourValue)) {
    throw new ProtocolError('CONTOUR_VALUE_INVALID')
  }
  return state
}

// ---------------------------------------------------------------------------
// 父 → 子消息
// ---------------------------------------------------------------------------

export interface InitMessageV2 {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'INIT'
  requestId: string
  asset: RenderAssetRecord | null
  displayTransform: DisplayTransform
  state: RenderStateV2
}

export interface ApplyRenderStateMessageV2 {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'APPLY_RENDER_STATE'
  requestId: string
  commandId: string
  state: RenderStateV2
}

export interface SetPointLayerMessageV2 {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'SET_POINT_LAYER'
  requestId: string
  commandId: string
  layer: PointLayerPayload
}

export interface ResetViewMessageV2 {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'RESET_VIEW'
  requestId: string
  commandId: string
}

export type ParentMessageV2 =
  | InitMessageV2
  | ApplyRenderStateMessageV2
  | SetPointLayerMessageV2
  | ResetViewMessageV2

export function buildInitMessage(
  requestId: string,
  asset: RenderAssetRecord | null,
  displayTransform: DisplayTransform,
  state: RenderStateV2,
): InitMessageV2 {
  return {
    protocol: VOLUME_FRAME_PROTOCOL,
    type: 'INIT',
    requestId,
    asset,
    displayTransform,
    state: validateRenderState(state),
  }
}

export function buildApplyRenderState(
  requestId: string,
  commandId: string,
  state: RenderStateV2,
): ApplyRenderStateMessageV2 {
  return {
    protocol: VOLUME_FRAME_PROTOCOL,
    type: 'APPLY_RENDER_STATE',
    requestId,
    commandId,
    state: validateRenderState(state),
  }
}

export function buildSetPointLayer(
  requestId: string,
  commandId: string,
  layer: PointLayerPayload,
): SetPointLayerMessageV2 {
  return { protocol: VOLUME_FRAME_PROTOCOL, type: 'SET_POINT_LAYER', requestId, commandId, layer }
}

export function buildResetView(requestId: string, commandId: string): ResetViewMessageV2 {
  return { protocol: VOLUME_FRAME_PROTOCOL, type: 'RESET_VIEW', requestId, commandId }
}

// ---------------------------------------------------------------------------
// 子 → 父消息
// ---------------------------------------------------------------------------

export interface FrameCapabilities {
  singleAxisSlice: boolean
  lighting: boolean
  gradientOpacity: boolean
  boundingBox: boolean
  transferFunction: boolean
}

export interface FrameReadyMessage {
  type: 'FRAME_READY'
  requestId: string
  sdkVersion: string
  contextType: number
  capabilities: FrameCapabilities
}

export interface RenderStateMessage {
  type: 'RENDER_STATE'
  requestId: string
  phase: RenderPhase
  identity: RenderIdentity | null
}

export interface StateAppliedMessage {
  type: 'STATE_APPLIED'
  requestId: string
  commandId: string
  revision: number
  appliedState: RenderStateV2
}

export interface CommandAppliedMessage {
  type: 'COMMAND_APPLIED'
  requestId: string
  commandId: string
  commandType: 'SET_POINT_LAYER' | 'RESET_VIEW'
}

export interface ErrorMessageV2 {
  type: 'ERROR'
  requestId: string
  commandId?: string
  revision?: number
  code: string
  message: string
}

export type ChildMessageV2 =
  | FrameReadyMessage
  | RenderStateMessage
  | StateAppliedMessage
  | CommandAppliedMessage
  | ErrorMessageV2

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function parseCapabilities(value: unknown): FrameCapabilities | null {
  if (!isRecord(value)) return null
  for (const key of [
    'singleAxisSlice',
    'lighting',
    'gradientOpacity',
    'boundingBox',
    'transferFunction',
  ] as const) {
    if (typeof value[key] !== 'boolean') return null
  }
  return value as unknown as FrameCapabilities
}

function parseStateWire(value: unknown): RenderStateV2 | null {
  if (!isRecord(value)) return null
  const state = { ...value } as Record<string, unknown>
  try {
    return validateRenderState(state as unknown as RenderStateV2)
  } catch {
    return null
  }
}

export function parseChildMessage(data: unknown): ChildMessageV2 | null {
  if (!isRecord(data)) return null
  if (data.protocol !== VOLUME_FRAME_PROTOCOL) return null
  if (typeof data.requestId !== 'string' || !data.requestId) return null
  switch (data.type) {
    case 'FRAME_READY': {
      if (typeof data.sdkVersion !== 'string' || typeof data.contextType !== 'number') return null
      const capabilities = parseCapabilities(data.capabilities)
      if (!capabilities) return null
      return {
        type: 'FRAME_READY',
        requestId: data.requestId,
        sdkVersion: data.sdkVersion,
        contextType: data.contextType,
        capabilities,
      }
    }
    case 'RENDER_STATE': {
      if (
        !['loading', 'rendered', 'failed', 'unsupported'].includes(String(data.phase)) ||
        (data.identity !== null && !isRecord(data.identity))
      ) {
        return null
      }
      return {
        type: 'RENDER_STATE',
        requestId: data.requestId,
        phase: data.phase as RenderPhase,
        identity: (data.identity ?? null) as RenderIdentity | null,
      }
    }
    case 'STATE_APPLIED': {
      if (
        typeof data.commandId !== 'string' ||
        !Number.isInteger(data.revision) ||
        (data.revision as number) < 1
      ) {
        return null
      }
      const appliedState = parseStateWire(data.appliedState)
      if (!appliedState) return null
      return {
        type: 'STATE_APPLIED',
        requestId: data.requestId,
        commandId: data.commandId,
        revision: data.revision as number,
        appliedState,
      }
    }
    case 'COMMAND_APPLIED': {
      if (
        typeof data.commandId !== 'string' ||
        !['SET_POINT_LAYER', 'RESET_VIEW'].includes(String(data.commandType))
      ) {
        return null
      }
      return {
        type: 'COMMAND_APPLIED',
        requestId: data.requestId,
        commandId: data.commandId,
        commandType: data.commandType as 'SET_POINT_LAYER' | 'RESET_VIEW',
      }
    }
    case 'ERROR': {
      if (typeof data.code !== 'string' || typeof data.message !== 'string') return null
      return {
        type: 'ERROR',
        requestId: data.requestId,
        commandId: typeof data.commandId === 'string' ? data.commandId : undefined,
        revision: Number.isInteger(data.revision) ? (data.revision as number) : undefined,
        code: data.code,
        message: data.message,
      }
    }
    default:
      return null
  }
}

// ---------------------------------------------------------------------------
// 事件校验与工具
// ---------------------------------------------------------------------------

export function isVolumeFrameEvent(
  event: MessageEvent,
  expectedSource: Window | null,
  expectedRequestId: string,
): boolean {
  if (event.origin !== window.location.origin) return false
  if (expectedSource !== null && event.source !== expectedSource) return false
  const data = event.data as { protocol?: unknown; requestId?: unknown } | null
  if (!data || data.protocol !== VOLUME_FRAME_PROTOCOL) return false
  return data.requestId === expectedRequestId
}

export function newFrameRequestId(): string {
  return `rvf-${crypto.randomUUID()}`
}

export function buildFrameUrl(requestId: string): string {
  return `/supermap-volume-frame/index.html?request_id=${encodeURIComponent(requestId)}`
}

/**
 * v0.6.1 Task 10：父页面（Vue）与隔离 SuperMap3D iframe 之间的类型化协议桥
 * （设计 §2.4，消息字段名与 web/public/supermap-volume-frame/app.js 逐字一致）。
 *
 *   parent → INIT / SET_MODE / SET_FILTER / SET_OPACITY / SET_POINT_LAYER / RESET_VIEW
 *   child  → FRAME_READY / RENDER_STATE / ERROR
 *
 * 双向都强制四重校验：
 *   event.origin === window.location.origin
 *   event.source === 预期窗口
 *   message.protocol === 'gmp-supermap-volume/v1'
 *   message.requestId === 活动 requestId
 * postMessage 目标 origin 恒为 window.location.origin，绝不 "*"。
 */

import type {
  DisplayTransform,
  PointLayerPayload,
  RenderAssetRecord,
  RenderIdentity,
} from '../../api/types'

export const VOLUME_FRAME_PROTOCOL = 'gmp-supermap-volume/v1' as const

export type VolumeMode = 'volume' | 'slice' | 'contour'

export type RenderPhase = 'loading' | 'rendered' | 'failed' | 'unsupported'

// ---------------------------------------------------------------------------
// 父 → 子命令
// ---------------------------------------------------------------------------

export interface InitMessage {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'INIT'
  requestId: string
  asset: RenderAssetRecord | null
  displayTransform: DisplayTransform
}

export interface SetModeMessage {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'SET_MODE'
  requestId: string
  mode: VolumeMode
}

export interface SetFilterMessage {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'SET_FILTER'
  requestId: string
  min: number
  max: number
}

export interface SetOpacityMessage {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'SET_OPACITY'
  requestId: string
  opacity: number
}

export interface SetPointLayerMessage {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'SET_POINT_LAYER'
  requestId: string
  layer: PointLayerPayload
}

export interface ResetViewMessage {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'RESET_VIEW'
  requestId: string
}

export type ParentMessage =
  | InitMessage
  | SetModeMessage
  | SetFilterMessage
  | SetOpacityMessage
  | SetPointLayerMessage
  | ResetViewMessage

// ---------------------------------------------------------------------------
// 子 → 父事件
// ---------------------------------------------------------------------------

export interface FrameReadyMessage {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'FRAME_READY'
  requestId: string
  sdkVersion: string
  contextType: number
}

export interface RenderStateMessage {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'RENDER_STATE'
  requestId: string
  phase: RenderPhase
  identity: RenderIdentity | null
}

export interface FrameErrorMessage {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'ERROR'
  requestId: string
  code: string
  message: string
}

export type ChildMessage = FrameReadyMessage | RenderStateMessage | FrameErrorMessage

// ---------------------------------------------------------------------------
// 运行时守卫
// ---------------------------------------------------------------------------

const RENDER_PHASES: ReadonlySet<string> = new Set(['loading', 'rendered', 'failed', 'unsupported'])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function isRenderIdentity(value: unknown): value is RenderIdentity {
  return (
    isRecord(value) &&
    (value.sourceKind === 'candidate_result' || value.sourceKind === 'builtin_legacy') &&
    typeof value.sourceId === 'string' &&
    typeof value.gridSha256 === 'string' &&
    typeof value.netcdfSha256 === 'string'
  )
}

/**
 * 入站事件四重校验：origin / source / protocol / requestId 任一项不符即忽略。
 * 只做信封级校验；消息体形态由 parseChildMessage 进一步判别。
 */
export function isVolumeFrameEvent(
  event: MessageEvent,
  expectedSource: Window | null,
  activeRequestId: string,
): boolean {
  if (event.origin !== window.location.origin) return false
  if (event.source !== expectedSource) return false
  const data: unknown = event.data
  if (!isRecord(data)) return false
  if (data.protocol !== VOLUME_FRAME_PROTOCOL) return false
  if (data.requestId !== activeRequestId) return false
  return true
}

/** 判别并校验子帧消息形态；不合法一律返回 null（调用方忽略）。 */
export function parseChildMessage(data: unknown): ChildMessage | null {
  if (!isRecord(data)) return null
  if (data.protocol !== VOLUME_FRAME_PROTOCOL) return null
  if (typeof data.requestId !== 'string' || data.requestId === '') return null
  switch (data.type) {
    case 'FRAME_READY':
      if (typeof data.sdkVersion !== 'string') return null
      if (typeof data.contextType !== 'number' || !Number.isFinite(data.contextType)) return null
      return {
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'FRAME_READY',
        requestId: data.requestId,
        sdkVersion: data.sdkVersion,
        contextType: data.contextType,
      }
    case 'RENDER_STATE':
      if (typeof data.phase !== 'string' || !RENDER_PHASES.has(data.phase)) return null
      if (data.identity !== null && !isRenderIdentity(data.identity)) return null
      return {
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'RENDER_STATE',
        requestId: data.requestId,
        phase: data.phase as RenderPhase,
        identity: data.identity ?? null,
      }
    case 'ERROR':
      if (typeof data.code !== 'string' || typeof data.message !== 'string') return null
      return {
        protocol: VOLUME_FRAME_PROTOCOL,
        type: 'ERROR',
        requestId: data.requestId,
        code: data.code,
        message: data.message,
      }
    default:
      return null
  }
}

/** iframe URL：requestId 经 URL 编码，子帧据此完成首次握手关联。 */
export function buildFrameUrl(requestId: string): string {
  return `/supermap-volume-frame/index.html?request_id=${encodeURIComponent(requestId)}`
}

/** 活动 requestId：随机、每次组件实例唯一（子帧正则为 ^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$）。 */
export function newFrameRequestId(): string {
  const cryptoApi = globalThis.crypto
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return `rvf-${cryptoApi.randomUUID()}`
  }
  return `rvf-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

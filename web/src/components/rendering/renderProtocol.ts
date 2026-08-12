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

// ---------------------------------------------------------------------------
// v0.9.0 Task 7：异常标注与相机（设计 §6）
// 标注是完整渲染状态的可选扩展（v2 向后兼容）；坐标恒为成果局部米制，
// 子帧按 INIT.displayTransform 变换；相机预设与组件聚焦为带 commandId 的命令。
// ---------------------------------------------------------------------------

export type CameraPreset = 'isometric' | 'top-xy' | 'front-xz' | 'front-yz'

export const CAMERA_PRESETS: readonly CameraPreset[] = ['isometric', 'top-xy', 'front-xz', 'front-yz']

export interface AnnotationWire {
  id: string
  label: string
  localPosition: [number, number, number]
  bounds: [[number, number], [number, number], [number, number]]
  valueMax: number
  supportMeasure: number
  supportUnit: 'volume_coordinate_unit3' | 'area_coordinate_unit2'
  color: string
  visible: boolean
}

export interface SceneAidsWire {
  axes: boolean
  depthTicks: boolean
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
  // v0.9.0 可选扩展：异常标注 / 聚焦标注 / 场景辅助（XYZ 轴 + 深度刻度）
  annotations?: AnnotationWire[]
  focusedAnnotationId?: string | null
  sceneAids?: SceneAidsWire
}

export class ProtocolError extends Error {}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isHexColor(value: unknown): value is string {
  return typeof value === 'string' && /^#[0-9a-fA-F]{6}$/.test(value)
}

const ANNOTATION_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/

function validateAnnotationWire(value: unknown, what: string): AnnotationWire {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new ProtocolError(`${what}_INVALID`)
  }
  const a = value as Record<string, unknown>
  if (typeof a.id !== 'string' || !ANNOTATION_ID_RE.test(a.id)) {
    throw new ProtocolError(`${what}_ID_INVALID`)
  }
  if (typeof a.label !== 'string' || a.label.length === 0 || a.label.length > 16) {
    throw new ProtocolError(`${what}_LABEL_INVALID`)
  }
  if (!Array.isArray(a.localPosition) || a.localPosition.length !== 3 || !a.localPosition.every(isFiniteNumber)) {
    throw new ProtocolError(`${what}_POSITION_INVALID`)
  }
  if (
    !Array.isArray(a.bounds) ||
    a.bounds.length !== 3 ||
    !a.bounds.every(
      (pair) =>
        Array.isArray(pair) &&
        pair.length === 2 &&
        pair.every(isFiniteNumber) &&
        (pair[0] as number) <= (pair[1] as number),
    )
  ) {
    throw new ProtocolError(`${what}_BOUNDS_INVALID`)
  }
  if (!isFiniteNumber(a.valueMax)) throw new ProtocolError(`${what}_VALUE_MAX_INVALID`)
  if (!isFiniteNumber(a.supportMeasure) || a.supportMeasure < 0) {
    throw new ProtocolError(`${what}_SUPPORT_INVALID`)
  }
  if (!['volume_coordinate_unit3', 'area_coordinate_unit2'].includes(String(a.supportUnit))) {
    throw new ProtocolError(`${what}_SUPPORT_UNIT_INVALID`)
  }
  if (!isHexColor(a.color)) throw new ProtocolError(`${what}_COLOR_INVALID`)
  if (typeof a.visible !== 'boolean') throw new ProtocolError(`${what}_VISIBLE_INVALID`)
  return value as AnnotationWire
}

function validateAnnotations(state: RenderStateV2): void {
  if (state.annotations === undefined) {
    if (state.focusedAnnotationId !== undefined && state.focusedAnnotationId !== null) {
      throw new ProtocolError('FOCUSED_ANNOTATION_WITHOUT_LIST')
    }
    return
  }
  if (!Array.isArray(state.annotations)) throw new ProtocolError('ANNOTATIONS_INVALID')
  const ids = new Set<string>()
  for (const raw of state.annotations) {
    const annotation = validateAnnotationWire(raw, 'ANNOTATION')
    if (ids.has(annotation.id)) throw new ProtocolError('ANNOTATION_DUPLICATE_ID')
    ids.add(annotation.id)
  }
  if (state.focusedAnnotationId !== undefined && state.focusedAnnotationId !== null) {
    if (typeof state.focusedAnnotationId !== 'string' || !ids.has(state.focusedAnnotationId)) {
      throw new ProtocolError('FOCUSED_ANNOTATION_UNKNOWN')
    }
  }
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
  validateAnnotations(state)
  if (state.sceneAids !== undefined) {
    const aids = state.sceneAids
    if (!aids || typeof aids.axes !== 'boolean' || typeof aids.depthTicks !== 'boolean') {
      throw new ProtocolError('SCENE_AIDS_INVALID')
    }
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

export interface SetCameraPresetMessageV2 {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'SET_CAMERA_PRESET'
  requestId: string
  commandId: string
  preset: CameraPreset
}

export interface FocusAnnotationMessageV2 {
  protocol: typeof VOLUME_FRAME_PROTOCOL
  type: 'FOCUS_ANNOTATION'
  requestId: string
  commandId: string
  annotationId: string
}

export type ParentMessageV2 =
  | InitMessageV2
  | ApplyRenderStateMessageV2
  | SetPointLayerMessageV2
  | ResetViewMessageV2
  | SetCameraPresetMessageV2
  | FocusAnnotationMessageV2

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

export function buildSetCameraPreset(
  requestId: string,
  commandId: string,
  preset: CameraPreset,
): SetCameraPresetMessageV2 {
  if (!CAMERA_PRESETS.includes(preset)) throw new ProtocolError('CAMERA_PRESET_INVALID')
  return { protocol: VOLUME_FRAME_PROTOCOL, type: 'SET_CAMERA_PRESET', requestId, commandId, preset }
}

export function buildFocusAnnotation(
  requestId: string,
  commandId: string,
  annotationId: string,
): FocusAnnotationMessageV2 {
  if (typeof annotationId !== 'string' || !ANNOTATION_ID_RE.test(annotationId)) {
    throw new ProtocolError('ANNOTATION_ID_INVALID')
  }
  return {
    protocol: VOLUME_FRAME_PROTOCOL,
    type: 'FOCUS_ANNOTATION',
    requestId,
    commandId,
    annotationId,
  }
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

export type FrameCommandType = 'SET_POINT_LAYER' | 'RESET_VIEW' | 'SET_CAMERA_PRESET' | 'FOCUS_ANNOTATION'

export interface CommandAppliedMessage {
  type: 'COMMAND_APPLIED'
  requestId: string
  commandId: string
  commandType: FrameCommandType
}

export interface AnnotationSelectedMessage {
  type: 'ANNOTATION_SELECTED'
  requestId: string
  annotationId: string
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
  | AnnotationSelectedMessage
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
        !['SET_POINT_LAYER', 'RESET_VIEW', 'SET_CAMERA_PRESET', 'FOCUS_ANNOTATION'].includes(
          String(data.commandType),
        )
      ) {
        return null
      }
      return {
        type: 'COMMAND_APPLIED',
        requestId: data.requestId,
        commandId: data.commandId,
        commandType: data.commandType as FrameCommandType,
      }
    }
    case 'ANNOTATION_SELECTED': {
      if (typeof data.annotationId !== 'string' || data.annotationId.length === 0) return null
      return {
        type: 'ANNOTATION_SELECTED',
        requestId: data.requestId,
        annotationId: data.annotationId,
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

// iframe URL 携带帧运行时内容哈希（v）与 SDK 钉住哈希（sdk）：升级即换 URL，
// 旧浏览器缓存中的旧版 app.js/index 永不命中（warm-cache 黑屏修复）。
export function buildFrameUrl(requestId: string): string {
  const params = new URLSearchParams({
    request_id: requestId,
    v: __VOLUME_FRAME_VERSION__,
    sdk: __VOLUME_SDK_VERSION__,
  })
  return `/supermap-volume-frame/index.html?${params.toString()}`
}

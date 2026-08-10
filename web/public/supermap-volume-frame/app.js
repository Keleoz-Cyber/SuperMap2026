/* v0.7.0 Batch 2 Task 8：隔离 SuperMap3D 体渲染 iframe 运行时（协议 v2）。
 *
 * 协议 gmp-supermap-volume/v2（设计 §8）：
 *   parent → INIT（完整初始状态）/ APPLY_RENDER_STATE（revision 完整状态）
 *            / SET_POINT_LAYER / RESET_VIEW（均带 commandId）
 *   child  → FRAME_READY（capabilities）/ RENDER_STATE / STATE_APPLIED
 *            / COMMAND_APPLIED / ERROR
 * revision 单调递增；iframe 忽略 <= 最后已应用 revision 的状态；
 * 应用失败回滚上一份已确认状态，回滚失败进入 failed，绝不继续显示已渲染。
 *
 * SDK API 写法以 origin/codex/v0.6.1-supermap-netcdf-handoff 实测为准：
 *   contextType=2（WebGL2）；startRender 前等待 layer._frameState 就绪；
 *   startRender 用 variableName/xDimName/yDimName/zDimName；
 *   layerBounds 用原始角度裸 Rectangle（本构建包 _computePosition 内部再做
 *   fromDegrees，绝不能再 fromDegrees）；zBounds 为米制 Cartesian2；
 *   相机 lookAt；RGB 控制点 0..1 浮点；透明度只走 opacityTransferFunction
 *   （opaqueRate 在本构建包不进 uniform，实测 no-op，故不携带）；filter
 *   min/max 直接赋值实时生效。
 *
 * 只读诊断快照 window.__GMP_VOLUME_FRAME__（Object.freeze，整体替换式更新）：
 * 绝不暴露 viewer/layer/token/文件路径。
 */

const PROTOCOL = 'gmp-supermap-volume/v2'
const CONTEXT_TYPE = 2
const MANIFEST_PREFIX = '/api/render-assets/'
const MAX_POINTS_PER_LAYER = 500_000
const REQUEST_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const POINT_LAYER_IDS = new Set([
  'grid-samples',
  'aggregated',
  'accepted',
  'rejected',
  'legacy-measurements',
])
const POINT_LAYER_ROLES = new Set(['auxiliary', 'evidence'])
const VOLUME_MODES = new Set(['volume', 'slice', 'contour'])
const TRANSFORM_KEYS = [
  'contract',
  'origin_x',
  'origin_y',
  'anchor_longitude',
  'anchor_latitude',
  'anchor_height',
  'metres_per_degree_lon',
  'metres_per_degree_lat',
]

// ---------------------------------------------------------------------------
// 只读诊断快照（唯一对外暴露）
// ---------------------------------------------------------------------------

const diag = {
  phase: 'idle', // idle → loading → rendered | failed | unsupported
  layerType: null,
  mode: null, // volume | slice | contour（协议命名）
  identity: null, // { sourceKind, sourceId, gridSha256, netcdfSha256 }
  boundingBoxVisible: false,
  // 体盒几何只读诊断（INIT 后写入，全模式不变；绝不暴露 viewer/layer 本体）：
  // { layerBoundsDegrees: {west,south,east,north}, zBoundsMetres: [z0,z1],
  //   cameraSpanMetres: 最大物理跨度（相机取景依据） }
  geometry: null,
  // v0.9.0：异常标注 / 场景辅助 / 相机预设只读诊断（全模式共享同一几何）
  annotations: { total: 0, visible: 0, focusedId: null },
  sceneAids: { axes: false, depthTicks: false },
  cameraPreset: 'isometric',
  errors: [], // [{ code, message }]
}

function publishDiag() {
  window.__GMP_VOLUME_FRAME__ = Object.freeze({
    protocol: PROTOCOL,
    phase: diag.phase,
    layerType: diag.layerType,
    mode: diag.mode,
    identity: diag.identity ? Object.freeze({ ...diag.identity }) : null,
    boundingBoxVisible: diag.boundingBoxVisible,
    annotations: Object.freeze({ ...diag.annotations }),
    sceneAids: Object.freeze({ ...diag.sceneAids }),
    cameraPreset: diag.cameraPreset,
    geometry: diag.geometry
      ? Object.freeze({
          layerBoundsDegrees: Object.freeze({ ...diag.geometry.layerBoundsDegrees }),
          zBoundsMetres: Object.freeze([...diag.geometry.zBoundsMetres]),
          dimensionOrder: Object.freeze([...diag.geometry.dimensionOrder]),
          cellSizeMetres: Object.freeze([...diag.geometry.cellSizeMetres]),
          bboxSpansMetres: Object.freeze([...diag.geometry.bboxSpansMetres]),
          cameraSpanMetres: diag.geometry.cameraSpanMetres,
        })
      : null,
    errors: Object.freeze(diag.errors.map((e) => Object.freeze({ ...e }))),
  })
}
publishDiag()

const overlay = document.getElementById('error-overlay')

function showOverlay(text) {
  overlay.textContent = text
  overlay.hidden = false
}

// ---------------------------------------------------------------------------
// 协议出站（目标 origin 恒为 window.location.origin，绝不 "*"）
// ---------------------------------------------------------------------------

const urlRequestId = new URLSearchParams(window.location.search).get('request_id') || ''

// URL request_id 未通过校验前静默：绝不以未校验身份发出任何协议消息
let bootValidated = false

function post(msg) {
  if (!bootValidated) return
  window.parent.postMessage({ protocol: PROTOCOL, requestId: urlRequestId, ...msg }, window.location.origin)
}

function emitRenderState() {
  post({ type: 'RENDER_STATE', phase: diag.phase, identity: diag.identity ? { ...diag.identity } : null })
}

function emitError(code, message, commandId, revision) {
  const payload = { type: 'ERROR', code, message: String(message).slice(0, 500) }
  if (typeof commandId === 'string') payload.commandId = commandId
  if (Number.isInteger(revision)) payload.revision = revision
  post(payload)
}

// 失败通道：记录诊断 + 覆盖层 + ERROR 消息；未 rendered 前同时翻转相位；
// fatal=true 时即使已经 rendered 也必须翻转相位并通知父页（恢复失败等
// 终态错误绝不允许继续显示已渲染）。
function fail(code, message, fatal) {
  const text = String(message).slice(0, 500)
  diag.errors.push({ code, message: text })
  if (diag.phase !== 'rendered' || fatal) {
    diag.phase = 'failed'
    publishDiag()
    emitRenderState()
  } else {
    publishDiag()
  }
  showOverlay(`${code}\n${text}`)
  emitError(code, text)
}

window.addEventListener('error', (e) => fail('PAGE_ERROR', e.message || e.type))
window.addEventListener('unhandledrejection', (e) =>
  fail('UNHANDLED_REJECTION', (e.reason && (e.reason.message || e.reason.stack)) || e.reason),
)

// ---------------------------------------------------------------------------
// 启动：URL request_id 校验 → FRAME_READY（校验不过绝不发握手）
// ---------------------------------------------------------------------------

if (!REQUEST_ID_RE.test(urlRequestId)) {
  fail('FRAME_BOOT_INVALID_REQUEST_ID', 'iframe URL 的 request_id 缺失或形态非法')
  throw new Error('FRAME_BOOT_INVALID_REQUEST_ID')
}
if (typeof SuperMap3D === 'undefined') {
  fail('FRAME_BOOT_SDK_MISSING', 'SuperMap3D 全局缺失（SDK 脚本未加载）')
  throw new Error('FRAME_BOOT_SDK_MISSING')
}
bootValidated = true
post({
  type: 'FRAME_READY',
  // 本构建包导出版本号为 MajorVersion（"12.1.0"）；Cesium 风格 VERSION 兜底
  sdkVersion: String(SuperMap3D.MajorVersion || SuperMap3D.VERSION || 'unknown'),
  contextType: CONTEXT_TYPE,
  // 公开 SDK 表面能力检查（不替代真实 GPU 单轴探针，见 Task 1 证据）
  capabilities: {
    singleAxisSlice:
      !!SuperMap3D.VolumeRenderMode && 'Slice' in SuperMap3D.VolumeRenderMode,
    lighting: true,
    gradientOpacity: true,
    boundingBox: !!SuperMap3D.PolylineCollection,
    transferFunction: !!SuperMap3D.ColorTransferFunction,
  },
})

// ---------------------------------------------------------------------------
// 运行时状态（不对外暴露）
// ---------------------------------------------------------------------------

let initialized = false
let viewer = null
let scene = null
let volumeLayer = null
let initTransform = null // INIT.displayTransform（点层坐标变换唯一依据）
let viewParams = null // RESET_VIEW 用：{ centerLon, centerLat, centerZ, span }
let valueRange = null // manifest 编码值域 [min, max]
const pointLayers = new Map() // id → PointPrimitiveCollection

// ---------------------------------------------------------------------------
// 校验辅助
// ---------------------------------------------------------------------------

function isFiniteNumber(v) {
  return typeof v === 'number' && Number.isFinite(v)
}

function requireDisplayTransform(t, what) {
  if (!t || typeof t !== 'object') throw new Error(`${what}：displayTransform 缺失`)
  if (t.contract !== 'wgs84_display_anchor_v1') {
    throw new Error(`${what}：displayTransform.contract 非法 ${t.contract}`)
  }
  for (const key of TRANSFORM_KEYS) {
    if (key === 'contract') continue
    if (!isFiniteNumber(t[key])) throw new Error(`${what}：displayTransform.${key} 不是有限数值`)
  }
  return t
}

function transformsEqual(a, b) {
  return TRANSFORM_KEYS.every((k) => Object.is(a[k], b[k]))
}

// 只接受 /api/render-assets/ 开头的同源相对路径（拒绝绝对 URL、//、..、% 编码）
function requireAssetPath(url, what) {
  if (
    typeof url !== 'string' ||
    !url.startsWith(MANIFEST_PREFIX) ||
    url.includes('..') ||
    url.includes('%') ||
    /[\s\\]/.test(url)
  ) {
    throw new Error(`ASSET_URL_REJECTED：${what} 只接受 ${MANIFEST_PREFIX} 开头的同源相对路径`)
  }
  return url
}

async function fetchJsonChecked(url, what) {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`MANIFEST_HTTP_FAILED：${what} HTTP ${resp.status}`)
  const type = (resp.headers.get('content-type') || '').toLowerCase()
  if (type.includes('text/html')) throw new Error(`MANIFEST_HTTP_FAILED：${what} 返回 HTML 错误页`)
  return resp.json()
}

// ---------------------------------------------------------------------------
// 有界帧等待（handoff 验证写法：startRender 前置条件 _frameState）
// ---------------------------------------------------------------------------

function waitLayerFrameState(layer, maxFrames = 600) {
  return new Promise((resolve, reject) => {
    let frames = 0
    const tick = () => {
      frames += 1
      if (layer._frameState) {
        resolve(frames)
        return
      }
      if (frames >= maxFrames) {
        reject(new Error('VOXEL_LAYER_LOAD_FAILED：600 帧内 _frameState 未就绪'))
        return
      }
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
}

// 画布像素探针：rendered 只在探到体积像素后发出。rAF 回调在合成前执行，
// 画布内容可读；同时 contextOptions.webgl.preserveDrawingBuffer=true 兜底。
function probeVolumePixels(minPixels = 1000, maxFrames = 900) {
  return new Promise((resolve, reject) => {
    const canvas = document.querySelector('#container canvas')
    if (!canvas) {
      reject(new Error('VOLUME_PIXELS_NOT_DETECTED：渲染 canvas 不存在'))
      return
    }
    const copy = document.createElement('canvas')
    const ctx = copy.getContext('2d', { willReadFrequently: true })
    let frames = 0
    const tick = () => {
      frames += 1
      copy.width = canvas.width
      copy.height = canvas.height
      ctx.drawImage(canvas, 0, 0)
      const d = ctx.getImageData(0, 0, copy.width, copy.height).data
      let nonBg = 0
      for (let i = 0; i < d.length; i += 4) {
        if (d[i] > 12 || d[i + 1] > 12 || d[i + 2] > 12) nonBg += 1
      }
      if (nonBg >= minPixels) {
        resolve(nonBg)
        return
      }
      if (frames >= maxFrames) {
        reject(new Error(`VOLUME_PIXELS_NOT_DETECTED：${maxFrames} 帧内非背景像素 ${nonBg} < ${minPixels}`))
        return
      }
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
}

// ---------------------------------------------------------------------------
// Viewer 与体图层（handoff 验证写法）
// ---------------------------------------------------------------------------

async function ensureViewer() {
  if (viewer) return
  viewer = new SuperMap3D.Viewer('container', {
    contextOptions: { contextType: CONTEXT_TYPE, webgl: { preserveDrawingBuffer: true } },
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
  })
  scene = viewer.scenePromise ? await viewer.scenePromise : viewer.scene
  // 确定性黑背景（handoff clean 模式）：体数据可位于地下，关闭地表/天空遮挡
  try {
    scene.skyBox.show = false
    scene.skyAtmosphere.show = false
    scene.sun.show = false
    scene.globe.showGroundAtmosphere = false
    scene.globe.show = false
    if (scene.backgroundColor) scene.backgroundColor = SuperMap3D.Color.BLACK
  } catch {
    /* 单项缺失不构成失败：保持黑底即可 */
  }
}

// handoff 色带：RGB 控制点 0..1 浮点，5 档蓝→青→黄→橙→红
function buildTransferFunctions(vmin, vmax) {
  const span = vmax - vmin
  const at = (f) => vmin + span * f
  const colors = new SuperMap3D.ColorTransferFunction()
  colors.addRGBPoint(at(0.0), 0.1, 0.25, 0.85)
  colors.addRGBPoint(at(0.25), 0.1, 0.8, 0.8)
  colors.addRGBPoint(at(0.5), 0.95, 0.85, 0.15)
  colors.addRGBPoint(at(0.75), 0.95, 0.35, 0.1)
  colors.addRGBPoint(at(1.0), 0.65, 0.05, 0.1)
  const opacity = opacityFunction(vmin, vmax, 1.0)
  return { colors, opacity }
}

// 不透明度只经 opacityTransferFunction 生效（opaqueRate 本构建包 no-op）
function opacityFunction(vmin, vmax, factor) {
  const span = vmax - vmin
  const at = (f) => vmin + span * f
  const fn = new SuperMap3D.PiecewiseFunction()
  fn.addPoint(at(0.0), 0.0)
  fn.addPoint(at(0.2), 0.05 * factor)
  fn.addPoint(at(0.5), 0.2 * factor)
  fn.addPoint(at(0.75), 0.55 * factor)
  fn.addPoint(at(1.0), 0.9 * factor)
  return fn
}

function lookAtVolume() {
  const { centerLon, centerLat, centerZ, span } = viewParams
  const target = SuperMap3D.Cartesian3.fromDegrees(centerLon, centerLat, centerZ)
  scene.camera.lookAt(target, new SuperMap3D.HeadingPitchRange(0.6, -0.9, span * 2.5))
}

// 独立包围盒线框：八个角点严格来自 layerBounds/zBounds（真实体元边界，
// 绝无任意固定外扩）。SDK fillStyle 自带的线框样式实测既不贴体数据、
// Slice 模式也不显示，因此包围盒一律由本实体承担，三模式共用；
// boundingBox 状态只控制它的 show。depthTest=false：线框与体素外表面
// 共面会被体渲染遮挡，包围盒语义要求全框可见（X 射线式）。
function addVolumeBoundingBox(bounds, zBounds) {
  const w = bounds.west
  const e = bounds.east
  const s = bounds.south
  const n = bounds.north
  const z0 = zBounds[0]
  const z1 = zBounds[1]
  // 底面四角 + 顶面四角
  const corners = [
    [w, s, z0],
    [e, s, z0],
    [e, n, z0],
    [w, n, z0],
    [w, s, z1],
    [e, s, z1],
    [e, n, z1],
    [w, n, z1],
  ]
  const edges = [
    [0, 1], [1, 2], [2, 3], [3, 0],
    [4, 5], [5, 6], [6, 7], [7, 4],
    [0, 4], [1, 5], [2, 6], [3, 7],
  ]
  const created = []
  for (const [a, b] of edges) {
    created.push(
      viewer.entities.add({
        polyline: {
          positions: SuperMap3D.Cartesian3.fromDegreesArrayHeights(
            [corners[a], corners[b]].flat(),
          ),
          width: 1.5,
          material: SuperMap3D.Color.WHITE.withAlpha(0.65),
          depthTest: false,
        },
      }),
    )
  }
  bboxPrimitives = created
}

function setBoundingBoxVisible(visible) {
  if (!bboxPrimitives) return
  for (const entity of bboxPrimitives) entity.show = visible
  diag.boundingBoxVisible = visible
}

// ---------------------------------------------------------------------------
// v0.9.0 Task 8：异常标注层与场景辅助（设计 §6）
// 标注 = PointPrimitiveCollection（锚点）+ PolylineCollection（短引线）+
// LabelCollection（文字）；坐标恒为成果局部米制，经 INIT.displayTransform
// 变换（与体数据同一 display-anchor 链）；每份已应用状态整体重建；
// focusedAnnotationId 高亮；不可见标注跳过；点击标注回报 ANNOTATION_SELECTED。
// ---------------------------------------------------------------------------

let annotationLayers = null // { points, lines, labels }
let annotationIds = new Set() // 当前场景中可点击的标注 id
let pickHandler = null
let axisEntities = null // XYZ 轴 + 深度刻度实体
let currentCameraPreset = 'isometric'

const ANNOTATION_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/
const SUPPORT_UNITS = new Set(['volume_coordinate_unit3', 'area_coordinate_unit2'])

function shortNumber(value) {
  const rounded = Number(value.toPrecision(6))
  return String(rounded)
}

function leaderHeightMetres() {
  if (viewParams && Number.isFinite(viewParams.span)) return Math.max(viewParams.span * 0.04, 5)
  return 20
}

function clearAnnotationLayers() {
  if (!annotationLayers) return
  for (const collection of Object.values(annotationLayers)) {
    try {
      scene.primitives.remove(collection)
    } catch {
      /* 已销毁不构成失败 */
    }
  }
  annotationLayers = null
  annotationIds = new Set()
}

function rebuildAnnotations(state) {
  clearAnnotationLayers()
  const list = Array.isArray(state.annotations) ? state.annotations : []
  const visible = list.filter((a) => a.visible !== false)
  diag.annotations = { total: list.length, visible: visible.length, focusedId: state.focusedAnnotationId ?? null }
  if (visible.length === 0) {
    publishDiag()
    return
  }
  const points = new SuperMap3D.PointPrimitiveCollection()
  const lines = new SuperMap3D.PolylineCollection()
  const labels = new SuperMap3D.LabelCollection()
  const ids = new Set()
  for (const a of visible) {
    const base = localToDisplay(initTransform, a.localPosition[0], a.localPosition[1], a.localPosition[2])
    const top = { lon: base.lon, lat: base.lat, height: base.height + leaderHeightMetres() }
    const focused = state.focusedAnnotationId === a.id
    const color = SuperMap3D.Color.fromCssColorString(a.color)
    const anchor = points.add({
      position: SuperMap3D.Cartesian3.fromDegrees(base.lon, base.lat, base.height),
      color,
      pixelSize: focused ? 14 : 9,
      outlineColor: focused ? SuperMap3D.Color.WHITE : SuperMap3D.Color.BLACK,
      outlineWidth: 1.5,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    })
    anchor.id = a.id
    lines.add({
      positions: [
        SuperMap3D.Cartesian3.fromDegrees(base.lon, base.lat, base.height),
        SuperMap3D.Cartesian3.fromDegrees(top.lon, top.lat, top.height),
      ],
      width: 1.2,
      material: SuperMap3D.Material.fromType('Color', { color: color.withAlpha(0.8) }),
    })
    const label = labels.add({
      position: SuperMap3D.Cartesian3.fromDegrees(top.lon, top.lat, top.height),
      text: `${a.label} · ${shortNumber(a.valueMax)}`,
      font: focused ? 'bold 16px sans-serif' : '13px sans-serif',
      fillColor: focused ? SuperMap3D.Color.fromCssColorString('#d9a84e') : SuperMap3D.Color.WHITE,
      style: SuperMap3D.LabelStyle.FILL_AND_OUTLINE,
      outlineColor: SuperMap3D.Color.BLACK,
      outlineWidth: 3,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    })
    label.id = a.id
    ids.add(a.id)
  }
  scene.primitives.add(points)
  scene.primitives.add(lines)
  scene.primitives.add(labels)
  annotationLayers = { points, lines, labels }
  annotationIds = ids
  publishDiag()
}

// 点击标注 → ANNOTATION_SELECTED（父侧仍按四重校验过滤）
function ensureAnnotationPicking() {
  if (pickHandler) return
  pickHandler = new SuperMap3D.ScreenSpaceEventHandler(scene.canvas)
  pickHandler.setInputAction((movement) => {
    if (!annotationLayers || annotationIds.size === 0) return
    const picked = scene.pick(movement.position)
    const primitive = picked && picked.primitive
    const id = primitive && typeof primitive.id === 'string' ? primitive.id : null
    if (id && annotationIds.has(id)) {
      post({ type: 'ANNOTATION_SELECTED', annotationId: id })
    }
  }, SuperMap3D.ScreenSpaceEventType.LEFT_CLICK)
}

// XYZ 轴 + Z 深度刻度：角点与体盒同一边界，标签展示局部坐标值
function clearSceneAids() {
  if (!axisEntities) return
  for (const entity of axisEntities) {
    try {
      viewer.entities.remove(entity)
    } catch {
      /* 已销毁不构成失败 */
    }
  }
  axisEntities = null
}

function buildSceneAids(bounds, zBounds) {
  clearSceneAids()
  const w = bounds.west
  const e = bounds.east
  const s = bounds.south
  const n = bounds.north
  const z0 = zBounds[0]
  const z1 = zBounds[1]
  const created = []
  const axisLine = (from, to, color) =>
    viewer.entities.add({
      show: false,
      polyline: {
        positions: SuperMap3D.Cartesian3.fromDegreesArrayHeights([...from, ...to]),
        width: 2.5,
        material: color,
        depthTest: false,
      },
    })
  // 轴起点：体盒 (west, south, z0) 角
  created.push(axisLine([w, s, z0], [e, s, z0], SuperMap3D.Color.fromCssColorString('#e06666')))
  created.push(axisLine([w, s, z0], [w, n, z0], SuperMap3D.Color.fromCssColorString('#6aa84f')))
  created.push(axisLine([w, s, z0], [w, s, z1], SuperMap3D.Color.fromCssColorString('#4d8de0')))
  // 轴端标签
  const axisLabel = (position, text, color) =>
    viewer.entities.add({
      show: false,
      position: SuperMap3D.Cartesian3.fromDegrees(...position),
      label: {
        text,
        font: 'bold 13px sans-serif',
        fillColor: color,
        style: SuperMap3D.LabelStyle.FILL_AND_OUTLINE,
        outlineColor: SuperMap3D.Color.BLACK,
        outlineWidth: 3,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    })
  created.push(axisLabel([e, s, z0], 'X', SuperMap3D.Color.fromCssColorString('#e06666')))
  created.push(axisLabel([w, n, z0], 'Y', SuperMap3D.Color.fromCssColorString('#6aa84f')))
  created.push(axisLabel([w, s, z1], 'Z', SuperMap3D.Color.fromCssColorString('#4d8de0')))
  // 深度刻度：沿 Z 轴 5 档，显示局部 z 值（display 高度 − anchor_height）
  const anchorHeight = initTransform.anchor_height
  for (let i = 0; i <= 4; i += 1) {
    const h = z0 + ((z1 - z0) * i) / 4
    const localZ = h - anchorHeight
    const tick = viewer.entities.add({
      show: false,
      position: SuperMap3D.Cartesian3.fromDegrees(w, s, h),
      label: {
        text: `${shortNumber(localZ)} m`,
        font: '11px sans-serif',
        fillColor: SuperMap3D.Color.fromCssColorString('#a7b8b0'),
        style: SuperMap3D.LabelStyle.FILL_AND_OUTLINE,
        outlineColor: SuperMap3D.Color.BLACK,
        outlineWidth: 3,
        pixelOffset: new SuperMap3D.Cartesian2(28, 0),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    })
    tick._gmpDepthTick = true
    created.push(tick)
  }
  axisEntities = created
}

function setSceneAidsVisible(aids) {
  if (!axisEntities) return
  const axesVisible = aids && aids.axes === true
  const ticksVisible = aids && aids.depthTicks === true
  for (const entity of axisEntities) {
    entity.show = entity._gmpDepthTick ? ticksVisible : axesVisible
  }
  diag.sceneAids = { axes: axesVisible, depthTicks: ticksVisible }
  publishDiag()
}

// 四种确定性相机预设：均以体盒中心为锚，绝不随机取景
function applyCameraPreset(preset) {
  if (!viewParams) throw new Error('CAMERA_PRESET_UNAVAILABLE：INIT 前无取景参数')
  const { centerLon, centerLat, centerZ, span } = viewParams
  const target = SuperMap3D.Cartesian3.fromDegrees(centerLon, centerLat, centerZ)
  const EPS = 0.02
  let heading
  let pitch
  let range = span * 2.5
  if (preset === 'isometric') {
    heading = 0.6
    pitch = -0.9
  } else if (preset === 'top-xy') {
    heading = 0
    pitch = -Math.PI / 2 + EPS
    range = span * 2.2
  } else if (preset === 'front-xz') {
    heading = 0
    pitch = -EPS
    range = span * 2.2
  } else if (preset === 'front-yz') {
    heading = Math.PI / 2
    pitch = -EPS
    range = span * 2.2
  } else {
    throw new Error(`CAMERA_PRESET_INVALID：${preset}`)
  }
  scene.camera.lookAt(target, new SuperMap3D.HeadingPitchRange(heading, pitch, range))
  currentCameraPreset = preset
  diag.cameraPreset = preset
  publishDiag()
}

function handleSetCameraPreset(msg) {
  applyCameraPreset(msg.preset)
  post({ type: 'COMMAND_APPLIED', commandId: msg.commandId, commandType: 'SET_CAMERA_PRESET' })
  emitRenderState()
}

// 组件聚焦：相机对准标注质心（距离按包围盒对角线），并更新高亮
function handleFocusAnnotation(msg) {
  const state = lastAppliedState
  const list = state && Array.isArray(state.annotations) ? state.annotations : []
  const target = list.find((a) => a.id === msg.annotationId)
  if (!target) throw new Error(`ANNOTATION_UNKNOWN：${msg.annotationId} 不在当前标注集中`)
  const display = localToDisplay(initTransform, target.localPosition[0], target.localPosition[1], target.localPosition[2])
  const spans = target.bounds.map((pair, i) => {
    const scale = i === 0 ? initTransform.metres_per_degree_lon : i === 1 ? initTransform.metres_per_degree_lat : 1
    return (pair[1] - pair[0]) * scale
  })
  const diagonal = Math.max(Math.hypot(spans[0], spans[1], spans[2]), 1)
  scene.camera.lookAt(
    SuperMap3D.Cartesian3.fromDegrees(display.lon, display.lat, display.height),
    new SuperMap3D.HeadingPitchRange(0.6, -0.6, diagonal * 3),
  )
  // 高亮同步到当前状态（后续完整状态推送以父侧 focusedAnnotationId 为准）
  state.focusedAnnotationId = target.id
  rebuildAnnotations(state)
  post({ type: 'COMMAND_APPLIED', commandId: msg.commandId, commandType: 'FOCUS_ANNOTATION' })
  emitRenderState()
}

// ---------------------------------------------------------------------------
// INIT：12 步（计划 Task 9 Step 3）
// ---------------------------------------------------------------------------

async function handleInit(msg) {
  if (initialized) {
    emitError('DUPLICATE_INIT', 'INIT 已应用，拒绝重复初始化')
    return
  }
  initialized = true

  // 1. requestId 已在监听器核对；这里校验 INIT 负载（displayTransform 必有）
  initTransform = requireDisplayTransform(msg.displayTransform, 'INIT')

  // 2. 创建 Viewer（contextType=2）
  await ensureViewer()

  // 3. asset=null：仅保留点层支持，emit unsupported（绝不 emit rendered）
  if (msg.asset === null) {
    clearAnnotationLayers()
    viewParams = {
      centerLon: initTransform.anchor_longitude,
      centerLat: initTransform.anchor_latitude,
      centerZ: initTransform.anchor_height,
      span: 3000,
    }
    lookAtVolume()
    diag.phase = 'unsupported'
    publishDiag()
    emitRenderState()
    return
  }

  // 资产记录形态校验（ready + 本渲染器 + 同源相对资产路径）
  const asset = msg.asset
  if (!asset || typeof asset !== 'object') throw new Error('INIT_INVALID_PAYLOAD：asset 缺失')
  if (asset.status !== 'ready') throw new Error(`INIT_INVALID_PAYLOAD：asset.status=${asset.status} 不是 ready`)
  if (asset.renderer !== 'supermap_voxelgrid_netcdf') {
    throw new Error(`INIT_INVALID_PAYLOAD：renderer=${asset.renderer} 不受支持`)
  }
  const manifestPath = requireAssetPath(asset.manifest_url, 'manifest_url')
  const netcdfPath = requireAssetPath(asset.netcdf_url, 'netcdf_url')

  diag.phase = 'loading'
  publishDiag()
  emitRenderState()

  // 4. 拉取 manifest（同源相对路径）
  const manifest = await fetchJsonChecked(manifestPath, 'manifest')

  // 5. manifest 身份与 display transform 必须与 POST/capability 响应一致
  if (
    manifest.source_kind !== asset.source_kind ||
    manifest.source_id !== asset.source_id ||
    manifest.grid_sha256 !== asset.grid_sha256 ||
    manifest.netcdf_sha256 !== asset.netcdf_sha256
  ) {
    throw new Error('MANIFEST_IDENTITY_MISMATCH：manifest 身份与资产记录不一致')
  }
  requireDisplayTransform(manifest.display_transform, 'manifest')
  if (!transformsEqual(manifest.display_transform, initTransform)) {
    throw new Error('MANIFEST_TRANSFORM_MISMATCH：manifest display_transform 与 INIT 不一致')
  }

  const bounds = manifest.layer_bounds_degrees
  const zBounds = manifest.z_bounds_metres
  const range = manifest.encoded_value_range || manifest.value_range
  if (
    !bounds ||
    !['west', 'south', 'east', 'north'].every((k) => isFiniteNumber(bounds[k])) ||
    !(bounds.west < bounds.east) ||
    !(bounds.south < bounds.north) ||
    !Array.isArray(zBounds) ||
    zBounds.length !== 2 ||
    !zBounds.every(isFiniteNumber) ||
    !(zBounds[0] < zBounds[1]) ||
    !Array.isArray(range) ||
    range.length !== 2 ||
    !range.every(isFiniteNumber) ||
    !(range[0] < range[1]) ||
    typeof manifest.variable_name !== 'string' ||
    !manifest.variable_name ||
    !Array.isArray(manifest.dimension_names) ||
    manifest.dimension_names.length !== 3
  ) {
    throw new Error('MANIFEST_INVALID：manifest 缺少渲染必需的边界/值域/变量字段')
  }
  valueRange = [range[0], range[1]]

  // 6. 添加 VoxelGridLayer3D
  const layer = await scene.addVoxelGridLayer(netcdfPath, manifest.variable_name)
  volumeLayer = layer
  diag.layerType = (layer.constructor && layer.constructor.name) || layer.type || 'unknown'
  publishDiag()

  // 7. 原始角度 layerBounds（裸 Rectangle）+ 米制 zBounds
  layer.layerBounds = new SuperMap3D.Rectangle(bounds.west, bounds.south, bounds.east, bounds.north)
  layer.zBounds = new SuperMap3D.Cartesian2(zBounds[0], zBounds[1])

  // 8. 有界帧循环等待 _frameState（startRender 前置条件）
  await waitLayerFrameState(layer)

  // 9. startRender（variableName/xDimName/yDimName/zDimName）
  await Promise.resolve(
    layer.startRender({
      variableName: manifest.variable_name,
      xDimName: manifest.dimension_names[0],
      yDimName: manifest.dimension_names[1],
      zDimName: manifest.dimension_names[2],
    }),
  )

  // 10. INIT 携带的完整渲染状态（先校验后应用；Task 8 起替代默认传递函数）
  const initialState = validateStateWire(msg.state, 'INIT')
  applyRenderStateToLayer(layer, initialState)
  lastAppliedState = initialState
  lastAppliedRevision = initialState.revision
  diag.mode = initialState.mode

  // 11. lookAt 体积中心（距离按最大物理跨度，经/纬用 manifest 变换的米/度）
  const t = manifest.display_transform
  viewParams = {
    centerLon: (bounds.west + bounds.east) / 2,
    centerLat: (bounds.south + bounds.north) / 2,
    centerZ: (zBounds[0] + zBounds[1]) / 2,
    span: Math.max(
      (bounds.east - bounds.west) * t.metres_per_degree_lon,
      (bounds.north - bounds.south) * t.metres_per_degree_lat,
      zBounds[1] - zBounds[0],
    ),
  }
  // 体盒几何只读诊断：边界/维度顺序/cell 尺寸/包围盒跨度/相机跨度（全模式不变）
  const spansMetres = [
    (bounds.east - bounds.west) * t.metres_per_degree_lon,
    (bounds.north - bounds.south) * t.metres_per_degree_lat,
    zBounds[1] - zBounds[0],
  ]
  diag.geometry = {
    layerBoundsDegrees: { west: bounds.west, south: bounds.south, east: bounds.east, north: bounds.north },
    zBoundsMetres: [zBounds[0], zBounds[1]],
    dimensionOrder: manifest.dimension_names.slice(),
    cellSizeMetres: spansMetres.map((span, i) =>
      manifest.shape[i] > 1 ? span / (manifest.shape[i] - 1) : span,
    ),
    bboxSpansMetres: spansMetres,
    cameraSpanMetres: viewParams.span,
  }
  publishDiag()
  // 独立包围盒线框（角点=真实体元边界；初始显隐由 INIT 状态决定）
  addVolumeBoundingBox(bounds, zBounds)
  setBoundingBoxVisible(initialState.boundingBox)
  // XYZ 轴与深度刻度：与体盒同一边界几何，初始显隐由 INIT sceneAids 决定
  buildSceneAids(bounds, zBounds)
  setSceneAidsVisible(initialState.sceneAids)
  ensureAnnotationPicking()
  lookAtVolume()

  // 12. 画布像素探针确认体积像素后才 emit rendered
  await probeVolumePixels()
  diag.identity = {
    sourceKind: manifest.source_kind,
    sourceId: manifest.source_id,
    gridSha256: manifest.grid_sha256,
    netcdfSha256: manifest.netcdf_sha256,
  }
  diag.phase = 'rendered'
  publishDiag()
  emitRenderState()
}

// ---------------------------------------------------------------------------
// v2 完整渲染状态：校验 → 应用 → revision 跟踪（设计 §8.3）
// ---------------------------------------------------------------------------

let lastAppliedState = null // 上一份已确认状态（应用失败回滚依据）
let lastAppliedRevision = 0 // iframe 会话内单调递增；<= 的一律忽略
let bboxPrimitives = null // 独立包围盒线框（PolylineCollection；三模式共用同一几何）

function isHexColorString(v) {
  return typeof v === 'string' && /^#[0-9a-fA-F]{6}$/.test(v)
}

function validateStateWire(state, what) {
  if (!state || typeof state !== 'object') throw new Error(`${what}：state 缺失`)
  if (!Number.isInteger(state.revision) || state.revision < 1) {
    throw new Error(`${what}：revision 必须是 ≥1 的整数`)
  }
  if (!VOLUME_MODES.has(state.mode)) throw new Error(`${what}：mode ${state.mode} 非法`)
  const filter = state.filter
  if (
    !filter ||
    !isFiniteNumber(filter.min) ||
    !isFiniteNumber(filter.max) ||
    filter.min > filter.max
  ) {
    throw new Error(`${what}：filter 必须是 min ≤ max 的有限数值`)
  }
  if (!isFiniteNumber(state.opacity) || state.opacity < 0 || state.opacity > 1) {
    throw new Error(`${what}：opacity 必须是 [0,1] 内的有限数值`)
  }
  if (
    !Array.isArray(state.colorTransferFunction) ||
    state.colorTransferFunction.length < 2 ||
    !state.colorTransferFunction.every(
      (stop) => stop && isFiniteNumber(stop.value) && isHexColorString(stop.color),
    )
  ) {
    throw new Error(`${what}：colorTransferFunction 必须是有限数值+十六进制色值节点`)
  }
  for (const flag of ['lighting', 'gradientOpacity', 'boundingBox']) {
    if (typeof state[flag] !== 'boolean') throw new Error(`${what}：${flag} 必须是布尔值`)
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
      throw new Error(`${what}：slice.axis/index/coordinate/relativePosition 合同不符`)
    }
  }
  if (state.contourValue !== undefined && !isFiniteNumber(state.contourValue)) {
    throw new Error(`${what}：contourValue 必须是有限数值`)
  }
  validateAnnotationsWire(state, what)
  if (state.sceneAids !== undefined) {
    const aids = state.sceneAids
    if (!aids || typeof aids.axes !== 'boolean' || typeof aids.depthTicks !== 'boolean') {
      throw new Error(`${what}：sceneAids.axes/depthTicks 必须是布尔值`)
    }
  }
  return state
}

// 异常标注线协议校验（与父侧 renderProtocol.ts 同一合同）：
// id 唯一且形态合法；局部坐标/bounds 全有限；支持量非负；色值十六进制；
// focusedAnnotationId 必须指向当前列表成员；缺省 annotations 时不得带聚焦 id。
function validateAnnotationsWire(state, what) {
  if (state.annotations === undefined) {
    if (state.focusedAnnotationId !== undefined && state.focusedAnnotationId !== null) {
      throw new Error(`${what}：focusedAnnotationId 缺少 annotations 列表`)
    }
    return
  }
  if (!Array.isArray(state.annotations)) throw new Error(`${what}：annotations 必须是数组`)
  const ids = new Set()
  for (const a of state.annotations) {
    if (!a || typeof a !== 'object') throw new Error(`${what}：annotation 缺失`)
    if (typeof a.id !== 'string' || !ANNOTATION_ID_RE.test(a.id)) {
      throw new Error(`${what}：annotation id 非法`)
    }
    if (typeof a.label !== 'string' || a.label.length === 0 || a.label.length > 16) {
      throw new Error(`${what}：annotation label 非法`)
    }
    if (!Array.isArray(a.localPosition) || a.localPosition.length !== 3 || !a.localPosition.every(isFiniteNumber)) {
      throw new Error(`${what}：annotation localPosition 必须是 3 个有限数值`)
    }
    if (
      !Array.isArray(a.bounds) ||
      a.bounds.length !== 3 ||
      !a.bounds.every(
        (pair) => Array.isArray(pair) && pair.length === 2 && pair.every(isFiniteNumber) && pair[0] <= pair[1],
      )
    ) {
      throw new Error(`${what}：annotation bounds 必须是 3 对 lo<=hi 有限数值`)
    }
    if (!isFiniteNumber(a.valueMax)) throw new Error(`${what}：annotation valueMax 非有限数值`)
    if (!isFiniteNumber(a.supportMeasure) || a.supportMeasure < 0) {
      throw new Error(`${what}：annotation supportMeasure 必须非负有限`)
    }
    if (!SUPPORT_UNITS.has(a.supportUnit)) throw new Error(`${what}：annotation supportUnit 非法`)
    if (!isHexColorString(a.color)) throw new Error(`${what}：annotation color 非法`)
    if (typeof a.visible !== 'boolean') throw new Error(`${what}：annotation visible 必须是布尔值`)
    if (ids.has(a.id)) throw new Error(`${what}：annotation id 重复 ${a.id}`)
    ids.add(a.id)
  }
  if (state.focusedAnnotationId !== undefined && state.focusedAnnotationId !== null) {
    if (typeof state.focusedAnnotationId !== 'string' || !ids.has(state.focusedAnnotationId)) {
      throw new Error(`${what}：focusedAnnotationId 不在当前标注集中`)
    }
  }
}

// 色带线节点 → SDK ColorTransferFunction（值域节点已由父侧按标度展开）
function colorFunctionFromWireStops(stops) {
  const fn = new SuperMap3D.ColorTransferFunction()
  for (const stop of stops) {
    const color = SuperMap3D.Color.fromCssColorString(stop.color)
    fn.addRGBPoint(stop.value, color.red, color.green, color.blue)
  }
  return fn
}

// 单轴切片坐标：Task 1 实测技术——非活动轴以负坐标隐藏（-1）
function sdkSliceCoordinate(slice) {
  const hidden = -1
  return new SuperMap3D.Cartesian3(
    slice.axis === 'x' ? slice.relativePosition : hidden,
    slice.axis === 'y' ? slice.relativePosition : hidden,
    slice.axis === 'z' ? slice.relativePosition : hidden,
  )
}

function applyRenderStateToLayer(layer, state) {
  const [vmin, vmax] = valueRange
  layer.minFiltration = state.filter.min
  layer.maxFiltration = state.filter.max
  layer.opacityTransferFunction = opacityFunction(vmin, vmax, state.opacity)
  layer.colorTransferFunction = colorFunctionFromWireStops(state.colorTransferFunction)
  layer.enableLighting = state.lighting
  layer.useGradientOpacity = state.gradientOpacity
  // fillStyle 恒为 Fill：SDK 线框样式实测超界且 Slice 模式不显示；
  // 包围盒由独立实体承担，boundingBox 只控制它的显隐
  layer.fillStyle = SuperMap3D.FillStyle.Fill
  setBoundingBoxVisible(state.boundingBox)
  const mode =
    state.mode === 'volume'
      ? SuperMap3D.VolumeRenderMode.VolumeRendering
      : state.mode === 'slice'
        ? SuperMap3D.VolumeRenderMode.Slice
        : SuperMap3D.VolumeRenderMode.ContourValue
  if (state.mode === 'slice') {
    if (!state.slice) throw new Error('APPLY_RENDER_STATE：slice 模式缺少 slice 载荷')
    layer.sliceCoordinate = sdkSliceCoordinate(state.slice)
  }
  if (state.mode === 'contour') {
    const requested = state.contourValue === undefined ? (vmin + vmax) / 2 : state.contourValue
    layer.contourValue = Math.min(vmax, Math.max(vmin, requested))
  }
  layer.volumeRenderMode = mode
  diag.mode = state.mode
  // 异常标注与场景辅助随完整状态重建（v0.9.0；缺省 annotations 时清空旧标注，
  // 绝不跨状态残留；可见性/聚焦以本份状态为唯一事实源）
  if (state.annotations !== undefined) rebuildAnnotations(state)
  else clearAnnotationLayers()
  setSceneAidsVisible(state.sceneAids)
  publishDiag()
}

function nextFrames(count) {
  return new Promise((resolve) => {
    let frames = 0
    const tick = () => {
      frames += 1
      if (frames >= count) resolve(frames)
      else requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
}

async function handleApplyRenderState(msg) {
  const layer = requireVolume('APPLY_RENDER_STATE')
  const state = validateStateWire(msg.state, 'APPLY_RENDER_STATE')
  // revision 单调递增：小于或等于最后已应用 revision 的状态整体忽略
  if (state.revision <= lastAppliedRevision) return
  const previousState = lastAppliedState
  const previousRevision = lastAppliedRevision
  try {
    applyRenderStateToLayer(layer, state)
  } catch (applyError) {
    // 应用异常：尝试恢复上一份已确认状态；恢复失败进入 failed
    try {
      if (previousState) applyRenderStateToLayer(layer, previousState)
    } catch (recoveryError) {
      // 恢复失败是终态错误：即使曾 rendered 也必须翻转相位并通知父页
      fail('RENDER_STATE_RECOVERY_FAILED', recoveryError, true)
      emitError('RENDER_STATE_RECOVERY_FAILED', recoveryError, msg.commandId, state.revision)
      return
    }
    lastAppliedState = previousState
    lastAppliedRevision = previousRevision
    emitError('RENDER_STATE_APPLY_FAILED', applyError, msg.commandId, state.revision)
    return
  }
  lastAppliedState = state
  lastAppliedRevision = state.revision
  // STATE_APPLIED 只能在属性设置完成且至少经过一个后续渲染帧后返回
  await nextFrames(2)
  post({
    type: 'STATE_APPLIED',
    commandId: msg.commandId,
    revision: state.revision,
    appliedState: state,
  })
  emitRenderState()
}

// ---------------------------------------------------------------------------
// 控制消息
// ---------------------------------------------------------------------------

function requireVolume(what) {
  if (diag.phase === 'unsupported' || !volumeLayer) {
    throw new Error(`VOLUME_NOT_AVAILABLE：${what} 需要已渲染的体图层（当前 ${diag.phase}）`)
  }
  if (diag.phase !== 'rendered') {
    throw new Error(`VOLUME_NOT_READY：${what} 需要 rendered 相位（当前 ${diag.phase}）`)
  }
  return volumeLayer
}

function localToDisplay(t, x, y, z) {
  return {
    lon: t.anchor_longitude + (x - t.origin_x) / t.metres_per_degree_lon,
    lat: t.anchor_latitude + (y - t.origin_y) / t.metres_per_degree_lat,
    height: t.anchor_height + z,
  }
}

function handleSetPointLayer(msg) {
  if (!initTransform) throw new Error('POINT_LAYER_INVALID：尚未 INIT，无显示变换依据')
  const payload = msg.layer
  if (!payload || typeof payload !== 'object') throw new Error('POINT_LAYER_INVALID：layer 缺失')
  if (!POINT_LAYER_IDS.has(payload.id)) throw new Error(`POINT_LAYER_INVALID：未知点层 id ${payload.id}`)
  if (payload.role !== undefined && !POINT_LAYER_ROLES.has(payload.role)) {
    throw new Error(`POINT_LAYER_INVALID：role ${payload.role}`)
  }
  if (payload.coordinates !== 'local') {
    throw new Error(`POINT_LAYER_INVALID：coordinates 只接受 local（${payload.coordinates}）`)
  }
  const { x, y, z, values, isNodata } = payload
  if (!Array.isArray(x) || !Array.isArray(y) || !Array.isArray(z) || x.length !== y.length || x.length !== z.length) {
    throw new Error('POINT_LAYER_INVALID：x/y/z 必须是等长数组')
  }
  if (x.length > MAX_POINTS_PER_LAYER) {
    throw new Error(`POINT_LAYER_TOO_LARGE：${x.length} > ${MAX_POINTS_PER_LAYER}`)
  }
  if (values !== undefined && (!Array.isArray(values) || values.length !== x.length)) {
    throw new Error('POINT_LAYER_INVALID：values 长度必须与坐标一致')
  }
  if (isNodata !== undefined && (!Array.isArray(isNodata) || isNodata.length !== x.length)) {
    throw new Error('POINT_LAYER_INVALID：isNodata 长度必须与坐标一致')
  }
  for (let i = 0; i < x.length; i += 1) {
    if (!isFiniteNumber(x[i]) || !isFiniteNumber(y[i]) || !isFiniteNumber(z[i])) {
      throw new Error(`POINT_LAYER_INVALID：坐标含非有限数值（index ${i}）`)
    }
  }
  const style = payload.style || {}
  const pixelSize = isFiniteNumber(style.pixelSize) && style.pixelSize > 0 ? style.pixelSize : 5

  let collection = pointLayers.get(payload.id)
  if (collection) {
    collection.removeAll()
  } else {
    collection = new SuperMap3D.PointPrimitiveCollection()
    scene.primitives.add(collection)
    pointLayers.set(payload.id, collection)
  }
  collection.show = payload.visible !== false

  const baseColor = style.color ? SuperMap3D.Color.fromCssColorString(style.color) : SuperMap3D.Color.WHITE
  const nodataColor = baseColor.withAlpha(0.25)
  const outlineColor = style.outlineColor
    ? SuperMap3D.Color.fromCssColorString(style.outlineColor)
    : SuperMap3D.Color.BLACK
  const outlineWidth = isFiniteNumber(style.outlineWidth) ? style.outlineWidth : 0
  for (let i = 0; i < x.length; i += 1) {
    const p = localToDisplay(initTransform, x[i], y[i], z[i])
    collection.add({
      position: SuperMap3D.Cartesian3.fromDegrees(p.lon, p.lat, p.height),
      color: isNodata && isNodata[i] ? nodataColor : baseColor,
      pixelSize,
      outlineColor,
      outlineWidth,
    })
  }
  post({ type: 'COMMAND_APPLIED', commandId: msg.commandId, commandType: 'SET_POINT_LAYER' })
  emitRenderState()
}

function handleResetView(msg) {
  if (!viewParams) throw new Error('RESET_VIEW 在 INIT 之前不可用')
  lookAtVolume()
  currentCameraPreset = 'isometric'
  diag.cameraPreset = 'isometric'
  publishDiag()
  post({ type: 'COMMAND_APPLIED', commandId: msg.commandId, commandType: 'RESET_VIEW' })
  emitRenderState()
}

// ---------------------------------------------------------------------------
// 协议入站：origin/source/protocol/requestId 四项全核（§2.4）
// ---------------------------------------------------------------------------

const handlers = {
  INIT: handleInit,
  APPLY_RENDER_STATE: handleApplyRenderState,
  SET_POINT_LAYER: handleSetPointLayer,
  RESET_VIEW: handleResetView,
  SET_CAMERA_PRESET: handleSetCameraPreset,
  FOCUS_ANNOTATION: handleFocusAnnotation,
}

window.addEventListener('message', (event) => {
  if (event.origin !== window.location.origin) return
  if (event.source !== window.parent) return
  const msg = event.data
  if (!msg || msg.protocol !== PROTOCOL) return
  if (msg.requestId !== urlRequestId) return
  const handler = handlers[msg.type]
  if (!handler) return
  Promise.resolve()
    .then(() => handler(msg))
    .catch((e) => {
      // 内部抛错统一 'CODE：message' 形态；外部异常回退稳定公共码
      const head = e && typeof e.message === 'string' ? e.message.split('：')[0] : ''
      const code = /^[A-Z][A-Z0-9_]{2,63}$/.test(head) ? head : 'FRAME_HANDLER_FAILED'
      fail(code, (e && (e.stack || e.message)) || e)
    })
})

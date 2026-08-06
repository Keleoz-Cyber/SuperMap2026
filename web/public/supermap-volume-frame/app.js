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
  errors: [], // [{ code, message }]
}

function publishDiag() {
  window.__GMP_VOLUME_FRAME__ = Object.freeze({
    protocol: PROTOCOL,
    phase: diag.phase,
    layerType: diag.layerType,
    mode: diag.mode,
    identity: diag.identity ? Object.freeze({ ...diag.identity }) : null,
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
    boundingBox: !!SuperMap3D.FillStyle && 'Fill_And_WireFrame' in SuperMap3D.FillStyle,
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
  return state
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
  layer.fillStyle = state.boundingBox
    ? SuperMap3D.FillStyle.Fill_And_WireFrame
    : SuperMap3D.FillStyle.Fill
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

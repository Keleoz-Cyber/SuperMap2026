<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Loading, Refresh, RefreshRight } from '@element-plus/icons-vue'
import { fetchRhoPoints, fetchVoxelCells, postBrowserLoad } from '../api/client'
import type { RhoPoints, VolumeServicePlan, VoxelCells } from '../api/types'

const props = defineProps<{ volume?: VolumeServicePlan }>()

const SCENE_URL = 'http://localhost:8090/iserver/services/3D-WorkSpace/rest/realspace'
const SCENE_NAME = 'RHO_三维全值域'
const RESULT_ID = 'RHO_KRIG_FINAL_20M_40'
const SCENE_OPEN_TIMEOUT_MS = 8000

// 体元包围盒（与 iServer dataset_info / 登记范围一致）
const BBOX = {
  x: [-160, -40] as [number, number],
  y: [220, 660] as [number, number],
  z: [-840, 0] as [number, number],
}

// 蓝 → 青 → 绿 → 黄 → 红
type ColorStop = [number, [number, number, number]]
const COLOR_STOPS: ColorStop[] = [
  [0.0, [37, 99, 235]],
  [0.25, [6, 182, 212]],
  [0.5, [34, 197, 94]],
  [0.75, [234, 179, 8]],
  [1.0, [239, 68, 68]],
]

const DECIMATE_OPTIONS = [
  { value: 1, label: '全量' },
  { value: 4, label: '1/4' },
  { value: 10, label: '1/10' },
  { value: 40, label: '1/40' },
]

const containerRef = ref<HTMLDivElement | null>(null)
const loading = ref(true)
const errorMsg = ref<string | null>(null)

const points = ref<RhoPoints | null>(null)
const renderedCount = ref(0)
const decimate = ref(4)
const zExaggeration = ref(1)
const pointSize = ref(5)
const valueRange = ref<[number, number]>([1, 150])
const thresholdEnabled = ref(false)
const threshold = ref(77)

const sceneOpenState = ref<'pending' | 'ok' | 'failed'>('pending')
const sceneLayerCount = ref(0)

// S3M 体元缓存渲染（FastAPI 经 iServer 取瓦片解析后的体元格点；available 时才加载）
const volumeState = ref<'none' | 'loading' | 'ok' | 'failed'>('none')
const displayMode = ref<'points' | 'volume' | 'both'>('points')
const voxelCells = ref<VoxelCells | null>(null)
const volumeBadgeText = computed(() => {
  if (volumeState.value === 'ok') return `体元缓存已加载（${voxelCells.value?.count.toLocaleString() ?? 0} 格）`
  if (volumeState.value === 'failed') return '体元缓存加载失败'
  if (volumeState.value === 'loading') return '体元缓存加载中…'
  return ''
})
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let voxelCollection: any = null

const fullMin = computed(() => points.value?.value_range[0] ?? 1)
const fullMax = computed(() => points.value?.value_range[1] ?? 150)

const sceneOpenText = computed(() => {
  if (sceneOpenState.value === 'ok') {
    return `iServer 场景已加载（${sceneLayerCount.value} 图层）`
  }
  if (sceneOpenState.value === 'failed') {
    return 'iServer 场景未加载（点云不受影响）'
  }
  return 'iServer 场景加载中…'
})

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let viewer: any = null
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let pointCollection: any = null
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let boxEntities: any[] = []
let rangeInited = false
// 浏览器加载回执只上报一次
let reportSent = false
let pointsRendered = false
let sceneOpenSettled = false
let sceneOpenTimer: ReturnType<typeof setTimeout> | null = null

// 平面场景坐标 → Cesium 世界坐标。
// COLUMBUS_VIEW 的 GeographicProjection 把 (lon*a, lat*a) 作为平面米坐标，
// 因此局部平面米坐标 (x, y) 对应 Cartographic(x/a, y/a, z)，
// 再经椭球转 ECEF 后才是图元可用的 position。
const EARTH_A = 6378137.0
function toScenePosition(x: number, y: number, z: number) {
  return Cesium.Ellipsoid.WGS84.cartographicToCartesian(
    new Cesium.Cartographic(x / EARTH_A, y / EARTH_A, z),
  )
}

function colorFor(value: number) {
  const [vmin, vmax] = valueRange.value
  const t = vmax > vmin ? Math.min(1, Math.max(0, (value - vmin) / (vmax - vmin))) : 0.5
  let idx = 0
  while (idx < COLOR_STOPS.length - 2 && t > COLOR_STOPS[idx + 1][0]) idx += 1
  const [t0, c0] = COLOR_STOPS[idx]
  const [t1, c1] = COLOR_STOPS[idx + 1]
  const f = t1 > t0 ? (t - t0) / (t1 - t0) : 0
  const r = Math.round(c0[0] + (c1[0] - c0[0]) * f)
  const g = Math.round(c0[1] + (c1[1] - c0[1]) * f)
  const b = Math.round(c0[2] + (c1[2] - c0[2]) * f)
  // eslint-disable-next-line @typescript-eslint/no-unsafe-return
  return Cesium.Color.fromBytes(r, g, b, 255)
}

function rebuildBox(zf: number) {
  if (!viewer) return
  for (const e of boxEntities) viewer.entities.remove(e)
  boxEntities = []
  const [x0, x1] = BBOX.x
  const [y0, y1] = BBOX.y
  const z0 = BBOX.z[0] * zf
  const z1 = BBOX.z[1] * zf
  // 角点索引：x * 4 + y * 2 + z
  const corner = (xi: number, yi: number, zi: number) => [
    xi === 0 ? x0 : x1,
    yi === 0 ? y0 : y1,
    zi === 0 ? z0 : z1,
  ]
  const edges: Array<[number[], number[]]> = [
    [corner(0, 0, 0), corner(0, 0, 1)],
    [corner(0, 1, 0), corner(0, 1, 1)],
    [corner(1, 0, 0), corner(1, 0, 1)],
    [corner(1, 1, 0), corner(1, 1, 1)],
    [corner(0, 0, 0), corner(0, 1, 0)],
    [corner(0, 0, 1), corner(0, 1, 1)],
    [corner(1, 0, 0), corner(1, 1, 0)],
    [corner(1, 0, 1), corner(1, 1, 1)],
    [corner(0, 0, 0), corner(1, 0, 0)],
    [corner(0, 0, 1), corner(1, 0, 1)],
    [corner(0, 1, 0), corner(1, 1, 0)],
    [corner(0, 1, 1), corner(1, 1, 1)],
  ]
  const material = Cesium.Color.CYAN.withAlpha(0.55)
  for (const [a, b] of edges) {
    boxEntities.push(
      viewer.entities.add({
        polyline: {
          positions: [toScenePosition(a[0], a[1], a[2]), toScenePosition(b[0], b[1], b[2])],
          width: 1.5,
          material,
          depthFailMaterial: material,
        },
      }),
    )
  }
  // 角点坐标标注（标注显示数据真实坐标）
  for (const xi of [0, 1]) {
    for (const yi of [0, 1]) {
      for (const zi of [0, 1]) {
        const [px, py, pz] = corner(xi, yi, zi)
        boxEntities.push(
          viewer.entities.add({
            position: toScenePosition(px, py, pz),
            label: {
              text: `(${px}, ${py}, ${Math.round(pz / zf)})`,
              font: '10px monospace',
              fillColor: Cesium.Color.fromCssColorString('#7fd4dc'),
              showBackground: true,
              backgroundColor: Cesium.Color.fromCssColorString('#0b0f14').withAlpha(0.75),
              pixelOffset: new Cesium.Cartesian2(0, -12),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          }),
        )
      }
    }
  }
}

function rebuildSceneContent() {
  if (!viewer || !pointCollection || !points.value) return
  const data = points.value
  const zf = zExaggeration.value
  const useThreshold = thresholdEnabled.value
  const th = threshold.value
  pointCollection.removeAll()
  let n = 0
  if (displayMode.value !== 'volume') {
    for (let i = 0; i < data.served; i += 1) {
      const v = data.values[i]
      if (useThreshold && v < th) continue
      pointCollection.add({
        position: toScenePosition(data.x[i], data.y[i], data.z[i] * zf),
        color: colorFor(v),
        pixelSize: pointSize.value,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      })
      n += 1
    }
  }
  renderedCount.value = n
  rebuildVoxelContent(zf, useThreshold, th)
  rebuildBox(zf)
}

// S3M 体元格点：与测点同一套色带/阈值/Z 夸张交互
function rebuildVoxelContent(zf: number, useThreshold: boolean, th: number) {
  if (!viewer || !voxelCollection || !voxelCells.value) return
  const data = voxelCells.value
  voxelCollection.removeAll()
  if (displayMode.value === 'points') return
  for (let i = 0; i < data.count; i += 1) {
    const v = data.values[i]
    if (useThreshold && v < th) continue
    voxelCollection.add({
      position: toScenePosition(data.x[i], data.y[i], data.z[i] * zf),
      color: colorFor(v),
      pixelSize: Math.max(3, pointSize.value - 1),
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    })
  }
}

async function loadPoints() {
  loading.value = true
  errorMsg.value = null
  try {
    const data = await fetchRhoPoints(decimate.value)
    points.value = data
    if (!rangeInited) {
      valueRange.value = [data.value_range[0], data.value_range[1]]
      rangeInited = true
    }
    rebuildSceneContent()
    pointsRendered = true
    maybeReportBrowserLoad()
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function settleSceneOpen(ok: boolean, layerCount: number) {
  if (sceneOpenSettled) return
  if (sceneOpenTimer !== null) {
    clearTimeout(sceneOpenTimer)
    sceneOpenTimer = null
  }
  sceneOpenSettled = true
  sceneOpenState.value = ok ? 'ok' : 'failed'
  sceneLayerCount.value = layerCount
  if (ok) {
    ElMessage.success(`iServer 场景「${SCENE_NAME}」加载成功（${layerCount} 个图层）`)
  } else {
    console.warn('iServer 场景打开失败（不影响点云渲染）')
  }
  // scene.open 会恢复 iServer 场景保存的相机，且恢复发生在回调之后的渲染帧；
  // 延迟一拍再把相机拉回本平台默认视角，避免被场景相机覆盖
  setTimeout(() => resetView(), 800)
  void loadVoxelCells()
  maybeReportBrowserLoad()
}

// 本构建（SuperMap 定制 Cesium 1.67）实测：PointPrimitiveCollection 的
// show 不生效（设 false 仍渲染）；scene.primitives.remove() 后再 add() 也不再渲染。
// 唯一可靠的可见性控制 = removeAll() 隐藏 / 从内存数据重建显示（2026-07-22 截图取证）。
function applyDisplayMode() {
  if (!viewer) return
  rebuildSceneContent()
}

// 经 FastAPI（iServer S3M 瓦片）加载体元格点并自定义渲染
async function loadVoxelCells() {
  const vol = props.volume
  if (!vol || !vol.available || !viewer || volumeState.value !== 'none') return
  volumeState.value = 'loading'
  try {
    const data = await fetchVoxelCells()
    voxelCells.value = data
    if (!voxelCollection) {
      voxelCollection = new Cesium.PointPrimitiveCollection()
      viewer.scene.primitives.add(voxelCollection)
    }
    rebuildSceneContent()
    applyDisplayMode()
    volumeState.value = 'ok'
    displayMode.value = 'both'
    applyDisplayMode()
    ElMessage.success(`S3M 体元缓存加载成功（${data.count.toLocaleString()} 格 / ${data.tile_files} 瓦片，经 iServer 服务）`)
    postBrowserLoad({
      case_id: 'resistivity',
      result_id: RESULT_ID,
      service_url: data.service_url,
      scene_name: vol.scene_name,
      layer_count: 1,
      success: true,
      render_kind: 's3m_voxel_cache',
      validated_count: data.count,
      note: `S3M 体元缓存浏览器渲染：${data.count} 格 / ${data.tile_files} 个 s3mb 瓦片经 iServer 服务获取并解析（${data.fetched_bytes} B）；值域 ${data.value_range[0].toFixed(2)}–${data.value_range[1].toFixed(2)}；范围 x[${data.x_range}] y[${data.y_range}] z[${data.z_range}]`,
    }).catch((e) => console.warn('体元缓存回执上报失败：', e))
  } catch (e) {
    volumeState.value = 'failed'
    console.warn('S3M 体元缓存加载失败（点云不受影响）：', e)
  }
}

function openIsServerScene() {
  try {
    if (!viewer || typeof viewer.scene.open !== 'function') {
      settleSceneOpen(false, 0)
      return
    }
    // iServer 不可达时 scene.open 可能长时间不回调，超时兜底按失败处理
    sceneOpenTimer = setTimeout(() => settleSceneOpen(false, 0), SCENE_OPEN_TIMEOUT_MS)
    const promise = viewer.scene.open(SCENE_URL, SCENE_NAME)
    const onOk = (layers: unknown) => {
      // 只有实际返回图层（>0）才算场景打开成功；空数组/非数组按失败处理
      const n = Array.isArray(layers) ? layers.length : 0
      settleSceneOpen(n > 0, n)
    }
    const onFail = (err: unknown) => {
      console.warn('scene.open 回调失败：', err)
      settleSceneOpen(false, 0)
    }
    if (typeof Cesium.when === 'function') {
      Cesium.when(promise, onOk, onFail)
    } else if (promise && typeof promise.then === 'function') {
      promise.then(onOk, onFail)
    } else {
      settleSceneOpen(false, 0)
    }
  } catch (err) {
    console.warn('scene.open 调用异常：', err)
    settleSceneOpen(false, 0)
  }
}

function maybeReportBrowserLoad() {
  if (reportSent || !pointsRendered || !sceneOpenSettled) return
  reportSent = true
  const ok = sceneOpenState.value === 'ok'
  postBrowserLoad({
    case_id: 'resistivity',
    result_id: RESULT_ID,
    service_url: SCENE_URL,
    scene_name: SCENE_NAME,
    layer_count: ok ? sceneLayerCount.value : 0,
    success: ok,
    render_kind: ok ? 'iserver_scene' : 'fallback_points',
    validated_count: ok ? sceneLayerCount.value : 0,
    note: ok
      ? `浏览器渲染完成：iServer 场景 ${sceneLayerCount.value} 个图层 + RHO 点云 ${renderedCount.value} 点（decimate=${decimate.value}）`
      : 'iServer 场景打开失败；仅点云独立渲染（fallback_points，不进入发布证据）',
  }).catch((e) => console.warn('浏览器加载回执上报失败：', e))
}

function resetView() {
  if (!viewer) return
  const data = points.value
  const cx = data ? (data.x_range[0] + data.x_range[1]) / 2 : -100
  const cy = data ? (data.y_range[0] + data.y_range[1]) / 2 : 440
  viewer.scene.camera.setView({
    destination: new Cesium.Cartesian3(cx, cy - 900, 1100),
    orientation: { heading: 0, pitch: Cesium.Math.toRadians(-55), roll: 0 },
    convert: false,
  })
}

function initViewer(): boolean {
  const el = containerRef.value
  if (!el) return false
  if (typeof Cesium === 'undefined') {
    errorMsg.value = 'Cesium 全局脚本未加载（请确认 public/Cesium/Cesium.js 存在）'
    return false
  }
  try {
    viewer = new Cesium.Viewer(el, {
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
    viewer.scene.mode = Cesium.SceneMode.COLUMBUS_VIEW
    viewer.imageryLayers.removeAll()
    if (viewer.scene.skyBox) viewer.scene.skyBox.show = false
    if (viewer.scene.skyAtmosphere) viewer.scene.skyAtmosphere.show = false
    if (viewer.scene.sun) viewer.scene.sun.show = false
    if (viewer.scene.moon) viewer.scene.moon.show = false
    viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#05070a')
    if (viewer.scene.globe) {
      viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#0b0f14')
    }
    pointCollection = new Cesium.PointPrimitiveCollection()
    viewer.scene.primitives.add(pointCollection)
    // E2E/debug handle: lets automated checks drive the camera and inspect state
    ;(window as unknown as Record<string, unknown>).__rhoViewer = viewer
    return true
  } catch (e) {
    errorMsg.value = `WebGL 场景初始化失败：${e instanceof Error ? e.message : String(e)}`
    return false
  }
}

function retry() {
  if (!viewer) {
    if (!initViewer()) return
    resetView()
    openIsServerScene()
  }
  void loadPoints()
}

function formatValue(v: number): string {
  return v.toFixed(1)
}

function formatTimes(v: number): string {
  return `${v}×`
}

onMounted(() => {
  if (!initViewer()) {
    loading.value = false
    return
  }
  resetView()
  void loadPoints()
  openIsServerScene()
})

// publish-status 可能晚于场景就绪返回；volume 变为可用时补一次加载
watch(
  () => props.volume?.available,
  (avail) => {
    if (avail && volumeState.value === 'none' && viewer) void loadVoxelCells()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (sceneOpenTimer !== null) clearTimeout(sceneOpenTimer)
  if (viewer && typeof viewer.isDestroyed === 'function' && !viewer.isDestroyed()) {
    viewer.destroy()
  }
  viewer = null
  pointCollection = null
  voxelCollection = null
  boxEntities = []
})
</script>

<template>
  <div class="scene-wrap">
    <div ref="containerRef" class="scene-container"></div>

    <div v-if="points && !errorMsg" class="scene-toolbar">
      <div v-if="volumeState === 'ok'" class="toolbar-row">
        <span class="toolbar-label">显示内容</span>
        <el-radio-group v-model="displayMode" size="small" @change="applyDisplayMode">
          <el-radio-button value="points">点云</el-radio-button>
          <el-radio-button value="volume">体元</el-radio-button>
          <el-radio-button value="both">叠加</el-radio-button>
        </el-radio-group>
      </div>
      <div class="toolbar-row">
        <span class="toolbar-label">色带值域（RHO）</span>
        <el-slider
          v-model="valueRange"
          range
          :min="fullMin"
          :max="fullMax"
          :step="0.1"
          @change="rebuildSceneContent"
        />
      </div>
      <div class="toolbar-row">
        <div class="toolbar-line">
          <span class="toolbar-label">阈值过滤（RHO ≥ 阈值）</span>
          <el-switch v-model="thresholdEnabled" size="small" @change="rebuildSceneContent" />
        </div>
        <el-slider
          v-model="threshold"
          :min="fullMin"
          :max="fullMax"
          :step="0.5"
          :disabled="!thresholdEnabled"
          @change="rebuildSceneContent"
        />
        <span class="toolbar-hint">演示阈值，非地质结论</span>
      </div>
      <div class="toolbar-row">
        <span class="toolbar-label">点大小（{{ pointSize }} px）</span>
        <el-slider v-model="pointSize" :min="2" :max="10" :step="1" @change="rebuildSceneContent" />
      </div>
      <div class="toolbar-row">
        <span class="toolbar-label">抽稀</span>
        <el-radio-group v-model="decimate" size="small" @change="loadPoints">
          <el-radio-button v-for="o in DECIMATE_OPTIONS" :key="o.value" :value="o.value">
            {{ o.label }}
          </el-radio-button>
        </el-radio-group>
      </div>
      <div class="toolbar-row">
        <span class="toolbar-label">Z 夸张（{{ zExaggeration }}×）</span>
        <el-slider
          v-model="zExaggeration"
          :min="1"
          :max="5"
          :step="0.5"
          :format-tooltip="formatTimes"
          @change="rebuildSceneContent"
        />
      </div>
      <el-button size="small" :icon="RefreshRight" class="reset-btn" @click="resetView">
        复位视角
      </el-button>
    </div>

    <div v-if="points && !errorMsg" class="scene-legend">
      <div class="legend-bar"></div>
      <div class="legend-labels">
        <span>{{ formatValue(valueRange[0]) }}</span>
        <span>RHO</span>
        <span>{{ formatValue(valueRange[1]) }}</span>
      </div>
    </div>

    <div v-if="points && !errorMsg" class="scene-status">
      <span class="status-item mono">
        {{ renderedCount.toLocaleString() }} / {{ points.count.toLocaleString() }} 点
      </span>
      <span class="status-item">
        <span
          class="dot"
          :class="sceneOpenState === 'ok' ? 'ok' : sceneOpenState === 'failed' ? 'bad' : 'pending'"
        ></span>
        {{ sceneOpenText }}
      </span>
      <span v-if="volumeBadgeText" class="status-item">
        <span
          class="dot"
          :class="volumeState === 'ok' ? 'ok' : volumeState === 'failed' ? 'bad' : 'pending'"
        ></span>
        {{ volumeBadgeText }}
      </span>
    </div>

    <div v-if="loading" class="scene-mask">
      <el-icon class="is-loading" :size="28"><Loading /></el-icon>
      <p>正在加载 RHO 点云…</p>
    </div>

    <div v-if="errorMsg && !loading" class="scene-mask">
      <el-result icon="error" title="三维场景加载失败" :sub-title="errorMsg">
        <template #extra>
          <el-button type="primary" :icon="Refresh" @click="retry">重试</el-button>
        </template>
      </el-result>
    </div>
  </div>
</template>

<style scoped>
.scene-wrap {
  position: relative;
  flex: 1;
  min-height: 560px;
  height: 640px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--gmp-border-soft);
  background: #05070a;
}

.scene-container {
  position: absolute;
  inset: 0;
}

.scene-toolbar {
  position: absolute;
  top: 12px;
  left: 12px;
  width: 252px;
  background: rgba(13, 19, 26, 0.88);
  border: 1px solid var(--gmp-border);
  border-radius: 10px;
  padding: 12px 14px;
  backdrop-filter: blur(6px);
  z-index: 10;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.toolbar-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.toolbar-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.toolbar-label {
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.toolbar-hint {
  font-size: 11px;
  color: var(--gmp-text-faint);
}

.reset-btn {
  align-self: flex-end;
}

.scene-legend {
  position: absolute;
  left: 12px;
  bottom: 30px;
  z-index: 10;
  background: rgba(13, 19, 26, 0.85);
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  padding: 8px 10px;
  width: 210px;
}

.legend-bar {
  height: 10px;
  border-radius: 5px;
  background: linear-gradient(90deg, #2563eb, #06b6d4, #22c55e, #eab308, #ef4444);
}

.legend-labels {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-size: 11px;
  color: var(--gmp-text-dim);
}

.scene-status {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 10;
  display: flex;
  flex-direction: column;
  gap: 6px;
  align-items: flex-end;
}

.status-item {
  background: rgba(13, 19, 26, 0.85);
  border: 1px solid var(--gmp-border);
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.scene-mask {
  position: absolute;
  inset: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: rgba(11, 15, 20, 0.78);
  color: var(--gmp-text-dim);
  font-size: 13px;
}

.scene-mask :deep(.el-result) {
  background: transparent;
  padding: 20px;
}
</style>

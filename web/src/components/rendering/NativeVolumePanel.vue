<script lang="ts">
import type { PointLayerStyle, RenderAssetRecord, RenderCapability } from '../../api/types'

// 面板的数据层以回调注入：候选成果与内置电阻率共用本面板，
// 各自绑定 client.ts 中对应的 capability/create/fetch 函数（Task 11/12 接线）。
export interface NativeVolumeRenderApi {
  fetchCapability: () => Promise<RenderCapability>
  fetchAsset: () => Promise<RenderAssetRecord>
  createAsset: (retryFailed: boolean) => Promise<RenderAssetRecord>
}

// 辅助采样点载荷（不含 visible/coordinates：visible 由复选框决定，coordinates 恒为 local）
export interface NativeVolumeAuxPoints {
  id: 'grid-samples' | 'legacy-measurements'
  role: 'auxiliary' | 'evidence'
  x: number[]
  y: number[]
  z: number[]
  values?: number[]
  isNodata?: boolean[]
  style: PointLayerStyle
}
</script>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Aim } from '@element-plus/icons-vue'
import { ApiError } from '../../api/client'
import type { PointLayerPayload, RenderIdentity } from '../../api/types'
import SuperMapVolumeFrame from './SuperMapVolumeFrame.vue'
import { buildColorStops } from './renderTransferFunctions'
import type { RenderStateV2, VolumeMode } from './renderProtocol'

const props = withDefaults(
  defineProps<{
    api: NativeVolumeRenderApi
    auxPoints?: NativeVolumeAuxPoints | null
  }>(),
  { auxPoints: null },
)

type VolumePhase = 'idle' | 'loading' | 'rendered' | 'failed'

const capabilityLoading = ref(true)
const capabilityError = ref<string | null>(null)
const capability = ref<RenderCapability | null>(null)

const assetChecked = ref(false)
const asset = ref<RenderAssetRecord | null>(null)
const creating = ref(false)
const createError = ref<string | null>(null)

const frameRef = ref<InstanceType<typeof SuperMapVolumeFrame> | null>(null)
const frameReady = ref(false)
const phase = ref<VolumePhase>('idle')
const identity = ref<RenderIdentity | null>(null)
const frameError = ref<{ code: string; message: string } | null>(null)

const mode = ref<VolumeMode>('volume')
const sliceZ = ref(0.5)
const contourValueInput = ref('')
const opacity = ref(1)
const filterMinInput = ref('')
const filterMaxInput = ref('')
const filterError = ref<string | null>(null)
const auxVisible = ref(false)

function formatError(e: unknown): string {
  return e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
}

// frame 初始化载荷：仅在有能力 + 显示变换时挂载；
// supported 时只在 ready 资产后挂载，unsupported 时以 asset=null 进入点云专用初始化
const frameInit = computed<{
  asset: RenderAssetRecord | null
  transform: NonNullable<RenderCapability['display_transform']>
  initialState: RenderStateV2
} | null>(() => {
  const cap = capability.value
  const transform = cap?.display_transform
  if (!cap || !transform) return null
  const initialState = currentRenderState()
  if (cap.supported) {
    const record = asset.value
    return record && record.status === 'ready' ? { asset: record, transform, initialState } : null
  }
  return { asset: null, transform, initialState }
})

// 体积控件门禁：能力支持 + ready 资产 + frame 报告 rendered，三者缺一不可
const controlsEnabled = computed(
  () =>
    capability.value?.supported === true &&
    asset.value?.status === 'ready' &&
    phase.value === 'rendered',
)

const phaseText = computed(() => {
  if (capability.value && !capability.value.supported) return '不支持体渲染'
  switch (phase.value) {
    case 'loading':
      return '原生渲染加载中…'
    case 'rendered':
      return '已渲染'
    case 'failed':
      return '原生渲染失败'
    default:
      return '待初始化'
  }
})

async function refreshAsset() {
  // 状态刷新是纯 GET：绝不隐式 POST
  try {
    asset.value = await props.api.fetchAsset()
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      asset.value = null
    } else {
      createError.value = formatError(e)
    }
  }
}

async function load() {
  capabilityLoading.value = true
  capabilityError.value = null
  try {
    capability.value = await props.api.fetchCapability()
  } catch (e) {
    capabilityError.value = formatError(e)
    capabilityLoading.value = false
    return
  }
  capabilityLoading.value = false
  await refreshAsset()
  assetChecked.value = true
}

function resetFrameState() {
  frameReady.value = false
  phase.value = 'idle'
  identity.value = null
  frameError.value = null
}

async function create(retryFailed: boolean) {
  // 显式变异动作：唯一会触发 POST 的入口
  creating.value = true
  createError.value = null
  try {
    const record = await props.api.createAsset(retryFailed)
    asset.value = record
    resetFrameState()
  } catch (e) {
    createError.value = formatError(e)
    // 失败后以 GET 同步持久化资产状态（failed 行含稳定错误码）
    await refreshAsset()
  } finally {
    creating.value = false
  }
}

function pushPointLayer() {
  const points = props.auxPoints
  if (!frameReady.value || !points) return
  const layer: PointLayerPayload = {
    ...points,
    visible: auxVisible.value,
    coordinates: 'local',
  }
  frameRef.value?.setPointLayer(layer)
}

function onFrameReady() {
  frameReady.value = true
  if (phase.value === 'idle') phase.value = 'loading'
  pushPointLayer()
}

function onFrameRendered(payload: RenderIdentity | null) {
  identity.value = payload
  phase.value = 'rendered'
}

function onFrameFailed(error: { code: string; message: string }) {
  // 原生失败保持显式错误：绝不切换到任何替代渲染
  frameError.value = error
  phase.value = 'failed'
}

// v0.7.0 第二批 Task 7 桥接适配：控件状态组装为完整 v2 渲染状态。
// 默认值来自 capability.render_profile（色带/标度经 Task 6 纯函数展开）；
// 缺省（点云专用初始化）使用固定安全默认。Task 9/10/11 将把这些控件拆分为
// VolumeRenderToolbar 与 OrthogonalSliceControls，并以剖面 API 的真实
// index/coordinate 取代本处的相对位置占位（index/coordinate 暂为 0）。
const renderRevision = ref(1)

function profileDefaults() {
  const profile = capability.value?.render_profile ?? null
  const range: [number, number] = profile ? profile.value_range : [0, 1]
  return {
    range,
    stops: buildColorStops(profile?.default_palette ?? 'viridis', profile?.default_scale ?? 'linear', range),
    lighting: profile?.lighting ?? true,
    gradientOpacity: profile?.gradient_opacity ?? true,
    boundingBox: profile?.bounding_box ?? true,
    opacity: profile?.opacity ?? 1,
  }
}

function currentRenderState(mutate?: (state: RenderStateV2) => void): RenderStateV2 {
  const defaults = profileDefaults()
  const state: RenderStateV2 = {
    revision: renderRevision.value,
    mode: mode.value,
    filter: { min: defaults.range[0], max: defaults.range[1] },
    opacity: defaults.opacity,
    colorTransferFunction: defaults.stops,
    lighting: defaults.lighting,
    gradientOpacity: defaults.gradientOpacity,
    boundingBox: defaults.boundingBox,
  }
  if (mode.value === 'slice') {
    state.slice = { axis: 'z', index: 0, coordinate: 0, relativePosition: sliceZ.value }
  }
  if (mode.value === 'contour') {
    const contourValue = Number(contourValueInput.value)
    if (Number.isFinite(contourValue) && contourValueInput.value.trim() !== '') {
      state.contourValue = contourValue
    }
  }
  mutate?.(state)
  return state
}

function pushRenderState(mutate?: (state: RenderStateV2) => void) {
  if (!controlsEnabled.value) return
  const state = currentRenderState(mutate)
  if (frameRef.value?.applyRenderState(state)) {
    renderRevision.value += 1
  }
}

function selectMode(next: VolumeMode) {
  mode.value = next
  pushRenderState()
}

function applySliceCoordinate() {
  pushRenderState((state) => {
    state.mode = 'slice'
    state.slice = { axis: 'z', index: 0, coordinate: 0, relativePosition: sliceZ.value }
  })
}

function applyContourValue() {
  const contourValue = Number(contourValueInput.value)
  if (!Number.isFinite(contourValue)) return
  pushRenderState((state) => {
    state.mode = 'contour'
    state.contourValue = contourValue
  })
}

function applyFilter() {
  const rawMin = String(filterMinInput.value).trim()
  const rawMax = String(filterMaxInput.value).trim()
  const min = Number(rawMin)
  const max = Number(rawMax)
  if (rawMin === '' || rawMax === '' || !Number.isFinite(min) || !Number.isFinite(max) || min > max) {
    filterError.value = '滤波范围必须是有限数值且 min ≤ max'
    return
  }
  filterError.value = null
  pushRenderState((state) => {
    state.filter = { min, max }
  })
}

function onOpacityInput() {
  pushRenderState((state) => {
    state.opacity = opacity.value
  })
}

function onResetView() {
  frameRef.value?.resetView()
}

function sendPointLayer(layer: PointLayerPayload) {
  frameRef.value?.setPointLayer(layer)
}

defineExpose({ sendPointLayer })

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="native-volume-panel" data-test="native-volume-panel">
    <header class="panel-header">
      <h3 class="panel-title">NetCDF 原生体渲染</h3>
      <span class="volume-phase" data-test="volume-phase">{{ phaseText }}</span>
    </header>

    <!-- 固定真值标签：渲染器 / 坐标状态 / 辅助点定位，恒显 -->
    <ul class="truth-labels" data-test="truth-labels">
      <li>渲染器：SuperMap3D VoxelGridLayer3D</li>
      <li>坐标状态：显示锚点（非真实地理配准）</li>
      <li>辅助采样点：不参与连续体渲染</li>
    </ul>

    <div v-if="capabilityLoading" class="panel-note" data-test="capability-loading">能力检查中…</div>
    <div v-else-if="capabilityError" class="panel-error" data-test="capability-error">
      {{ capabilityError }}
      <button class="link-button" data-test="reload-capability" @click="load">重试</button>
    </div>

    <template v-else-if="capability">
      <div class="panel-note" data-test="geo-status">坐标契约：{{ capability.geolocation_status }}</div>

      <!-- 不支持：稳定原因码 + 原因；有显示变换时以 asset=null 进入点云专用初始化 -->
      <div v-if="!capability.supported" class="panel-error" data-test="unsupported-reason">
        <strong>{{ capability.reason_code }}</strong>
        <span v-if="capability.reason">：{{ capability.reason }}</span>
      </div>

      <template v-else>
        <div class="asset-actions">
          <button
            v-if="assetChecked && !asset"
            class="primary-button"
            data-test="create-asset"
            :disabled="creating"
            @click="create(false)"
          >
            {{ creating ? '正在生成…' : '生成 NetCDF 体渲染资产' }}
          </button>
          <button
            v-if="asset && (asset.status === 'failed' || asset.status === 'interrupted')"
            class="primary-button"
            data-test="retry-asset"
            :disabled="creating"
            @click="create(true)"
          >
            {{ creating ? '正在重试…' : '重试生成渲染资产' }}
          </button>
          <button class="link-button" data-test="refresh-asset" :disabled="creating" @click="refreshAsset">
            刷新状态
          </button>
        </div>

        <div v-if="asset && asset.error" class="panel-error" data-test="asset-error">
          {{ asset.error.code }}：{{ asset.error.message }}
        </div>
        <div v-if="createError" class="panel-error" data-test="create-error">{{ createError }}</div>

        <div v-if="asset" class="asset-identity" data-test="asset-identity">
          <div>资产：{{ asset.id }}（{{ asset.renderer }}，状态 {{ asset.status }}）</div>
          <div>网格 SHA-256：{{ asset.grid_sha256.slice(0, 16) }}…</div>
          <div v-if="asset.netcdf_sha256">NetCDF SHA-256：{{ asset.netcdf_sha256.slice(0, 16) }}…</div>
          <div>坐标契约：{{ capability.geolocation_status }}</div>
          <div v-if="identity">
            渲染身份：{{ identity.sourceKind }}/{{ identity.sourceId }}，网格
            {{ identity.gridSha256.slice(0, 12) }}…，NetCDF {{ identity.netcdfSha256.slice(0, 12) }}…
          </div>
        </div>
      </template>

      <div v-if="frameError" class="panel-error" data-test="frame-error">
        {{ frameError.code }}：{{ frameError.message }}
      </div>

      <SuperMapVolumeFrame
        v-if="frameInit"
        ref="frameRef"
        :key="frameInit.asset ? frameInit.asset.id : 'point-only'"
        :asset="frameInit.asset"
        :display-transform="frameInit.transform"
        :initial-state="frameInit.initialState"
        @ready="onFrameReady"
        @rendered="onFrameRendered"
        @failed="onFrameFailed"
      />

      <!-- 体积控件：只在 rendered 后启用；体积绝不被名为「点」的显示模式隐藏 -->
      <div class="volume-controls" data-test="volume-controls">
        <div class="mode-tabs" role="group" aria-label="渲染模式">
          <button
            class="mode-tab"
            :class="{ active: mode === 'volume' }"
            data-test="mode-volume"
            :disabled="!controlsEnabled"
            @click="selectMode('volume')"
          >
            体积
          </button>
          <button
            class="mode-tab"
            :class="{ active: mode === 'slice' }"
            data-test="mode-slice"
            :disabled="!controlsEnabled"
            @click="selectMode('slice')"
          >
            切片
          </button>
          <button
            class="mode-tab"
            :class="{ active: mode === 'contour' }"
            data-test="mode-contour"
            :disabled="!controlsEnabled"
            @click="selectMode('contour')"
          >
            等值线
          </button>
          <button
            class="icon-button"
            data-test="reset-view"
            title="重置视角"
            aria-label="重置视角"
            :disabled="!controlsEnabled"
            @click="onResetView"
          >
            <Aim />
          </button>
        </div>

        <div class="control-row">
          <label class="control-label" for="slice-coordinate">切片位置 Z</label>
          <input
            id="slice-coordinate"
            v-model.number="sliceZ"
            class="opacity-slider"
            data-test="slice-coordinate"
            type="range"
            min="0"
            max="1"
            step="0.01"
            :disabled="!controlsEnabled"
            @input="applySliceCoordinate"
          />
          <span class="control-value">{{ sliceZ.toFixed(2) }}</span>
        </div>

        <div class="control-row">
          <label class="control-label" for="contour-value">等值面值</label>
          <input
            id="contour-value"
            v-model="contourValueInput"
            class="number-input"
            data-test="contour-value"
            type="number"
            :disabled="!controlsEnabled"
            @change="applyContourValue"
          />
          <button class="link-button" data-test="contour-apply" :disabled="!controlsEnabled" @click="applyContourValue">
            应用等值面
          </button>
          <span class="style-note">留空使用数据值域中点</span>
        </div>

        <div class="control-row">
          <label class="control-label" for="filter-min">滤波 min</label>
          <input
            id="filter-min"
            v-model="filterMinInput"
            class="number-input"
            data-test="filter-min"
            type="number"
            :disabled="!controlsEnabled"
          />
          <label class="control-label" for="filter-max">max</label>
          <input
            id="filter-max"
            v-model="filterMaxInput"
            class="number-input"
            data-test="filter-max"
            type="number"
            :disabled="!controlsEnabled"
          />
          <button class="link-button" data-test="filter-apply" :disabled="!controlsEnabled" @click="applyFilter">
            应用滤波
          </button>
          <span v-if="filterError" class="control-error" data-test="filter-error">{{ filterError }}</span>
        </div>

        <div class="control-row">
          <label class="control-label" for="opacity-slider">不透明度</label>
          <input
            id="opacity-slider"
            v-model.number="opacity"
            class="opacity-slider"
            data-test="opacity-slider"
            type="range"
            min="0"
            max="1"
            step="0.05"
            :disabled="!controlsEnabled"
            @input="onOpacityInput"
          />
          <span class="control-value">{{ opacity.toFixed(2) }}</span>
        </div>

        <div class="control-row style-toggles">
          <label class="toggle-label">
            <input data-test="lighting-toggle" type="checkbox" checked disabled />
            光照
          </label>
          <label class="toggle-label">
            <input data-test="gradient-opacity-toggle" type="checkbox" checked disabled />
            渐变透明度
          </label>
          <span class="style-note" data-test="style-note">
            光照与渐变透明度由渲染器初始化时固定启用（协议 v1 无运行时调整命令）
          </span>
        </div>

        <div class="control-row">
          <label class="toggle-label">
            <input
              v-model="auxVisible"
              data-test="aux-points-toggle"
              type="checkbox"
              :disabled="!auxPoints || !frameReady"
              @change="pushPointLayer"
            />
            辅助采样点
          </label>
          <span class="style-note">默认关闭；仅作数据分布参考</span>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.native-volume-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.panel-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.panel-title {
  margin: 0;
  font-size: 15px;
}

.volume-phase {
  font-size: 12px;
  color: var(--gmp-accent);
  font-family: ui-monospace, monospace;
}

.truth-labels {
  margin: 0;
  padding: 8px 12px;
  list-style: none;
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  background: var(--gmp-bg-soft);
  font-size: 12px;
  color: var(--gmp-text-dim);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.panel-note {
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.panel-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
}

.asset-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.primary-button {
  border: 1px solid var(--gmp-accent);
  background: var(--gmp-accent);
  color: #0b0f14;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.primary-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.link-button {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  border-radius: 8px;
  padding: 8px 14px;
  font-size: 12px;
  cursor: pointer;
}

.link-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.asset-identity {
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 12px;
  font-family: ui-monospace, monospace;
  color: var(--gmp-text-dim);
  display: flex;
  flex-direction: column;
  gap: 4px;
  word-break: break-all;
}

.volume-controls {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.mode-tabs {
  display: flex;
  gap: 8px;
  align-items: center;
}

.mode-tab {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
}

.mode-tab.active {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.mode-tab:disabled,
.icon-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.icon-button {
  margin-left: auto;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text-dim);
  border-radius: 8px;
  cursor: pointer;
}

.icon-button svg {
  width: 16px;
  height: 16px;
}

.control-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.control-label {
  min-width: 52px;
}

.number-input {
  width: 110px;
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: inherit;
  border-radius: 6px;
  padding: 5px 8px;
}

.opacity-slider {
  flex: 1;
  min-width: 160px;
  accent-color: var(--gmp-accent);
}

.control-value {
  font-family: ui-monospace, monospace;
}

.control-error {
  color: #ef9a9a;
}

.toggle-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.toggle-label input:disabled {
  cursor: not-allowed;
}

.style-note {
  font-size: 11px;
  color: var(--gmp-text-dim);
  opacity: 0.8;
}
</style>

<script lang="ts">
import type {
  ExportRecord,
  PointLayerStyle,
  RenderAssetRecord,
  RenderCapability,
  SliceAnalysisResponse,
  SliceAxis,
} from '../../api/types'

// 面板的数据层以回调注入：候选成果与内置电阻率共用本面板，
// 各自绑定 client.ts 中对应的 capability/create/fetch 函数。
// v0.7.0 第二批 Task 11：剖面分析/导出经 RenderAsset 统一 API（三来源共用），
// 签名与 SliceAnalysisPanel 的 SliceAnalysisApi 结构化一致，api 直接透传。
export interface NativeVolumeRenderApi {
  fetchCapability: () => Promise<RenderCapability>
  fetchAsset: () => Promise<RenderAssetRecord>
  createAsset: (retryFailed: boolean) => Promise<RenderAssetRecord>
  fetchSliceAnalysis: (
    assetId: string,
    axis: SliceAxis,
    index: number,
  ) => Promise<SliceAnalysisResponse>
  createSliceExport: (
    assetId: string,
    axis: SliceAxis,
    index: number,
    png: Blob,
  ) => Promise<ExportRecord>
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
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError } from '../../api/client'
import type { PointLayerPayload, RenderIdentity } from '../../api/types'
import SuperMapVolumeFrame from './SuperMapVolumeFrame.vue'
import VolumeRenderToolbar from './VolumeRenderToolbar.vue'
import OrthogonalSliceControls from './OrthogonalSliceControls.vue'
import type { SliceAxisMeta } from './OrthogonalSliceControls.vue'
import SliceAnalysisPanel from './SliceAnalysisPanel.vue'
import { buildColorStops } from './renderTransferFunctions'
import type { RenderPaletteId, RenderScale } from './renderTransferFunctions'
import type { RenderStateV2 } from './renderProtocol'

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

const auxVisible = ref(false)

// ---------------------------------------------------------------------------
// v0.7.0 第二批 Task 11：完整 v2 渲染状态编排
// renderState 是唯一事实源；revision 1 由 INIT 消费，后续 APPLY 从 2 起单调
// 递增。slice 模式必须携带权威 slice 载荷（app.js 硬要求）：剖面响应到达前
// 绝不推送 slice 模式状态。色带/标度由工具栏受控提升，与剖面热力图共享。
// ---------------------------------------------------------------------------
const renderState = ref<RenderStateV2>(initialRenderState())
const nextRevision = ref(2)
const activePalette = ref<RenderPaletteId>('viridis')
const activeScale = ref<RenderScale>('linear')
const axesMeta = ref<Record<SliceAxis, SliceAxisMeta> | null>(null)
const sliceTarget = ref<{ axis: SliceAxis; index: number } | null>(null)
const contourInput = ref<string | number>('')
let sliceDebounce: ReturnType<typeof setTimeout> | null = null

function formatError(e: unknown): string {
  return e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
}

// 渲染默认值来自 capability.render_profile（色带/标度经纯函数展开）；
// 缺省（不支持/点云专用初始化）使用固定安全默认
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

function initialRenderState(): RenderStateV2 {
  const defaults = profileDefaults()
  return {
    revision: 1,
    mode: 'volume',
    filter: { min: defaults.range[0], max: defaults.range[1] },
    opacity: defaults.opacity,
    colorTransferFunction: defaults.stops,
    lighting: defaults.lighting,
    gradientOpacity: defaults.gradientOpacity,
    boundingBox: defaults.boundingBox,
  }
}

function clearSliceDebounce() {
  if (sliceDebounce !== null) {
    clearTimeout(sliceDebounce)
    sliceDebounce = null
  }
}

function resetRenderState() {
  clearSliceDebounce()
  renderState.value = initialRenderState()
  nextRevision.value = 2
  axesMeta.value = null
  sliceTarget.value = null
  contourInput.value = ''
}

// 能力（重）加载：渲染状态/色带/标度/剖面上下文全部回默认
watch(
  () => capability.value,
  () => {
    const profile = capability.value?.render_profile ?? null
    activePalette.value = profile?.default_palette ?? 'viridis'
    activeScale.value = profile?.default_scale ?? 'linear'
    resetRenderState()
  },
  { immediate: true },
)

// 资产身份切换：剖面目标/轴元数据清空，渲染状态回 profile 默认，revision 重置
watch(
  () => asset.value?.id ?? null,
  (id, prev) => {
    if (id === prev) return
    resetRenderState()
  },
)

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
  const initialState = JSON.parse(JSON.stringify(renderState.value)) as RenderStateV2
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

// ---------------------------------------------------------------------------
// 渲染状态推送与控件事件
// ---------------------------------------------------------------------------

function pushRenderState() {
  if (!controlsEnabled.value) return
  const current = renderState.value
  // slice 模式必须携带权威 slice 载荷；剖面响应到达前不推送（app.js 硬失败）
  if (current.mode === 'slice' && !current.slice) return
  const next: RenderStateV2 = { ...current, revision: nextRevision.value }
  if (frameRef.value?.applyRenderState(next)) {
    renderState.value = next
    nextRevision.value += 1
  }
}

function onToolbarUpdate(next: RenderStateV2) {
  renderState.value = next
  pushRenderState()
}

function onPaletteUpdate(palette: RenderPaletteId) {
  activePalette.value = palette
}

function onScaleUpdate(scale: RenderScale) {
  activeScale.value = scale
}

// 模式切换：进入 slice 时确立剖面目标（有元数据用 z 中位索引，否则 z/0 引导）；
// 离开时清空目标（控件与分析面板随之卸载）
watch(
  () => renderState.value.mode,
  (mode, prev) => {
    if (mode === prev) return
    clearSliceDebounce()
    if (mode === 'slice') {
      const axes = axesMeta.value
      sliceTarget.value = axes
        ? { axis: 'z', index: Math.floor((axes.z.length - 1) / 2) }
        : { axis: 'z', index: 0 }
    } else {
      sliceTarget.value = null
    }
  },
)

function onAxesMetaLoaded(axes: Record<SliceAxis, SliceAxisMeta>) {
  axesMeta.value = axes
  sliceTarget.value = { axis: 'z', index: Math.floor((axes.z.length - 1) / 2) }
}

// 滑块拖动 150ms 防抖；轴切换/步进/松手 commit 立即生效
function onSliceChange(payload: { axis: SliceAxis; index: number; coordinate: number }) {
  clearSliceDebounce()
  sliceDebounce = setTimeout(() => {
    sliceDebounce = null
    sliceTarget.value = { axis: payload.axis, index: payload.index }
  }, 150)
}

function onSliceCommit(payload: { axis: SliceAxis; index: number }) {
  clearSliceDebounce()
  sliceTarget.value = { axis: payload.axis, index: payload.index }
}

// 3D slice 状态只来自权威剖面响应（index/coordinate/sdk_relative_position）
function onAnalysisLoaded(response: SliceAnalysisResponse) {
  if (renderState.value.mode !== 'slice') return
  const s = response.slice
  renderState.value = {
    ...renderState.value,
    mode: 'slice',
    slice: {
      axis: s.fixed_axis,
      index: s.index,
      coordinate: s.coordinate,
      relativePosition: s.sdk_relative_position,
    },
  }
  pushRenderState()
}

// 等值面输入只在 contour 模式显示；留空回落值域中点（不带 contourValue）。
// 注意 type="number" 输入的 v-model 会被 Vue 自动转型为 number，这里统一按字符串处理
function applyContourValue() {
  const raw = String(contourInput.value ?? '').trim()
  const next = JSON.parse(JSON.stringify(renderState.value)) as RenderStateV2
  next.mode = 'contour'
  if (raw === '') {
    delete next.contourValue
  } else {
    const value = Number(raw)
    if (!Number.isFinite(value)) return
    next.contourValue = value
  }
  renderState.value = next
  pushRenderState()
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

      <!-- 体积控件：常驻工具栏 + 模式专属控件；只在 rendered 后启用 -->
      <div class="volume-controls" data-test="volume-controls">
        <VolumeRenderToolbar
          :model-value="renderState"
          :profile="capability.render_profile ?? null"
          :palette="activePalette"
          :scale="activeScale"
          :enabled="controlsEnabled"
          @update:model-value="onToolbarUpdate"
          @update:palette="onPaletteUpdate"
          @update:scale="onScaleUpdate"
          @reset-view="onResetView"
        />

        <!-- 等值面输入只在 contour 模式显示 -->
        <div v-if="renderState.mode === 'contour'" class="control-row" data-test="contour-controls">
          <label class="control-label" for="contour-value">等值面值</label>
          <input
            id="contour-value"
            v-model="contourInput"
            class="number-input"
            data-test="contour-value"
            type="number"
            :disabled="!controlsEnabled"
            @change="applyContourValue"
          />
          <button
            class="link-button"
            data-test="contour-apply"
            :disabled="!controlsEnabled"
            @click="applyContourValue"
          >
            应用等值面
          </button>
          <span class="style-note">留空使用数据值域中点</span>
        </div>

        <OrthogonalSliceControls
          v-if="renderState.mode === 'slice' && axesMeta"
          :mode="renderState.mode"
          :axes="axesMeta"
          @change="onSliceChange"
          @commit="onSliceCommit"
        />
        <SliceAnalysisPanel
          v-if="renderState.mode === 'slice' && asset && asset.status === 'ready'"
          :api="api"
          :asset-id="asset.id"
          :target="sliceTarget"
          :axes-meta="axesMeta"
          :palette="activePalette"
          :scale="activeScale"
          :enabled="controlsEnabled"
          @analysis-loaded="onAnalysisLoaded"
          @axes-meta-loaded="onAxesMetaLoaded"
        />

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

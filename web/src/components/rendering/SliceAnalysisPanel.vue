<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  ExportRecord,
  SliceAnalysisResponse,
  SliceAxis,
} from '../../api/types'
import type { SliceAxisMeta } from './OrthogonalSliceControls.vue'
import SliceHeatmap from './SliceHeatmap.vue'

// v0.7.0 Batch 2 Task 10：剖面分析面板（设计 §7.3）。
// 最新请求获胜：每个请求捕获 {assetId, axis, index, sequence}，成功/失败/
// finally 都只更新仍为当前目标的状态。首次进入切片模式先以 z/0 引导
// （仅分析用途），拿到三轴元数据后立即请求 z/floor((len-1)/2)，之后才
// 显示热力图并上报 analysis-loaded；后续切轴复用已加载元数据。

export interface SliceAnalysisApi {
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

const props = withDefaults(
  defineProps<{
    api: SliceAnalysisApi
    assetId: string
    axisMeta?: Record<SliceAxis, SliceAxisMeta> | null
    enabled?: boolean
  }>(),
  { axisMeta: null, enabled: true },
)

const emit = defineEmits<{
  'analysis-loaded': [response: SliceAnalysisResponse]
}>()

const AXES: SliceAxis[] = ['x', 'y', 'z']

const active = ref(false)
const axis = ref<SliceAxis>('z')
const index = ref(0)
const axesMeta = ref<Record<SliceAxis, SliceAxisMeta> | null>(props.axisMeta)
const analysis = ref<SliceAnalysisResponse | null>(null)
const loadError = ref<string | null>(null)
const exporting = ref(false)
const exportError = ref<string | null>(null)
const heatmapRef = ref<InstanceType<typeof SliceHeatmap> | null>(null)

let requestSeq = 0

const statistics = computed(() => analysis.value?.statistics ?? null)
const coordinateLabel = computed(() => {
  if (!analysis.value) return ''
  const s = analysis.value.slice
  return `${s.fixed_axis.toUpperCase()} = ${s.coordinate} ${analysis.value.axes[s.fixed_axis].unit}`
})
const currentTargetMatches = computed(
  () =>
    analysis.value !== null &&
    analysis.value.asset_identity.asset_id === props.assetId &&
    analysis.value.slice.fixed_axis === axis.value &&
    analysis.value.slice.index === index.value,
)
const exportEnabled = computed(
  () => props.enabled && currentTargetMatches.value && !exporting.value,
)

function axisLengthOf(name: SliceAxis): number {
  return axesMeta.value?.[name]?.length ?? 0
}

async function request(targetAxis: SliceAxis, targetIndex: number): Promise<void> {
  const seq = ++requestSeq
  const target = { assetId: props.assetId, axis: targetAxis, index: targetIndex }
  loadError.value = null
  try {
    const response = await props.api.fetchSliceAnalysis(target.assetId, target.axis, target.index)
    if (seq !== requestSeq) return
    analysis.value = response
    loadError.value = null
    emit('analysis-loaded', response)
  } catch (error) {
    if (seq !== requestSeq) return
    loadError.value = error instanceof Error ? error.message : String(error)
  }
}

async function enterSliceMode() {
  active.value = true
  if (!axesMeta.value) {
    // 引导请求：仅用于拿三轴元数据；面板保持加载语义
    const boot = await props.api.fetchSliceAnalysis(props.assetId, 'z', 0)
    axesMeta.value = {
      x: boot.axes.x,
      y: boot.axes.y,
      z: boot.axes.z,
    }
  }
  axis.value = 'z'
  index.value = Math.floor((axisLengthOf('z') - 1) / 2)
  await request(axis.value, index.value)
}

async function selectAxis(next: SliceAxis) {
  axis.value = next
  index.value = Math.floor((axisLengthOf(next) - 1) / 2)
  await request(next, index.value)
}

watch(
  () => props.assetId,
  () => {
    // 资产切换：取消旧请求、清空剖面与错误状态，等待下一次显式进入
    requestSeq += 1
    active.value = false
    analysis.value = null
    loadError.value = null
    exportError.value = null
    axesMeta.value = props.axisMeta
  },
)

async function retry() {
  await request(axis.value, index.value)
}

async function exportSlice() {
  if (!exportEnabled.value) return
  exporting.value = true
  exportError.value = null
  try {
    const png = await heatmapRef.value!.capturePng()
    const record = await props.api.createSliceExport(props.assetId, axis.value, index.value, png)
    window.location.assign(`/api/exports/${record.id}/download`)
  } catch (error) {
    exportError.value = error instanceof Error ? error.message : String(error)
  } finally {
    exporting.value = false
  }
}

function statText(value: number | null, digits = 4): string {
  if (value === null) return '—'
  return String(Number(value.toFixed(digits)))
}
</script>

<template>
  <div class="slice-analysis" data-test="slice-analysis">
    <el-button
      v-if="!active"
      size="small"
      type="primary"
      :disabled="!enabled"
      data-test="enter-slice-mode"
      @click="enterSliceMode"
    >
      进入切片分析
    </el-button>

    <template v-else>
      <div class="analysis-axes" data-test="analysis-axis-segment">
        <el-radio-group v-model="axis" size="small">
          <el-radio-button
            v-for="name in AXES"
            :key="name"
            :value="name"
            :data-test="`axis-${name}`"
            @click="selectAxis(name)"
          >
            {{ name.toUpperCase() }}
          </el-radio-button>
        </el-radio-group>
        <span class="coordinate-label" data-test="slice-coordinate-label">{{ coordinateLabel }}</span>
      </div>

      <div v-if="loadError" class="analysis-error" data-test="slice-error">
        剖面加载失败：{{ loadError }}
        <el-button size="small" text data-test="slice-retry" @click="retry">重试</el-button>
      </div>

      <template v-if="analysis && !loadError">
        <div class="analysis-body">
          <SliceHeatmap
            ref="heatmapRef"
            :analysis="analysis"
            palette="viridis"
            scale="linear"
          />
          <div class="analysis-stats" data-test="slice-statistics">
            <p data-test="slice-valid-count">
              有效 {{ statistics?.valid_count }} / NoData {{ statistics?.nodata_count }}（共
              {{ statistics?.total_count }}）
            </p>
            <p>最小 {{ statText(statistics?.min ?? null) }} · 最大 {{ statText(statistics?.max ?? null) }} {{ analysis.property.unit }}</p>
            <p>均值 {{ statText(statistics?.mean ?? null) }} · 总体标准差 {{ statText(statistics?.std_population ?? null) }}</p>
            <p>
              P10 {{ statText(statistics?.p10 ?? null) }} · P50
              {{ statText(statistics?.p50 ?? null) }} · P90 {{ statText(statistics?.p90 ?? null) }}
            </p>
            <el-button
              size="small"
              type="primary"
              :disabled="!exportEnabled"
              :loading="exporting"
              data-test="export-slice"
              @click="exportSlice"
            >
              下载剖面分析包
            </el-button>
            <p v-if="exportError" class="analysis-error" data-test="export-error">{{ exportError }}</p>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.slice-analysis {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.analysis-axes {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.coordinate-label {
  color: var(--gmp-text-dim);
  font-size: 12px;
}
.analysis-body {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(240px, 1fr);
  gap: 16px;
  align-items: start;
}
@media (max-width: 1100px) {
  .analysis-body {
    grid-template-columns: 1fr;
  }
}
.analysis-stats {
  font-size: 13px;
  line-height: 1.7;
}
.analysis-error {
  color: var(--el-color-danger);
  font-size: 13px;
}
</style>

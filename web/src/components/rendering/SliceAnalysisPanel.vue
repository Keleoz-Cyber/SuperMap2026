<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  ExportRecord,
  RenderPaletteId,
  RenderScale,
  SliceAnalysisResponse,
  SliceAxis,
} from '../../api/types'
import type { SliceAxisMeta } from './OrthogonalSliceControls.vue'
import SliceHeatmap from './SliceHeatmap.vue'

// v0.7.0 Batch 2 Task 10/11：剖面分析面板（目标驱动 + 最新请求获胜）。
// 轴/索引选择由 OrthogonalSliceControls（父级）持有；本组件只负责请求
// 生命周期、统计展示、导出与响应竞态控制（设计 §7.1）。
// 首次进入切片模式且无轴元数据时：先以 z/0 引导（仅分析用途），上报
// axes-meta-loaded，父级随后把目标设为 z/floor((len-1)/2)，本组件再请求
// 并展示；每个请求捕获 {assetId, axis, index, sequence}，成功/失败/finally
// 都只更新仍为当前目标的状态。

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
    target: { axis: SliceAxis; index: number } | null
    axesMeta?: Record<SliceAxis, SliceAxisMeta> | null
    palette?: RenderPaletteId
    scale?: RenderScale
    enabled?: boolean
    display?: 'panel' | 'controller'
  }>(),
  {
    axesMeta: null,
    palette: 'viridis',
    scale: 'linear',
    enabled: true,
    display: 'panel',
  },
)

const emit = defineEmits<{
  'analysis-loaded': [response: SliceAnalysisResponse]
  'axes-meta-loaded': [axes: Record<SliceAxis, SliceAxisMeta>]
}>()

const bootstrapping = ref(false)
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
    props.target !== null &&
    analysis.value.asset_identity.asset_id === props.assetId &&
    analysis.value.slice.fixed_axis === props.target.axis &&
    analysis.value.slice.index === props.target.index,
)
const exportEnabled = computed(
  () => props.enabled && currentTargetMatches.value && !exporting.value,
)

async function bootstrapIfNeeded(): Promise<boolean> {
  if (props.axesMeta || props.target === null) return true
  if (bootstrapping.value) return false
  bootstrapping.value = true
  try {
    // 引导请求：仅用于拿三轴元数据；统计区保持加载语义
    const boot = await props.api.fetchSliceAnalysis(props.assetId, 'z', 0)
    emit('axes-meta-loaded', { x: boot.axes.x, y: boot.axes.y, z: boot.axes.z })
    return true
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : String(error)
    return false
  } finally {
    bootstrapping.value = false
  }
}

async function request(targetAxis: SliceAxis, targetIndex: number): Promise<void> {
  const seq = ++requestSeq
  const target = { assetId: props.assetId, axis: targetAxis, index: targetIndex }
  loadError.value = null
  try {
    const response = await props.api.fetchSliceAnalysis(target.assetId, target.axis, target.index)
    if (seq !== requestSeq) return
    if (
      props.target === null ||
      props.target.axis !== target.axis ||
      props.target.index !== target.index
    ) {
      return
    }
    analysis.value = response
    loadError.value = null
    emit('analysis-loaded', response)
  } catch (error) {
    if (seq !== requestSeq) return
    if (
      props.target === null ||
      props.target.axis !== target.axis ||
      props.target.index !== target.index
    ) {
      return
    }
    loadError.value = error instanceof Error ? error.message : String(error)
  }
}

watch(
  () => [props.assetId, props.target?.axis, props.target?.index] as const,
  async () => {
    if (props.target === null) {
      requestSeq += 1
      analysis.value = null
      loadError.value = null
      return
    }
    const ready = await bootstrapIfNeeded()
    if (ready && props.target !== null) {
      await request(props.target.axis, props.target.index)
    }
  },
  { immediate: true },
)

watch(
  () => props.assetId,
  () => {
    requestSeq += 1
    analysis.value = null
    loadError.value = null
    exportError.value = null
  },
)

async function retry() {
  if (props.target === null) return
  const ready = await bootstrapIfNeeded()
  if (ready) await request(props.target.axis, props.target.index)
}

async function exportSlice() {
  if (!exportEnabled.value || props.target === null) return
  exporting.value = true
  exportError.value = null
  try {
    const png = await heatmapRef.value!.capturePng()
    const record = await props.api.createSliceExport(
      props.assetId,
      props.target.axis,
      props.target.index,
      png,
    )
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
  <span v-if="display === 'controller'" hidden data-test="slice-analysis-controller" />
  <div v-else class="slice-analysis" data-test="slice-analysis">
    <div v-if="loadError" class="analysis-error" data-test="slice-error">
      剖面加载失败：{{ loadError }}
      <el-button size="small" text data-test="slice-retry" @click="retry">重试</el-button>
    </div>

    <template v-if="analysis && !loadError">
      <div class="analysis-head">
        <span class="coordinate-label" data-test="slice-coordinate-label">{{ coordinateLabel }}</span>
      </div>
      <div class="analysis-body">
        <SliceHeatmap
          ref="heatmapRef"
          :analysis="analysis"
          :palette="palette"
          :scale="scale"
        />
        <div class="analysis-stats" data-test="slice-statistics">
          <p data-test="slice-valid-count">
            有效 {{ statistics?.valid_count }} / NoData {{ statistics?.nodata_count }}（共
            {{ statistics?.total_count }}）
          </p>
          <p>
            最小 {{ statText(statistics?.min ?? null) }} · 最大
            {{ statText(statistics?.max ?? null) }} {{ analysis.property.unit }}
          </p>
          <p>
            均值 {{ statText(statistics?.mean ?? null) }} · 总体标准差
            {{ statText(statistics?.std_population ?? null) }}
          </p>
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
  </div>
</template>

<style scoped>
.slice-analysis {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.analysis-head {
  display: flex;
  align-items: center;
  gap: 12px;
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

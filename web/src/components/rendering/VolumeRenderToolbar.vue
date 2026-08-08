<script setup lang="ts">
import { computed, reactive } from 'vue'
import { RefreshLeft } from '@element-plus/icons-vue'
import {
  PALETTES,
  PALETTE_IDS,
  buildColorStops,
  type RenderPaletteId,
  type RenderScale,
} from './renderTransferFunctions'
import type { RenderProfile } from '../../api/types'
import type { RenderStateV2 } from './renderProtocol'

// v0.7.0 Batch 2 Task 9：常驻渲染工具栏（设计 §7.2）。
// 模式/色带/标度/滤波/不透明度/光照/渐变透明度/包围盒/重置视角常驻；
// 每次合法修改都发射**完整克隆状态**（revision 由编排层递增）；重置视角
// 只发 reset-view 事件，绝不改渲染状态。

const props = withDefaults(
  defineProps<{
    modelValue: RenderStateV2
    profile: RenderProfile | null
    enabled?: boolean
    // Task 11：色带/标度可由面板提升为受控状态（与剖面热力图共享同一份选择）；
    // 不传时回退 profile 默认（保持旧用法兼容）
    palette?: RenderPaletteId
    scale?: RenderScale
  }>(),
  { enabled: true, palette: undefined, scale: undefined },
)

const emit = defineEmits<{
  'update:modelValue': [state: RenderStateV2]
  'update:palette': [palette: RenderPaletteId]
  'update:scale': [scale: RenderScale]
  'reset-view': []
}>()

const paletteIds = PALETTE_IDS
const paletteColors = PALETTES

const state = computed(() => props.modelValue)
const logAvailable = computed(() => props.profile?.log_available !== false)

function cloneWith(mutate: (next: RenderStateV2) => void) {
  if (!props.enabled) return
  const next: RenderStateV2 = JSON.parse(JSON.stringify(state.value))
  mutate(next)
  emit('update:modelValue', next)
}

const currentPaletteId = computed<RenderPaletteId>({
  get: () => props.palette ?? props.profile?.default_palette ?? 'viridis',
  set: (palette) => {
    emit('update:palette', palette)
    cloneWith((next) => {
      next.colorTransferFunction = buildColorStops(
        palette,
        currentScale.value,
        [next.filter.min, next.filter.max],
      )
    })
  },
})

const currentScale = computed<RenderScale>({
  get: () => props.scale ?? props.profile?.default_scale ?? 'linear',
  set: (scale) => {
    if (scale === 'log' && !logAvailable.value) return
    emit('update:scale', scale)
    cloneWith((next) => {
      next.colorTransferFunction = buildColorStops(
        currentPaletteId.value,
        scale,
        [next.filter.min, next.filter.max],
      )
    })
  },
})

const paletteModel = computed<string>({
  get: () => currentPaletteId.value,
  set: (value) => {
    currentPaletteId.value = value as RenderPaletteId
  },
})

const scaleModel = computed<string>({
  get: () => currentScale.value,
  set: (value) => {
    currentScale.value = value as RenderScale
  },
})

const modeModel = computed<string>({
  get: () => state.value.mode,
  set: (value) =>
    cloneWith((next) => {
      next.mode = value as RenderStateV2['mode']
    }),
})

const opacityModel = computed<number>({
  get: () => state.value.opacity,
  set: (value) =>
    cloneWith((next) => {
      next.opacity = value
    }),
})

const lightingModel = computed<boolean>({
  get: () => state.value.lighting,
  set: (value) =>
    cloneWith((next) => {
      next.lighting = value
    }),
})

const gradientModel = computed<boolean>({
  get: () => state.value.gradientOpacity,
  set: (value) =>
    cloneWith((next) => {
      next.gradientOpacity = value
    }),
})

const boundingBoxModel = computed<boolean>({
  get: () => state.value.boundingBox,
  set: (value) =>
    cloneWith((next) => {
      next.boundingBox = value
    }),
})

const filterDraft = reactive({ min: '', max: '' })

function applyFilter() {
  // 单侧留空回退为当前状态值；两侧都空或非法或退化区间（min >= max）时不发射；
  // min == max 会让 buildColorStops 的空值域校验抛 VALUE_RANGE_INVALID，必须先拦截
  const minInput = filterDraft.min.trim()
  const maxInput = filterDraft.max.trim()
  if (minInput === '' && maxInput === '') return
  const min = minInput === '' ? state.value.filter.min : Number(minInput)
  const max = maxInput === '' ? state.value.filter.max : Number(maxInput)
  if (!Number.isFinite(min) || !Number.isFinite(max) || min >= max) return
  cloneWith((next) => {
    next.filter = { min, max }
    next.colorTransferFunction = buildColorStops(currentPaletteId.value, currentScale.value, [min, max])
  })
}

function onResetView() {
  emit('reset-view')
}
</script>

<template>
  <div class="render-toolbar" data-test="render-toolbar">
    <div class="toolbar-row">
      <el-radio-group
        v-model="modeModel"
        size="small"
        :disabled="!enabled"
        data-test="mode-segment"
      >
        <el-radio-button value="volume" data-test="mode-volume">体积</el-radio-button>
        <el-radio-button value="slice" data-test="mode-slice">切片</el-radio-button>
        <el-radio-button value="contour" data-test="mode-contour">等值面</el-radio-button>
      </el-radio-group>

      <el-select
        v-model="paletteModel"
        size="small"
        class="palette-select"
        :disabled="!enabled"
        data-test="palette-select"
      >
        <el-option v-for="id in paletteIds" :key="id" :value="id" :label="id">
          <span class="palette-option">
            <span
              class="palette-swatch"
              :data-test="`palette-swatch-${id}`"
              :style="{
                background: `linear-gradient(to right, ${paletteColors[id].join(', ')})`,
              }"
            />
            <span>{{ id }}</span>
          </span>
        </el-option>
      </el-select>

      <el-radio-group
        v-model="scaleModel"
        size="small"
        :disabled="!enabled"
        data-test="scale-segment"
      >
        <el-radio-button value="linear" data-test="linear-scale">线性</el-radio-button>
        <el-tooltip
          :disabled="logAvailable"
          content="权威有效值不全为正，对数不可用"
          placement="top"
        >
          <span>
            <el-radio-button value="log" :disabled="!logAvailable" data-test="log-scale">
              对数
            </el-radio-button>
          </span>
        </el-tooltip>
      </el-radio-group>

      <el-tooltip content="重置视角" placement="top">
        <el-button
          size="small"
          :icon="RefreshLeft"
          circle
          :disabled="!enabled"
          data-test="reset-view"
          aria-label="重置视角"
          @click="onResetView"
        />
      </el-tooltip>
    </div>

    <div class="toolbar-row">
      <label class="control-label" for="filter-min-input">滤波</label>
      <el-input
        v-model="filterDraft.min"
        size="small"
        class="filter-input"
        placeholder="min"
        :disabled="!enabled"
        data-test="filter-min"
        id="filter-min-input"
        name="filter_min"
        autocomplete="off"
      />
      <span class="control-sep">~</span>
      <el-input
        v-model="filterDraft.max"
        size="small"
        class="filter-input"
        placeholder="max"
        :disabled="!enabled"
        data-test="filter-max"
        id="filter-max-input"
        name="filter_max"
        autocomplete="off"
      />
      <el-button size="small" :disabled="!enabled" data-test="filter-apply" @click="applyFilter">
        应用
      </el-button>

      <span class="control-label">不透明度</span>
      <el-slider
        v-model="opacityModel"
        class="opacity-slider"
        :min="0"
        :max="1"
        :step="0.01"
        :disabled="!enabled"
        data-test="opacity-slider"
      />

      <el-checkbox
        v-model="lightingModel"
        size="small"
        :disabled="!enabled"
        data-test="lighting-toggle"
      >
        光照
      </el-checkbox>
      <el-checkbox
        v-model="gradientModel"
        size="small"
        :disabled="!enabled"
        data-test="gradient-opacity-toggle"
      >
        渐变透明度
      </el-checkbox>
      <el-checkbox
        v-model="boundingBoxModel"
        size="small"
        :disabled="!enabled"
        data-test="bounding-box-toggle"
      >
        包围盒
      </el-checkbox>
    </div>
  </div>
</template>

<style scoped>
.render-toolbar {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toolbar-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.palette-select {
  width: 180px;
}
.palette-option {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.palette-swatch {
  display: inline-block;
  width: 56px;
  height: 10px;
  border-radius: 2px;
}
.control-label {
  color: var(--gmp-text-dim);
  font-size: 12px;
}
.control-sep {
  color: var(--gmp-text-dim);
}
.filter-input {
  width: 90px;
}
.opacity-slider {
  width: 160px;
}
</style>

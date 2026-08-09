<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Algorithm, GridSpecPayload, ValidationSpecPayload } from '../../api/types'
import {
  combinationCount,
  parseNumberList,
  searchSpaceState,
  Z_SCALE_HINT,
  type ExperimentPreset,
} from './searchSpace'

export interface ParameterSubmit {
  algorithm: Algorithm
  search_mode: 'manual' | 'grid'
  parameters: Record<string, unknown>
  validation: ValidationSpecPayload
  grid: GridSpecPayload | null
}

const props = defineProps<{
  dimension: '2d' | '3d'
  submitting: boolean
  preset?: ExperimentPreset | null
  algorithmLock?: Algorithm | null
  zScaleLock?: number | null
  datasetLocked?: boolean
}>()
const emit = defineEmits<{
  (e: 'submit', payload: ParameterSubmit): void
  // v0.9.0：参数变化实时快照（与提交载荷同形），驱动候选摘要；不触发任何 API
  (e: 'change', payload: ParameterSubmit): void
}>()

const algorithm = ref<Algorithm>('idw')
const searchMode = ref<'manual' | 'grid'>('manual')

watch(
  () => props.algorithmLock,
  (val) => {
    if (val) algorithm.value = val
  },
  { immediate: true },
)

// IDW 手动参数
const idwPower = ref(2)
const idwNeighbors = ref(16)

// Kriging 手动参数
const krigingModel = ref<'spherical' | 'exponential' | 'gaussian'>('spherical')
const krigingMode = ref<'auto' | 'manual'>('auto')
const krigingNugget = ref(0)
const krigingSill = ref(1)
const krigingRange = ref(100)
const krigingNeighbors = ref(24)

// ---------------------------------------------------------------------------
// v0.8.0：DSI-like 离散平滑插值（工程近似，仅 3D，不等同 GOCAD DSI）。
// 可选值与后端 DSIParameters 合同一致；convergence_tolerance 与
// hard_constraints 是固定合同项，界面只读展示并随载荷原样提交。
// 后端 ContractModel extra=forbid：dsi_like 不携带 z_scale 等额外字段。
const DSI_INIT_POWER_OPTIONS = [1.5, 2, 3]
const DSI_CONNECTIVITY_OPTIONS = [6, 18, 26]
const DSI_SMOOTHING_OPTIONS = [0.25, 0.5, 0.75]
const DSI_ITERATION_OPTIONS = [25, 50]
const DSI_CONVERGENCE_TOLERANCE = 1e-4

// DSI-like 手动参数
const dsiInitPower = ref(2)
const dsiConnectivity = ref(6)
const dsiSmoothing = ref(0.5)
const dsiIterations = ref(25)

// DSI-like 网格候选（默认仅勾选合同默认值 → 1 组合）
const dsiGridInitPower = ref<number[]>([2])
const dsiGridConnectivity = ref<number[]>([6])
const dsiGridSmoothing = ref<number[]>([0.5])
const dsiGridIterations = ref<number[]>([25])

// 切入 dsi_like 时回到合同默认值，避免上一次选择的参数静默残留
watch(algorithm, (val) => {
  if (val !== 'dsi_like') return
  dsiInitPower.value = 2
  dsiConnectivity.value = 6
  dsiSmoothing.value = 0.5
  dsiIterations.value = 25
  dsiGridInitPower.value = [2]
  dsiGridConnectivity.value = [6]
  dsiGridSmoothing.value = [0.5]
  dsiGridIterations.value = [25]
})

// 网格搜索离散候选（逗号分隔输入）
const gridPower = ref(props.preset ? props.preset.idwGrid.power.join(', ') : '2')
const gridNeighbors = ref(props.preset ? props.preset.idwGrid.neighborCount.join(', ') : '8, 16')
const gridKrigingNeighbors = ref(
  props.preset ? props.preset.krigingGrid.neighborCount.join(', ') : '16, 24',
)
const gridModels = ref<Array<'spherical' | 'exponential' | 'gaussian'>>(
  props.preset ? [...props.preset.krigingGrid.models] : ['spherical'],
)

// z_scale 距离缩放实验参数（仅领域预设数据集显示；通用数据集不出现该控件）
const zScaleHint = Z_SCALE_HINT
const zScale = ref(props.preset?.zScaleManualDefault ?? 1)
const gridZScale = ref(props.preset ? props.preset.idwGrid.zScale.join(', ') : '')

watch(
  () => props.zScaleLock,
  (val) => {
    if (val !== null && val !== undefined) {
      zScale.value = val
      gridZScale.value = String(val)
    }
  },
  { immediate: true },
)

// 空间验证
const folds = ref(5)
const seed = ref(20260723)
const holdout = ref(0.2)

// 高级：自定义网格（默认自动）
const gridCustom = ref(false)
const gridNodes = ref(11)
const boundsText = ref<Array<{ min: number | null; max: number | null }>>([
  { min: null, max: null },
  { min: null, max: null },
  { min: null, max: null },
])

const gridParameters = computed<Record<string, unknown>>(() => {
  if (algorithm.value === 'dsi_like') {
    // 固定项以单元素列表随网格提交（后端 grid 合同要求全值为离散列表）
    return {
      init_power: dsiGridInitPower.value,
      neighbor_connectivity: dsiGridConnectivity.value,
      smoothing_strength: dsiGridSmoothing.value,
      max_iterations: dsiGridIterations.value,
      convergence_tolerance: [DSI_CONVERGENCE_TOLERANCE],
      hard_constraints: [true],
    }
  }
  const zScalePart = props.preset ? { z_scale: parseNumberList(gridZScale.value) ?? [] } : {}
  if (algorithm.value === 'idw') {
    return {
      power: parseNumberList(gridPower.value) ?? [],
      neighbor_count: parseNumberList(gridNeighbors.value) ?? [],
      ...zScalePart,
    }
  }
  return {
    variogram_model: gridModels.value,
    neighbor_count: parseNumberList(gridKrigingNeighbors.value) ?? [],
    ...zScalePart,
  }
})

const candidateCount = computed(() =>
  searchMode.value === 'manual' ? 1 : combinationCount(gridParameters.value, 'grid'),
)
const countState = computed(() => searchSpaceState(candidateCount.value))

const manualKrigingInvalid = computed(
  () =>
    algorithm.value === 'ordinary_kriging' &&
    krigingMode.value === 'manual' &&
    !(krigingSill.value > 0 && krigingRange.value > 0 && krigingNugget.value >= 0 && krigingSill.value > krigingNugget.value),
)

const manualZScaleInvalid = computed(
  () =>
    Boolean(props.preset) &&
    !(typeof zScale.value === 'number' && zScale.value > 0 && zScale.value <= 20),
)

const customGridInvalid = computed(() => {
  if (!gridCustom.value) return false
  const axes = props.dimension === '3d' ? 3 : 2
  if (!(gridNodes.value >= 2)) return true
  return boundsText.value.slice(0, axes).some(
    (b) => b.min === null || b.max === null || !(b.max > b.min),
  )
})

const canSubmit = computed(
  () =>
    !props.submitting &&
    countState.value !== 'blocked' &&
    !manualKrigingInvalid.value &&
    !manualZScaleInvalid.value &&
    !customGridInvalid.value,
)

function buildParameters(): Record<string, unknown> {
  if (searchMode.value === 'grid') return gridParameters.value
  if (algorithm.value === 'dsi_like') {
    return {
      init_power: dsiInitPower.value,
      neighbor_connectivity: dsiConnectivity.value,
      smoothing_strength: dsiSmoothing.value,
      max_iterations: dsiIterations.value,
      convergence_tolerance: DSI_CONVERGENCE_TOLERANCE,
      hard_constraints: true,
    }
  }
  const zScalePart = props.preset ? { z_scale: zScale.value } : {}
  if (algorithm.value === 'idw') {
    return { power: idwPower.value, neighbor_count: idwNeighbors.value, ...zScalePart }
  }
  const params: Record<string, unknown> = {
    variogram_model: krigingModel.value,
    variogram_mode: krigingMode.value,
    neighbor_count: krigingNeighbors.value,
    ...zScalePart,
  }
  if (krigingMode.value === 'manual') {
    params.nugget = krigingNugget.value
    params.sill = krigingSill.value
    params.range = krigingRange.value
  }
  return params
}

function buildGrid(): GridSpecPayload | null {
  if (!gridCustom.value) return null
  const axes = props.dimension === '3d' ? 3 : 2
  const bounds = boundsText.value
    .slice(0, axes)
    .map((b) => [Number(b.min), Number(b.max)] as [number, number])
  const resolution = bounds.map(([lo, hi]) => (hi - lo) / (gridNodes.value - 1))
  return { bounds, resolution }
}

function submit() {
  emit('submit', {
    algorithm: algorithm.value,
    search_mode: searchMode.value,
    parameters: buildParameters(),
    validation: {
      method: 'spatial_kfold',
      folds: folds.value,
      seed: seed.value,
      holdout_fraction: holdout.value,
    },
    grid: buildGrid(),
  })
}

// 参数快照：任何参数/验证/网格变化后向父级同步（仅内存事件，无 API 副作用）
const payloadSnapshot = computed<ParameterSubmit>(() => ({
  algorithm: algorithm.value,
  search_mode: searchMode.value,
  parameters: buildParameters(),
  validation: {
    method: 'spatial_kfold',
    folds: folds.value,
    seed: seed.value,
    holdout_fraction: holdout.value,
  },
  grid: buildGrid(),
}))

watch(
  payloadSnapshot,
  (payload) => {
    emit('change', payload)
  },
  { immediate: true, deep: true },
)

const AXES = ['x', 'y', 'z'] as const
</script>

<template>
  <section class="editor" data-test="param-editor">
    <div class="editor-row">
      <span class="row-label">算法</span>
      <label class="radio">
        <input type="radio" name="algo" data-test="algo-idw" :checked="algorithm === 'idw'" :disabled="!!algorithmLock" @change="algorithm = 'idw'" />
        IDW（反距离加权）
      </label>
      <label class="radio">
        <input
          type="radio"
          name="algo"
          data-test="algo-kriging"
          :checked="algorithm === 'ordinary_kriging'"
          :disabled="!!algorithmLock"
          @change="algorithm = 'ordinary_kriging'"
        />
        普通克里金
      </label>
      <label class="radio">
        <input
          type="radio"
          name="algo"
          data-test="algo-dsi-like"
          :checked="algorithm === 'dsi_like'"
          :disabled="dimension !== '3d' || !!algorithmLock"
          @change="algorithm = 'dsi_like'"
        />
        DSI-like 离散平滑插值
      </label>
      <span class="algo-note" data-test="dsi-like-note">
        基于 IDW 初始场和离散邻域平滑的工程近似方法，不等同于 GOCAD DSI。
      </span>
      <span v-if="algorithmLock" class="lock-hint" data-test="algorithm-lock">已锁定</span>
    </div>

    <div class="editor-row">
      <span class="row-label">参数模式</span>
      <label class="radio">
        <input
          type="radio"
          name="mode"
          data-test="mode-manual"
          :checked="searchMode === 'manual'"
          @change="searchMode = 'manual'"
        />
        单组参数（1 个候选）
      </label>
      <label class="radio">
        <input
          type="radio"
          name="mode"
          data-test="mode-grid"
          :checked="searchMode === 'grid'"
          @change="searchMode = 'grid'"
        />
        参数网格（自动组合）
      </label>
    </div>

    <template v-if="searchMode === 'manual'">
      <div v-if="algorithm === 'idw'" class="editor-grid">
        <label class="field">
          <span>幂次 power</span>
          <input v-model.number="idwPower" type="number" step="0.5" min="0.5" max="8" class="gmp-input" data-test="idw-power" />
        </label>
        <label class="field">
          <span>邻域点数</span>
          <input v-model.number="idwNeighbors" type="number" step="1" min="1" max="128" class="gmp-input" data-test="idw-neighbors" />
        </label>
        <label v-if="preset" class="field">
          <span>垂向距离缩放 z_scale</span>
          <input v-model.number="zScale" type="number" step="0.1" min="0.1" max="20" class="gmp-input" data-test="z-scale-manual" :disabled="zScaleLock !== null && zScaleLock !== undefined" />
        </label>
      </div>
      <div v-else-if="algorithm === 'ordinary_kriging'" class="editor-grid">
        <label class="field">
          <span>变异函数模型</span>
          <select v-model="krigingModel" class="gmp-select" data-test="kriging-model">
            <option value="spherical">球状 spherical</option>
            <option value="exponential">指数 exponential</option>
            <option value="gaussian">高斯 gaussian</option>
          </select>
        </label>
        <label class="field">
          <span>变异函数模式</span>
          <select v-model="krigingMode" class="gmp-select" data-test="kriging-mode">
            <option value="auto">自动拟合（仅训练折）</option>
            <option value="manual">手动 nugget/sill/range</option>
          </select>
        </label>
        <template v-if="krigingMode === 'manual'">
          <label class="field">
            <span>块金 nugget</span>
            <input v-model.number="krigingNugget" type="number" step="0.1" min="0" class="gmp-input" data-test="kriging-nugget" />
          </label>
          <label class="field">
            <span>基台 sill</span>
            <input v-model.number="krigingSill" type="number" step="0.1" min="0.1" class="gmp-input" data-test="kriging-sill" />
          </label>
          <label class="field">
            <span>变程 range</span>
            <input v-model.number="krigingRange" type="number" step="1" min="1" class="gmp-input" data-test="kriging-range" />
          </label>
        </template>
        <label class="field">
          <span>邻域点数</span>
          <input v-model.number="krigingNeighbors" type="number" step="1" min="4" max="128" class="gmp-input" data-test="kriging-neighbors" />
        </label>
        <label v-if="preset" class="field">
          <span>垂向距离缩放 z_scale</span>
          <input v-model.number="zScale" type="number" step="0.1" min="0.1" max="20" class="gmp-input" data-test="z-scale-manual" :disabled="zScaleLock !== null && zScaleLock !== undefined" />
        </label>
      </div>
      <div v-else class="editor-grid">
        <label class="field">
          <span>IDW 初始场幂次 init_power</span>
          <select v-model.number="dsiInitPower" class="gmp-select" data-test="dsi-init-power">
            <option v-for="p in DSI_INIT_POWER_OPTIONS" :key="p" :value="p">{{ p.toFixed(1) }}</option>
          </select>
        </label>
        <label class="field">
          <span>邻域连通性 neighbor_connectivity</span>
          <select v-model.number="dsiConnectivity" class="gmp-select" data-test="dsi-connectivity">
            <option v-for="c in DSI_CONNECTIVITY_OPTIONS" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>
        <label class="field">
          <span>平滑强度 smoothing_strength</span>
          <select v-model.number="dsiSmoothing" class="gmp-select" data-test="dsi-smoothing">
            <option v-for="s in DSI_SMOOTHING_OPTIONS" :key="s" :value="s">{{ s }}</option>
          </select>
        </label>
        <label class="field">
          <span>最大迭代次数 max_iterations</span>
          <select v-model.number="dsiIterations" class="gmp-select" data-test="dsi-iterations">
            <option v-for="m in DSI_ITERATION_OPTIONS" :key="m" :value="m">{{ m }}</option>
          </select>
        </label>
        <p class="field fixed-field" data-test="dsi-convergence-tolerance">
          <span>收敛容差 convergence_tolerance</span>
          <span class="fixed-value">固定 1e-4（只读）</span>
        </p>
        <p class="field fixed-field" data-test="dsi-hard-constraints">
          <span>观测点硬约束 hard_constraints</span>
          <span class="fixed-value">始终开启，不可关闭</span>
        </p>
      </div>
      <p v-if="preset && algorithm !== 'dsi_like'" class="editor-hint" data-test="z-scale-hint">{{ zScaleHint }}</p>
      <p v-if="manualKrigingInvalid" class="editor-error" data-test="kriging-manual-invalid">
        手动变异函数要求 sill &gt; nugget ≥ 0 且 range &gt; 0
      </p>
      <p v-if="manualZScaleInvalid" class="editor-error" data-test="z-scale-invalid">
        z_scale 需满足 0 &lt; z_scale ≤ 20
      </p>
    </template>

    <template v-else>
      <div v-if="algorithm === 'idw'" class="editor-grid">
        <label class="field wide">
          <span>power 候选（逗号分隔）</span>
          <input v-model="gridPower" class="gmp-input" data-test="grid-power" placeholder="如：1.5, 2, 3" />
        </label>
        <label class="field wide">
          <span>邻域点数候选</span>
          <input v-model="gridNeighbors" class="gmp-input" data-test="grid-neighbors" placeholder="如：8, 16, 32" />
        </label>
        <label v-if="preset" class="field wide">
          <span>z_scale 候选</span>
          <input v-model="gridZScale" class="gmp-input" data-test="grid-z-scale" placeholder="如：0.5, 1, 2" :disabled="zScaleLock !== null && zScaleLock !== undefined" />
        </label>
      </div>
      <div v-else-if="algorithm === 'ordinary_kriging'" class="editor-grid">
        <div class="field wide">
          <span>变异函数模型候选</span>
          <label v-for="m in ['spherical', 'exponential', 'gaussian'] as const" :key="m" class="radio inline">
            <input v-model="gridModels" type="checkbox" :value="m" :data-test="`grid-model-${m}`" />
            {{ m }}
          </label>
        </div>
        <label class="field wide">
          <span>邻域点数候选</span>
          <input v-model="gridKrigingNeighbors" class="gmp-input" data-test="grid-kriging-neighbors" placeholder="如：16, 24, 32" />
        </label>
        <label v-if="preset" class="field wide">
          <span>z_scale 候选</span>
          <input v-model="gridZScale" class="gmp-input" data-test="grid-z-scale" placeholder="如：0.5, 1, 2" :disabled="zScaleLock !== null && zScaleLock !== undefined" />
        </label>
        <p class="editor-hint">网格搜索固定使用自动变异函数拟合（每折独立，防泄漏）。</p>
      </div>
      <div v-else class="editor-grid">
        <div class="field wide">
          <span>init_power 候选</span>
          <label v-for="p in DSI_INIT_POWER_OPTIONS" :key="p" class="radio inline">
            <input v-model="dsiGridInitPower" type="checkbox" :value="p" :data-test="`grid-dsi-init-power-${p}`" />
            {{ p.toFixed(1) }}
          </label>
        </div>
        <div class="field wide">
          <span>邻域连通性候选</span>
          <label v-for="c in DSI_CONNECTIVITY_OPTIONS" :key="c" class="radio inline">
            <input v-model="dsiGridConnectivity" type="checkbox" :value="c" :data-test="`grid-dsi-connectivity-${c}`" />
            {{ c }}
          </label>
        </div>
        <div class="field wide">
          <span>平滑强度候选</span>
          <label v-for="s in DSI_SMOOTHING_OPTIONS" :key="s" class="radio inline">
            <input v-model="dsiGridSmoothing" type="checkbox" :value="s" :data-test="`grid-dsi-smoothing-${s}`" />
            {{ s }}
          </label>
        </div>
        <div class="field wide">
          <span>最大迭代次数候选</span>
          <label v-for="m in DSI_ITERATION_OPTIONS" :key="m" class="radio inline">
            <input v-model="dsiGridIterations" type="checkbox" :value="m" :data-test="`grid-dsi-iterations-${m}`" />
            {{ m }}
          </label>
        </div>
        <p class="editor-hint">
          网格搜索同样固定 convergence_tolerance = 1e-4 与 hard_constraints = 开启（每个组合一份）。
        </p>
      </div>
      <p v-if="preset && algorithm !== 'dsi_like'" class="editor-hint" data-test="z-scale-hint">{{ zScaleHint }}</p>

      <div class="count-line" :class="countState" data-test="count-preview">
        预计 {{ candidateCount }} 个候选组合
        <span v-if="countState === 'warn'" class="count-note warn" data-test="count-warning">
          超过 30 组合将显著拉长运行时间
        </span>
        <span v-else-if="countState === 'blocked'" class="count-note bad" data-test="count-error">
          超过硬上限 50，无法提交
        </span>
      </div>
    </template>

    <div class="editor-row validation-row">
      <span class="row-label">空间验证</span>
      <label class="field small">
        <span>折数</span>
        <input v-model.number="folds" type="number" min="3" max="10" class="gmp-input" data-test="val-folds" />
      </label>
      <label class="field small">
        <span>随机种子</span>
        <input v-model.number="seed" type="number" class="gmp-input" data-test="val-seed" />
      </label>
      <label class="field small">
        <span>留出比例</span>
        <input v-model.number="holdout" type="number" step="0.05" min="0.1" max="0.4" class="gmp-input" data-test="val-holdout" />
      </label>
    </div>

    <details class="advanced">
      <summary>高级：自定义输出网格（默认按数据范围自动）</summary>
      <div class="editor-grid">
        <label class="field small">
          <span>启用自定义</span>
          <input v-model="gridCustom" type="checkbox" data-test="grid-custom-enable" />
        </label>
        <label class="field small">
          <span>每轴节点数</span>
          <input v-model.number="gridNodes" type="number" min="2" max="61" class="gmp-input" data-test="grid-nodes" />
        </label>
        <template v-for="(axis, idx) in AXES.slice(0, dimension === '3d' ? 3 : 2)" :key="axis">
          <label class="field small">
            <span>{{ axis.toUpperCase() }} 最小</span>
            <input v-model.number="boundsText[idx].min" type="number" class="gmp-input" :data-test="`grid-${axis}-min`" />
          </label>
          <label class="field small">
            <span>{{ axis.toUpperCase() }} 最大</span>
            <input v-model.number="boundsText[idx].max" type="number" class="gmp-input" :data-test="`grid-${axis}-max`" />
          </label>
        </template>
      </div>
      <p v-if="customGridInvalid" class="editor-error" data-test="grid-invalid">
        自定义网格要求每轴最大值 &gt; 最小值且节点数 ≥ 2
      </p>
    </details>

    <div class="editor-actions">
      <button class="gmp-btn primary" data-test="exp-submit" :disabled="!canSubmit" @click="submit">
        {{ submitting ? '提交中…' : '创建实验并运行' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.editor {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.editor-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.row-label {
  width: 64px;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.radio {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  cursor: pointer;
}

.radio.inline {
  margin-right: 12px;
}

.editor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.field.wide {
  grid-column: span 2;
}

.field.small {
  min-width: 110px;
}

.gmp-input,
.gmp-select {
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  color: var(--gmp-text);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
}

.validation-row {
  border-top: 1px dashed var(--gmp-border);
  padding-top: 12px;
}

.count-line {
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.count-note {
  margin-left: 10px;
  font-size: 12px;
}

.count-note.warn {
  color: #e5c76b;
}

.count-note.bad {
  color: #ef9a9a;
}

.advanced {
  border-top: 1px dashed var(--gmp-border);
  padding-top: 10px;
  font-size: 13px;
}

.advanced summary {
  cursor: pointer;
  color: var(--gmp-text-dim);
  margin-bottom: 10px;
}

.editor-hint {
  font-size: 12px;
  color: var(--gmp-text-faint);
  margin: 0;
}

.editor-error {
  font-size: 12px;
  color: #ef9a9a;
  margin: 0;
}

.editor-actions {
  display: flex;
  gap: 12px;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 8px 18px;
  font-size: 13px;
  cursor: pointer;
}

.gmp-btn.primary {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.lock-hint {
  font-size: 12px;
  color: #e5c76b;
}

.algo-note {
  flex-basis: 100%;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.fixed-field {
  margin: 0;
}

.fixed-value {
  font-size: 13px;
  color: var(--gmp-text);
}
</style>

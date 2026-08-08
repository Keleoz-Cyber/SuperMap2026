<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, fetchAnalysisSummary } from '../api/client'
import type { AnalysisModuleResult } from '../api/types'
import PageNavigation from '../components/navigation/PageNavigation.vue'
import AnalysisHeader from '../components/analysis/AnalysisHeader.vue'
import QualitySummaryPanel from '../components/analysis/QualitySummaryPanel.vue'
import DistributionPanel from '../components/analysis/DistributionPanel.vue'
import SpatialFeaturePanel from '../components/analysis/SpatialFeaturePanel.vue'
import ModelComparisonPanel from '../components/analysis/ModelComparisonPanel.vue'
import ProfileAnalysisPanel from '../components/analysis/ProfileAnalysisPanel.vue'
import AnalysisExportPanel from '../components/analysis/AnalysisExportPanel.vue'
import {
  comparisonCandidatesOf,
  MODULE_LABELS,
  type AnalysisSelection,
} from '../components/analysis/analysisTypes'

// v0.8.0 第二批 Task 5：统计与空间分析中心 A+B 工作台壳（设计 §7）。
// 顶栏 AnalysisHeader；左侧窄栏模块导航（选中态 + disabled 标记）；中央
// 主区单焦点（默认空间视图，可切换分布/剖面）；右栏 QualitySummary +
// ModelComparison；底部可折叠（剖面统计 + 导出/溯源）。数据获取沿用单调
// 请求守卫与三态；模块可见性由后端 modules.status 驱动（disabled/error
// → 解释性空状态，绝不渲染空图表）。空间/剖面选择 → 有物化成果时
// router.push /results/{id}（带 axis/range/dataset 查询参数），否则非阻
// 断解释提示。响应式：<900px 右栏折到主区下方，<600px 左导航横向滚动。

const route = useRoute()
const router = useRouter()
const datasetId = computed(() => String(route.params.datasetId ?? ''))
const queryCaseId = computed(() => {
  const q = route.query.case
  return typeof q === 'string' ? q : ''
})

const loading = ref(true)
const loadError = ref<string | null>(null)
const summary = ref<Awaited<ReturnType<typeof fetchAnalysisSummary>> | null>(null)

const caseLinkId = computed(() => summary.value?.case_id ?? queryCaseId.value)

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

// ---------------------------------------------------------------------------
// 模块导航：右栏模块（quality/statistics/model_comparison）不进导航；
// 通用视图模块按固定顺序在前，其余（专属）模块按响应顺序在后
// ---------------------------------------------------------------------------

const RIGHTBAR_MODULE_IDS = new Set(['quality', 'statistics', 'model_comparison'])
const PRIMARY_MODULE_ORDER = ['spatial_extent', 'distribution', 'profile_slices']

interface NavItem {
  module: AnalysisModuleResult
  label: string
  usable: boolean
}

const navItems = computed<NavItem[]>(() => {
  const modules = (summary.value?.modules ?? []).filter(
    (module) => !RIGHTBAR_MODULE_IDS.has(module.module_id),
  )
  const orderOf = (id: string) => {
    const index = PRIMARY_MODULE_ORDER.indexOf(id)
    return index === -1 ? PRIMARY_MODULE_ORDER.length : index
  }
  return modules
    .slice()
    .sort((a, b) => orderOf(a.module_id) - orderOf(b.module_id))
    .map((module) => ({
      module,
      label: MODULE_LABELS[module.module_id] ?? module.module_id,
      usable:
        module.status === 'ok' && PRIMARY_MODULE_ORDER.includes(module.module_id),
    }))
})

const activeModuleId = ref('')

function defaultModuleId(): string {
  const items = navItems.value
  const spatial = items.find((item) => item.module.module_id === 'spatial_extent')
  if (spatial?.usable) return spatial.module.module_id
  return items.find((item) => item.usable)?.module.module_id ?? items[0]?.module.module_id ?? ''
}

const activeModule = computed<AnalysisModuleResult | null>(
  () =>
    summary.value?.modules.find((module) => module.module_id === activeModuleId.value) ?? null,
)

const activeNavItem = computed<NavItem | null>(
  () => navItems.value.find((item) => item.module.module_id === activeModuleId.value) ?? null,
)

function selectModule(moduleId: string) {
  activeModuleId.value = moduleId
}

function moduleOf(moduleId: string): AnalysisModuleResult | null {
  return summary.value?.modules.find((module) => module.module_id === moduleId) ?? null
}

// 底部折叠区剖面模块（仅在未被提升为主焦点时渲染，避免双图表实例）
const profileModule = computed<AnalysisModuleResult | null>(() =>
  activeModuleId.value === 'profile_slices' ? null : moduleOf('profile_slices'),
)

// ---------------------------------------------------------------------------
// 选择 → 成果导航：正式选择且已物化的候选优先，否则首个已物化候选
// ---------------------------------------------------------------------------

const materializedResultId = computed<string | null>(() => {
  const candidates = comparisonCandidatesOf(moduleOf('model_comparison'))
  const formal = candidates.find((candidate) => candidate.formal_selection && candidate.materialized)
  const first = candidates.find((candidate) => candidate.materialized)
  return (formal ?? first)?.result_id ?? null
})

const selectionHint = ref<string | null>(null)

function handleSelection(selection: AnalysisSelection) {
  selectionHint.value = null
  if (!selection.result_id) {
    selectionHint.value =
      '当前数据版本暂无已物化成果，无法定位到结果视图；请先在案例工作台完成实验并物化成果后再使用空间/剖面联动。'
    return
  }
  if (selection.axis === 'xy') {
    void router.push({
      path: `/results/${selection.result_id}`,
      query: {
        axis: 'xy',
        x_range: selection.x_range.join('..'),
        y_range: selection.y_range.join('..'),
        dataset: selection.dataset_id,
      },
    })
    return
  }
  void router.push({
    path: `/results/${selection.result_id}`,
    query: {
      axis: selection.axis,
      range: selection.range.join('..'),
      dataset: selection.dataset_id,
    },
  })
}

// ---------------------------------------------------------------------------
// 底部可折叠区：剖面统计（未被提升为主焦点时）+ 导出/溯源
// ---------------------------------------------------------------------------

const lowerActive = ref<string[]>([])

function openExport() {
  if (!lowerActive.value.includes('export')) {
    lowerActive.value = [...lowerActive.value, 'export']
  }
}

// 折叠面板展开后隐藏的 ECharts 需要一次 resize 才能正确布局
watch(lowerActive, () => {
  void nextTick(() => window.dispatchEvent(new Event('resize')))
})

// ---------------------------------------------------------------------------
// 数据获取：单调请求守卫 + 三态（沿用占位视图语义）
// ---------------------------------------------------------------------------

let requestSeq = 0

async function loadSummary() {
  const targetId = datasetId.value
  const seq = ++requestSeq
  loading.value = true
  loadError.value = null
  summary.value = null
  selectionHint.value = null
  try {
    const result = await fetchAnalysisSummary(targetId)
    if (seq !== requestSeq || targetId !== datasetId.value) return
    summary.value = result
    activeModuleId.value = defaultModuleId()
  } catch (e) {
    if (seq !== requestSeq || targetId !== datasetId.value) return
    loadError.value = describeError(e)
  } finally {
    if (seq === requestSeq && targetId === datasetId.value) loading.value = false
  }
}

onMounted(loadSummary)

watch(datasetId, (next, prev) => {
  if (next !== prev) void loadSummary()
})
</script>

<template>
  <div class="analysis-center-page" data-test="analysis-center-view">
    <PageNavigation
      :case-id="caseLinkId || undefined"
      :dataset-id="datasetId"
      current-label="统计与空间分析"
    />

    <el-result
      v-if="loadError"
      icon="error"
      title="分析摘要加载失败"
      :sub-title="loadError"
      data-test="analysis-error"
      role="alert"
    />
    <div v-else-if="loading" v-loading="true" class="page-loading" data-test="analysis-loading" />

    <template v-else-if="summary">
      <AnalysisHeader :summary="summary" @export="openExport" />

      <el-alert
        v-if="selectionHint"
        type="info"
        :title="selectionHint"
        show-icon
        data-test="analysis-selection-hint"
        @close="selectionHint = null"
      />

      <div class="analysis-layout" data-test="analysis-content">
        <nav class="module-nav" data-test="module-nav" aria-label="分析模块导航">
          <button
            v-for="item in navItems"
            :key="item.module.module_id"
            type="button"
            class="nav-item"
            :class="{ active: item.module.module_id === activeModuleId }"
            :data-test="`module-nav-item-${item.module.module_id}`"
            @click="selectModule(item.module.module_id)"
          >
            <span class="nav-label">{{ item.label }}</span>
            <span v-if="item.module.status !== 'ok'" class="nav-flag">不可用</span>
          </button>
          <p v-if="navItems.length === 0" class="nav-empty">当前数据版本未提供分析模块。</p>
        </nav>

        <main class="primary-area" data-test="primary-area">
          <SpatialFeaturePanel
            v-if="activeNavItem?.usable && activeModuleId === 'spatial_extent' && activeModule"
            :module="activeModule"
            :variable="summary.variable"
            :dataset-id="datasetId"
            :result-id="materializedResultId"
            @select="handleSelection"
          />
          <DistributionPanel
            v-else-if="activeNavItem?.usable && activeModuleId === 'distribution' && activeModule"
            :module="activeModule"
            :variable="summary.variable"
            :profile="summary.analysis_profile"
          />
          <ProfileAnalysisPanel
            v-else-if="activeNavItem?.usable && activeModuleId === 'profile_slices' && activeModule"
            :module="activeModule"
            :variable="summary.variable"
            :dataset-id="datasetId"
            :result-id="materializedResultId"
            @select="handleSelection"
          />
          <section v-else class="module-disabled" data-test="module-disabled-state">
            <h3>{{ activeNavItem?.label ?? '分析模块' }}</h3>
            <p>
              {{
                activeModule?.message ??
                  '该分析模块在当前数据版本不可用；其可视化将在后续批次就位。'
              }}
            </p>
          </section>
        </main>

        <aside class="side-area" data-test="side-area">
          <QualitySummaryPanel
            :quality="summary.quality"
            :statistics="summary.statistics"
            :variable="summary.variable"
          />
          <ModelComparisonPanel :module="moduleOf('model_comparison')" />
        </aside>
      </div>

      <el-collapse v-model="lowerActive" class="lower-area" data-test="lower-area">
        <el-collapse-item v-if="profileModule" title="剖面统计" name="profile">
          <ProfileAnalysisPanel
            :module="profileModule"
            :variable="summary.variable"
            :dataset-id="datasetId"
            :result-id="materializedResultId"
            @select="handleSelection"
          />
        </el-collapse-item>
        <el-collapse-item title="导出与数据溯源" name="export">
          <AnalysisExportPanel
            :provenance="summary.provenance"
            :dataset-id="datasetId"
            :profile="summary.analysis_profile"
          />
        </el-collapse-item>
      </el-collapse>
    </template>
  </div>
</template>

<style scoped>
.analysis-center-page {
  min-height: 100%;
  max-width: 1400px;
  margin: 0 auto;
  padding: 24px 20px 48px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-loading {
  min-height: 200px;
}

.analysis-layout {
  display: grid;
  grid-template-columns: 168px minmax(0, 1fr) 340px;
  gap: 16px;
  align-items: start;
}

.module-nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  background: var(--gmp-card);
  color: var(--gmp-text-dim);
  font-size: 13px;
  cursor: pointer;
  text-align: left;
  white-space: nowrap;
}

.nav-item:hover {
  background: var(--gmp-card-hover);
}

.nav-item.active {
  border-color: var(--gmp-accent);
  color: var(--gmp-text);
}

.nav-flag {
  font-size: 11px;
  color: var(--gmp-text-faint);
  border: 1px solid var(--gmp-border-soft);
  border-radius: 4px;
  padding: 0 4px;
}

.nav-empty {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.primary-area {
  min-width: 0;
}

.module-disabled {
  background: var(--gmp-card);
  border: 1px dashed var(--gmp-border);
  border-radius: 12px;
  padding: 24px 18px;
}

.module-disabled h3 {
  margin: 0 0 8px;
  font-size: 15px;
}

.module-disabled p {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.side-area {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.lower-area {
  border: none;
}

.lower-area :deep(.el-collapse-item__header) {
  font-size: 14px;
}

@media (max-width: 900px) {
  .analysis-layout {
    grid-template-columns: 148px minmax(0, 1fr);
  }

  .side-area {
    grid-column: 1 / -1;
  }
}

@media (max-width: 600px) {
  .analysis-center-page {
    padding: 16px 12px 32px;
  }

  .analysis-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .module-nav {
    flex-direction: row;
    overflow-x: auto;
    padding-bottom: 4px;
  }

  .nav-item {
    flex-shrink: 0;
  }
}
</style>

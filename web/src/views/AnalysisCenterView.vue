<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, fetchAnalysisSummary } from '../api/client'
import type { AnalysisModuleResult } from '../api/types'
import PageNavigation from '../components/navigation/PageNavigation.vue'
import AsyncState from '../components/states/AsyncState.vue'
import AnalysisHeader from '../components/analysis/AnalysisHeader.vue'
import QualitySummaryPanel from '../components/analysis/QualitySummaryPanel.vue'
import DistributionPanel from '../components/analysis/DistributionPanel.vue'
import SpatialFeaturePanel from '../components/analysis/SpatialFeaturePanel.vue'
import ModelComparisonPanel from '../components/analysis/ModelComparisonPanel.vue'
import ProfileAnalysisPanel from '../components/analysis/ProfileAnalysisPanel.vue'
import AnalysisExportPanel from '../components/analysis/AnalysisExportPanel.vue'
import {
  comparisonCandidatesOf,
  moduleLabel,
  type AnalysisSelection,
} from '../components/analysis/analysisTypes'

// v0.8.0 第二批 Task 5：统计与空间分析中心 A+B 工作台壳（设计 §7）。
// 顶栏 AnalysisHeader；左侧窄栏模块导航（选中态 + disabled 标记）；中央
// 主区单焦点（默认空间视图：generic 为 spatial_extent，微震/电阻率/瓦斯为
// spatial_anomaly 专属空间异常，可切换分布/剖面）；右栏 QualitySummary +
// ModelComparison；底部可折叠（剖面统计 + 导出/溯源）。数据获取沿用单调
// 请求守卫与三态；模块可见性由后端 modules.status 驱动（disabled/error
// → 解释性空状态，绝不渲染空图表）；generic_3d 显示降级原因说明（§5.4）。
// v0.8.0 第三批 Task 8：瓦斯模块用差异化标签（moduleLabel），ok 但暂无
// 面板的专属模块（axis_trends/gradient/depth_slices）不生成占位导航入口。
// 空间/剖面选择 → 有物化成果时
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

// 设计 §5.4：generic 降级必须写明为什么未启用专业分析（字段口径与后端
// profiles.py 注册表一致，按 profile id 静态说明，绝不按案例 ID 分支）
const GENERIC_FALLBACK_TEXT =
  '当前数据按 generic_3d 通用 profile 分析：未满足专业分析字段要求' +
  '（微震速度需变量 Vx 且单位 km/s；电阻率需变量名 RHO；瓦斯含量需变量名 CH4_content 且单位 ml/g）。' +
  '页面仅展示数据质量、基础统计、分布、空间范围、剖面与已有模型指标，不展示专业专属模块。'

// ---------------------------------------------------------------------------
// 模块导航：右栏模块（quality/statistics/model_comparison）不进导航；
// 通用视图模块按固定顺序在前，其余（专属）模块按响应顺序在后
// ---------------------------------------------------------------------------

const RIGHTBAR_MODULE_IDS = new Set(['quality', 'statistics'])
// 主区可承载的模块（顺序即导航优先级）：spatial_extent/spatial_anomaly 由
// SpatialFeaturePanel 承载（Task 6 起 spatial_anomaly 为专属 profile 的默认
// 空间视图——这些 profile 无 spatial_extent），distribution/profile_slices
// 各有专属面板；其余专属模块（axis_trends/gradient/depth_slices）暂无面板，
// ok 状态不生成占位导航入口（Task 8），disabled 状态保留导航并标记不可用
const PRIMARY_MODULE_ORDER = ['spatial_extent', 'spatial_anomaly', 'distribution', 'profile_slices', 'model_comparison']

interface NavItem {
  module: AnalysisModuleResult
  label: string
  usable: boolean
}

const navItems = computed<NavItem[]>(() => {
  const profile = summary.value?.analysis_profile ?? 'generic_3d'
  const modules = (summary.value?.modules ?? []).filter(
    (module) =>
      !RIGHTBAR_MODULE_IDS.has(module.module_id) &&
      // ok 但暂无面板的专属模块不生成占位入口；disabled/error 保留解释性入口
      (module.status !== 'ok' || PRIMARY_MODULE_ORDER.includes(module.module_id)),
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
      label: moduleLabel(profile, module.module_id),
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

const profileConclusion = computed(() => {
  if (!summary.value) return { title: '', body: '' }
  const valid = summary.value.quality.valid_count?.toLocaleString('zh-CN') ?? '未知'
  const unit = summary.value.variable.unit ? ` ${summary.value.variable.unit}` : ''
  const median = summary.value.statistics?.median
  const medianText = median === null || median === undefined ? '' : `，中位数 ${median.toLocaleString('zh-CN')}${unit}`
  const profile = summary.value.analysis_profile
  if (profile === 'resistivity') {
    return { title: '电阻率空间差异已形成可定位证据', body: `基于 ${valid} 个有效样本${medianText}；先查看高低值区域，再回到三维成果核对其空间连续性。` }
  }
  if (profile === 'microseismic_velocity') {
    return { title: '微震速度的空间变化可分层查看', body: `基于 ${valid} 个有效样本${medianText}；结合空间分布与剖面趋势判断局部速度变化。` }
  }
  if (profile === 'gas_content') {
    return { title: '瓦斯含量的高低值区域可进一步核查', body: `基于 ${valid} 个有效样本${medianText}；结论仅描述样本分布与空间位置，不延伸为规范判断。` }
  }
  return { title: '已生成通用数据分布与空间证据', body: `基于 ${valid} 个有效样本${medianText}；当前字段未匹配专属地质分析口径。` }
})

const contextEvidence = computed(() => {
  if (activeModuleId.value === 'model_comparison') return '模型证据：比较同一数据版本下已有候选的公共验证指标。'
  if (activeModuleId.value === 'distribution') return '分布证据：查看取值集中区间、偏态和长尾，不替代空间位置判断。'
  if (activeModuleId.value === 'profile_slices') return '剖面证据：沿 X/Y/Z 方向检查属性变化，并可定位到三维成果。'
  return '空间证据：查看样本或属性在 XY 平面的聚集与高低值位置，并与三维成果互相核对。'
})

function openMaterializedResult() {
  if (!materializedResultId.value) return
  void router.push(`/results/${materializedResultId.value}`)
}

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
  <div class="analysis-center-page product-page product-page--wide" data-test="analysis-center-view">
    <PageNavigation
      :case-id="caseLinkId || undefined"
      :dataset-id="datasetId"
      current-label="统计与空间分析"
    />

    <AsyncState
      v-if="loadError"
      kind="error"
      title="分析摘要加载失败"
      :impact="loadError"
      next-action="返回案例工作台重新进入，或稍后重试"
      data-test="analysis-error"
    />
    <AsyncState
      v-else-if="loading"
      kind="loading"
      title="分析摘要加载中"
      data-test="analysis-loading"
    />

    <template v-else-if="summary">
      <AnalysisHeader :summary="summary" @export="openExport" />

      <section class="analysis-conclusion" data-test="analysis-conclusion">
        <div>
          <span class="conclusion-kicker">本次分析结论</span>
          <h2>{{ profileConclusion.title }}</h2>
          <p>{{ profileConclusion.body }}</p>
        </div>
        <el-button
          v-if="materializedResultId"
          type="primary"
          data-test="analysis-open-result"
          @click="openMaterializedResult"
        >
          在三维成果中核对
        </el-button>
      </section>

      <el-alert
        v-if="summary.analysis_profile === 'generic_3d'"
        type="info"
        show-icon
        :closable="false"
        :title="GENERIC_FALLBACK_TEXT"
        data-test="analysis-generic-fallback"
      />

      <el-alert
        v-if="selectionHint"
        type="info"
        :title="selectionHint"
        show-icon
        data-test="analysis-selection-hint"
        @close="selectionHint = null"
      />

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

      <div class="analysis-layout" data-test="analysis-content">
        <main class="primary-area" data-test="primary-area">
          <SpatialFeaturePanel
            v-if="
              activeNavItem?.usable &&
              (activeModuleId === 'spatial_extent' || activeModuleId === 'spatial_anomaly') &&
              activeModule
            "
            :module="activeModule"
            :variable="summary.variable"
            :dataset-id="datasetId"
            :result-id="materializedResultId"
            :profile="summary.analysis_profile"
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
          <ModelComparisonPanel
            v-else-if="activeNavItem?.usable && activeModuleId === 'model_comparison'"
            :module="activeModule"
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
        <aside class="context-evidence" data-test="context-evidence">
          <span>如何阅读</span>
          <p>{{ contextEvidence }}</p>
          <button v-if="materializedResultId" type="button" @click="openMaterializedResult">查看对应三维成果 →</button>
        </aside>
      </div>

      <el-collapse v-model="lowerActive" class="lower-area" data-test="lower-area">
        <el-collapse-item title="数据质量与统计口径" name="quality">
          <QualitySummaryPanel
            :quality="summary.quality"
            :statistics="summary.statistics"
            :variable="summary.variable"
          />
        </el-collapse-item>
        <el-collapse-item title="方法、导出与技术溯源" name="export">
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
  max-width: var(--s1-page-wide);
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
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 16px;
  align-items: start;
}

.module-nav {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 2px;
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
  flex: 0 0 auto;
}

.nav-item:hover {
  background: var(--gmp-card-hover);
}

.nav-item.active {
  border-color: var(--gmp-accent);
  color: var(--gmp-text);
}

.nav-flag {
  font-size: 12px;
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

.analysis-conclusion {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--s1-space-6);
  padding: var(--s1-space-5) 0;
  border-block: 1px solid var(--s1-border);
}

.conclusion-kicker,
.context-evidence > span {
  color: var(--s1-cyan-strong);
  font-size: var(--s1-font-xs);
  font-weight: 600;
}

.analysis-conclusion h2 {
  margin: 6px 0;
  font-size: var(--s1-font-xl);
}

.analysis-conclusion p,
.context-evidence p {
  margin: 0;
  color: var(--s1-text-dim);
  line-height: var(--s1-leading);
}

.context-evidence {
  position: sticky;
  top: var(--s1-space-4);
  padding: var(--s1-space-4);
  border-left: 2px solid var(--s1-border-strong);
}

.context-evidence button {
  margin-top: var(--s1-space-4);
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--s1-cyan-strong);
  cursor: pointer;
}

.lower-area {
  border: none;
}

.lower-area :deep(.el-collapse-item__header) {
  font-size: 14px;
}

@media (max-width: 900px) {
  .analysis-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .context-evidence {
    position: static;
    border-left: 0;
    border-top: 1px solid var(--s1-border);
  }
}

@media (max-width: 600px) {
  .analysis-center-page {
    padding: 16px 12px 32px;
  }

  .analysis-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .analysis-conclusion {
    align-items: flex-start;
    flex-direction: column;
  }

  .nav-item {
    flex-shrink: 0;
  }
}
</style>

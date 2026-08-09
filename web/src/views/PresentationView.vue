<script setup lang="ts">
// v0.9.0：答辩模式章节宿主。固定六章节 + 键盘导航 + 降级路线；
// 案例章节复用指挥舱场景与发现组件（只读），数据不可用章节显示
// 显式降级面板且保持可导航，绝不黑屏或伪造内容。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  fetchAnalysisSummary,
  fetchCases,
  fetchCaseWorkspace,
  fetchHealth,
} from '../api/client'
import type { AnalysisSummaryResponse, CaseSummary, CaseWorkspaceSummary } from '../api/types'
import { CASE_PRESENTATION, resolveCaseProfile, type CaseProfile } from '../domain/casePresentation'
import { buildPresentationFindings, type PresentationFinding } from '../domain/findings'
import { PLATFORM_DEMO_3D_DOWNLOAD_URL } from '../api/client'
import PresentationOverlay from '../components/presentation/PresentationOverlay.vue'
import CommandCenterScene from '../components/home/CommandCenterScene.vue'
import FindingPanel from '../components/findings/FindingPanel.vue'
import AsyncState from '../components/states/AsyncState.vue'
import { usePresentationStore, type PresentationChapterId } from '../stores/presentation'

const router = useRouter()
const store = usePresentationStore()

const cases = ref<CaseSummary[]>([])
const serviceOnline = ref<boolean | null>(null)

// 案例章节缓存：按 profile 加载工作台与分析摘要（只读 GET）
const chapterWorkspace = ref<CaseWorkspaceSummary | null>(null)
const chapterFindings = ref<PresentationFinding[]>([])
const chapterLoading = ref(false)
const chapterUnavailable = ref<string | null>(null)
let chapterSeq = 0

const CASE_CHAPTER_PROFILE: Partial<Record<PresentationChapterId, CaseProfile>> = {
  resistivity: 'resistivity',
  microseismic: 'microseismic_velocity',
  gas: 'gas_content',
}

const activeCaseProfile = computed(
  () => CASE_CHAPTER_PROFILE[store.currentId.value] ?? null,
)

const chapterCase = computed(() => {
  if (!activeCaseProfile.value) return null
  return (
    cases.value.find(
      (c) => resolveCaseProfile(c.provenance_summary) === activeCaseProfile.value,
    ) ?? null
  )
})

const chapterPresentation = computed(() =>
  activeCaseProfile.value ? CASE_PRESENTATION[activeCaseProfile.value] : null,
)

const reducedMotion = ref(false)

async function loadChapter() {
  const profile = activeCaseProfile.value
  const seq = ++chapterSeq
  chapterWorkspace.value = null
  chapterFindings.value = []
  chapterUnavailable.value = null
  if (!profile) return
  const target = chapterCase.value
  if (!target) {
    chapterUnavailable.value = '本运行库未登记该官方案例，跳过本章三维与发现。'
    return
  }
  if (!target.official_result) {
    chapterUnavailable.value = '该案例官方成果尚未初始化（需维护者 seed），本章仅保留说明。'
    return
  }
  chapterLoading.value = true
  try {
    const ws = await fetchCaseWorkspace(target.case_id)
    if (seq !== chapterSeq) return
    chapterWorkspace.value = ws
    if (ws.primary_dataset && ws.primary_dataset.status === 'validated') {
      try {
        const summary: AnalysisSummaryResponse = await fetchAnalysisSummary(ws.primary_dataset.id)
        if (seq !== chapterSeq) return
        chapterFindings.value = buildPresentationFindings(summary)
      } catch {
        if (seq !== chapterSeq) return
        chapterFindings.value = []
      }
    }
  } catch {
    if (seq !== chapterSeq) return
    chapterWorkspace.value = null
    chapterUnavailable.value = '案例数据加载失败，本章降级为说明页。'
  } finally {
    if (seq === chapterSeq) chapterLoading.value = false
  }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    store.exit()
    return
  }
  if (event.key === 'ArrowRight') store.next()
  if (event.key === 'ArrowLeft') store.prev()
}

watch(
  () => store.currentId.value,
  () => {
    void loadChapter()
  },
)

watch(store.active, (active) => {
  if (!active) void router.push('/')
})

onMounted(async () => {
  if (!store.active.value) store.enter()
  reducedMotion.value =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  window.addEventListener('keydown', onKeydown)
  try {
    const health = await fetchHealth()
    serviceOnline.value = health.status === 'ok'
  } catch {
    serviceOnline.value = false
  }
  try {
    const resp = await fetchCases()
    cases.value = resp.cases
  } catch {
    cases.value = []
  }
  await loadChapter()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  if (store.active.value) store.exit()
})
</script>

<template>
  <div
    class="presentation-view"
    data-test="presentation-view"
    :data-motion="reducedMotion ? 'reduced' : 'full'"
  >
    <PresentationOverlay />

    <div class="chapter-body">
      <!-- 服务降级提示：所有章节共享 -->
      <p v-if="serviceOnline === false" class="service-banner" data-test="presentation-offline" role="status">
        服务当前离线：三维与分析内容不可用，章节说明仍可讲解。
      </p>

      <!-- 第一章：平台能力总览 -->
      <section v-if="store.currentId.value === 'overview'" class="chapter-stage" data-test="chapter-overview">
        <div class="chain-cards">
          <div class="chain-card">
            <h3>数据接入</h3>
            <p>CSV / XLSX 散点 · 字段映射 · 质量门禁 · 源哈希冻结</p>
          </div>
          <div class="chain-card">
            <h3>建模验证</h3>
            <p>IDW / 普通克里金 / DSI-like（工程近似） · 空间折分公共有效集</p>
          </div>
          <div class="chain-card">
            <h3>三维成果</h3>
            <p>SuperMap3D NetCDF 原生体渲染 · X/Y/Z 正交切片 · 等值面</p>
          </div>
          <div class="chain-card">
            <h3>证据追溯</h3>
            <p>正式选择 · 参数/指标/源哈希 · 导出与发布登记</p>
          </div>
        </div>
        <p class="chapter-note">当前运行库登记案例 {{ cases.length }} 个（含三个官方案例）。</p>
      </section>

      <!-- 案例章节（电阻率/微震/瓦斯共用框架） -->
      <section
        v-else-if="activeCaseProfile"
        class="chapter-stage case-chapter"
        :data-case-accent="chapterPresentation?.accent"
        :data-test="`chapter-${store.currentId.value}`"
      >
        <AsyncState v-if="chapterLoading" kind="loading" title="案例成果加载中" />
        <AsyncState
          v-else-if="chapterUnavailable"
          kind="degraded"
          title="本章降级"
          :impact="chapterUnavailable"
          next-action="可继续切换其他章节，讲解不受阻断"
        />
        <template v-else-if="chapterCase">
          <CommandCenterScene
            :case-title="chapterCase.title"
            :variable-label="chapterPresentation?.variableLabel ?? ''"
            :unit-label="typeof chapterCase.provenance_summary?.value_unit === 'string' ? chapterCase.provenance_summary.value_unit : null"
            :narrative-label="chapterPresentation?.narrativeLabel ?? ''"
            coordinate-note="局部线性米制 · 显示锚点"
            :result-id="chapterCase.official_result?.result_id ?? null"
            :result-url="chapterCase.official_result?.url ?? null"
            :loading="false"
            :error="null"
          />
          <aside class="chapter-findings">
            <FindingPanel :findings="chapterFindings" />
          </aside>
        </template>
      </section>

      <!-- 第五章：自定义数据 -->
      <section v-else-if="store.currentId.value === 'custom-data'" class="chapter-stage" data-test="chapter-custom-data">
        <div class="chain-cards">
          <div class="chain-card">
            <h3>同一建模链</h3>
            <p>上传 → 映射 → 质量门禁 → 调参实验 → 空间验证 → 正式成果，与官方案例完全一致。</p>
          </div>
          <div class="chain-card">
            <h3>固定演示数据</h3>
            <p>提供仓库冻结的演示 CSV，可现场走通全流程；演示数据身份明确标识。</p>
            <a class="demo-link" data-test="presentation-demo-download" :href="PLATFORM_DEMO_3D_DOWNLOAD_URL" download>
              下载演示数据
            </a>
          </div>
          <div class="chain-card">
            <h3>安全边界</h3>
            <p>未知坐标声明局部线性，绝不自动编造 EPSG；阻断项清零前禁止进入实验。</p>
          </div>
        </div>
      </section>

      <!-- 第六章：创新点与已知边界 -->
      <section v-else-if="store.currentId.value === 'innovation-boundaries'" class="chapter-stage" data-test="chapter-boundaries">
        <div class="chain-cards">
          <div class="chain-card">
            <h3>创新点</h3>
            <p>可复现建模链 + NetCDF 原生体渲染 + 证据驱动结论卡 + 公共有效集模型比较。</p>
          </div>
          <div class="chain-card">
            <h3>已知边界</h3>
            <p>局部坐标仅显示锚点（非真实地理配准）；发布登记为人工确认；瓦斯为稀疏采样解释性估计。</p>
          </div>
          <div class="chain-card">
            <h3>失败语义</h3>
            <p>服务离线、渲染失败、数据不可用均为类型化显式状态，绝不回退点云伪装体渲染。</p>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.presentation-view {
  min-height: calc(100vh - 52px);
  display: flex;
  flex-direction: column;
  background: var(--s1-canvas);
}

.chapter-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: var(--s1-space-4) var(--s1-space-6) var(--s1-space-6);
  gap: var(--s1-space-4);
}

.service-banner {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-warning);
  border: 1px solid rgba(217, 168, 78, 0.4);
  border-radius: var(--s1-radius-sm);
  padding: 8px 14px;
  background: rgba(217, 168, 78, 0.08);
}

.chapter-stage {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-4);
}

.case-chapter {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  grid-template-rows: minmax(0, 1fr);
}

.case-chapter :deep(.scene-panel) {
  min-height: 480px;
}

.case-chapter :deep(.async-state) {
  grid-column: 1 / -1;
}

.chapter-findings {
  overflow-y: auto;
  min-width: 0;
}

.chain-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--s1-space-4);
}

.chain-card {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  padding: var(--s1-space-4);
}

.chain-card h3 {
  margin: 0 0 var(--s1-space-2);
  font-size: var(--s1-font-lg);
  color: var(--s1-gold);
}

.chain-card p {
  margin: 0;
  font-size: var(--s1-font-md);
  color: var(--s1-text-dim);
  line-height: var(--s1-leading);
}

.chapter-note {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-faint);
}

.demo-link {
  display: inline-block;
  margin-top: var(--s1-space-2);
  color: var(--s1-cyan-strong);
  font-size: var(--s1-font-sm);
}

/* 章节切换过渡（reduced-motion 时由全局 token 归零） */
.chapter-stage {
  animation: chapter-in var(--s1-motion-panel) var(--s1-ease-out);
}

@keyframes chapter-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@media (max-width: 960px) {
  .case-chapter {
    grid-template-columns: 1fr;
  }
}
</style>

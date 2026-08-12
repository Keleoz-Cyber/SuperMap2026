<script setup lang="ts">
// v0.9.0：首页综合指挥舱。案例轨 + 中央三维主舞台 + 关键发现 + 底部证据带。
// 数据流：fetchCases → 选中案例 fetchCaseWorkspace → 主数据版本已验证时
// fetchAnalysisSummary；身份一律来自所选案例的 DTO，绝不跨案例取用。
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight } from '@element-plus/icons-vue'
import { ApiError, fetchAnalysisSummary, fetchCases, fetchCaseWorkspace, trashCase } from '../api/client'
import type {
  AnalysisSummaryResponse,
  CaseSummary,
  CaseWorkspaceSummary,
} from '../api/types'
import { CASE_PRESENTATION, resolveCaseProfile } from '../domain/casePresentation'
import { buildPresentationFindings } from '../domain/findings'
import type { PresentationFinding } from '../domain/findings'
import { clearShellContext, setShellContext } from '../stores/shellContext'
import CaseRail from '../components/shell/CaseRail.vue'
import CommandCenterScene from '../components/home/CommandCenterScene.vue'
import CommandCenterEvidence from '../components/home/CommandCenterEvidence.vue'
import FindingPanel from '../components/findings/FindingPanel.vue'
import AsyncState from '../components/states/AsyncState.vue'
import { coordinateLabel } from '../utils/modelingLabels'

const router = useRouter()
const route = useRoute()

const cases = ref<CaseSummary[]>([])
const loading = ref(true)
const loadError = ref<string | null>(null)

const selectedCaseId = ref<string | null>(null)
const workspace = ref<CaseWorkspaceSummary | null>(null)
const workspaceLoading = ref(false)
const workspaceError = ref<string | null>(null)
const analysis = ref<AnalysisSummaryResponse | null>(null)
const analysisLoading = ref(false)

// 单调请求序号：旧响应（成功/失败/finally）一律不得覆盖新选择的状态
let requestSeq = 0

const selectedCase = computed(
  () => cases.value.find((c) => c.case_id === selectedCaseId.value) ?? null,
)

// v0.9.0 修复：手机档三维不内嵌首屏，改为显式全屏打开/关闭（JS 只承载
// 显式全屏状态，不做视口内容分支）
const phoneSceneOpen = ref(false)

const profile = computed(() => resolveCaseProfile(selectedCase.value?.provenance_summary))
const presentation = computed(() => CASE_PRESENTATION[profile.value])

// 成果身份：工作台 DTO 优先（official_result 即正式/主打成果链接），
// 未 seed 描述卡回退到卡片字段；绝不拼接他案例成果
const sceneResult = computed(() => {
  const ws = workspace.value
  if (ws) return ws.official_result ?? ws.featured_result ?? null
  const c = selectedCase.value
  return c?.official_result ?? c?.featured_result ?? null
})

const findings = computed<PresentationFinding[]>(() =>
  analysis.value ? buildPresentationFindings(analysis.value) : [],
)

interface PrimaryAction {
  label: string
  url: string
}

function appRoute(url: string): string {
  return url.startsWith('/#/') ? url.slice(2) : url
}

// 每个案例恰好一个主动作（设计 §5.2）：官方案例进入案例分析；
// 用户项目按权威 data_preparation 状态给出继续数据准备/继续建模
const primaryAction = computed<PrimaryAction | null>(() => {
  const c = selectedCase.value
  if (!c) return null
  const kind = c.workspace_kind ?? (c.source_kind === 'upload' ? 'user_upload' : 'builtin_legacy')
  if (kind === 'user_upload') {
    const prep = workspace.value?.data_preparation
    if (prep && prep.state !== 'ready' && prep.state !== 'validated') {
      return {
        label: '继续数据准备',
        url: prep.next_action.url ?? `/cases/${c.case_id}`,
      }
    }
    return { label: '继续建模', url: `/cases/${c.case_id}` }
  }
  return { label: '进入案例分析', url: `/cases/${c.case_id}` }
})

function openPrimaryAction() {
  const action = primaryAction.value
  if (!action) return
  void router.push(appRoute(action.url))
}

const coordinateNote = computed(() => {
  const kind = selectedCase.value?.provenance_summary?.coordinate_kind
  return typeof kind === 'string' ? coordinateLabel(kind) : '局部坐标'
})

async function loadCases() {
  loading.value = true
  loadError.value = null
  try {
    const resp = await fetchCases()
    cases.value = resp.cases
    if (!selectedCaseId.value && resp.cases.length > 0) {
      await selectCase(resp.cases[0].case_id)
    }
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function selectCase(caseId: string) {
  if (selectedCaseId.value === caseId && workspace.value) return
  selectedCaseId.value = caseId
  const seq = ++requestSeq
  const isCurrent = () => seq === requestSeq && selectedCaseId.value === caseId

  workspace.value = null
  analysis.value = null
  workspaceError.value = null
  workspaceLoading.value = true
  analysisLoading.value = false
  try {
    const ws = await fetchCaseWorkspace(caseId)
    if (!isCurrent()) return
    workspace.value = ws
    workspaceLoading.value = false
    // 主数据版本已验证才加载分析摘要；否则发现/证据带保持真实空态
    if (ws.primary_dataset && ws.primary_dataset.status === 'validated') {
      analysisLoading.value = true
      try {
        const summary = await fetchAnalysisSummary(ws.primary_dataset.id)
        if (!isCurrent()) return
        analysis.value = summary
      } catch {
        // 分析不可用不阻断三维与基本信息（模块级降级由证据带空态表达）
        if (isCurrent()) analysis.value = null
      } finally {
        if (isCurrent()) analysisLoading.value = false
      }
    }
  } catch (e) {
    if (!isCurrent()) return
    workspaceError.value =
      e instanceof ApiError ? `${e.code}：${e.message}` : e instanceof Error ? e.message : String(e)
    workspaceLoading.value = false
  }
}

async function focusCasesRail() {
  await nextTick()
  const rail = document.querySelector<HTMLElement>('[data-test="case-rail"]')
  if (!rail) return
  rail.focus({ preventScroll: true })
  rail.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
}

async function handleTrashCase(caseId: string) {
  try {
    await trashCase(caseId)
    if (selectedCaseId.value === caseId) {
      selectedCaseId.value = null
      workspace.value = null
      analysis.value = null
    }
    await loadCases()
  } catch {
    // 回收站操作失败不阻断首页浏览
  }
}

// 发现 → 三维定位：携带轴/区间/数据身份深链到成果页，成果页消费查询参数
function locateFinding(finding: PresentationFinding) {
  const target = finding.spatialTarget
  const resultId = target?.resultId ?? sceneResult.value?.result_id
  if (!target || !resultId) return
  const query: Record<string, string> = {}
  if (workspace.value?.primary_dataset) query.dataset = workspace.value.primary_dataset.id
  if (target.axis === 'xy' && target.xRange && target.yRange) {
    query.axis = 'xy'
    query.x_range = `${target.xRange[0]},${target.xRange[1]}`
    query.y_range = `${target.yRange[0]},${target.yRange[1]}`
  } else if ((target.axis === 'x' || target.axis === 'y' || target.axis === 'z') && target.range) {
    query.axis = target.axis
    query.range = `${target.range[0]},${target.range[1]}`
  }
  void router.push({ path: `/results/${resultId}`, query })
}

onMounted(loadCases)

watch(
  [() => route.query.focus, cases],
  ([focus, availableCases]) => {
    if (focus === 'cases' && availableCases.length > 0) void focusCasesRail()
  },
  { immediate: true },
)

// 壳上下文：选中案例身份登记到全局头；离开首页即清理
watch(
  [selectedCase, presentation],
  ([c, p]) => {
    if (c) {
      setShellContext({
        caseId: c.case_id,
        caseTitle: c.title,
        stageLabel: '指挥舱',
        caseAccent: p.accent,
      })
    } else {
      clearShellContext()
    }
  },
  { immediate: true },
)
onBeforeUnmount(clearShellContext)
</script>

<template>
  <div
    class="command-center"
    :class="{ 'scene-open': phoneSceneOpen }"
    :data-case-accent="presentation.accent"
    data-test="command-center"
  >
    <AsyncState
      v-if="loadError"
      kind="error"
      title="案例列表加载失败"
      :impact="loadError"
      next-action="检查全局栏服务状态后刷新重试"
    />
    <AsyncState v-else-if="loading && cases.length === 0" kind="loading" title="案例加载中" />

    <div v-else class="cc-grid">
      <CaseRail
        :cases="cases"
        :selected-case-id="selectedCaseId"
        @select="selectCase"
        @trash="handleTrashCase"
      />

      <CommandCenterScene
        :case-title="selectedCase?.title ?? '未选择案例'"
        :variable-label="presentation.variableLabel"
        :unit-label="typeof selectedCase?.provenance_summary?.value_unit === 'string' ? selectedCase.provenance_summary.value_unit : null"
        :narrative-label="presentation.narrativeLabel"
        :coordinate-note="coordinateNote"
        :result-id="sceneResult?.result_id ?? null"
        :result-url="sceneResult?.url ?? null"
        :loading="workspaceLoading"
        :error="workspaceError"
      >
        <template #actions>
          <button
            v-if="primaryAction"
            type="button"
            class="cc-primary"
            data-test="command-primary-action"
            data-primary-action="true"
            @click="openPrimaryAction"
          >
            {{ primaryAction.label }}
            <el-icon :size="13"><ArrowRight /></el-icon>
          </button>
        </template>
      </CommandCenterScene>

      <aside class="cc-findings" data-test="home-findings" aria-label="关键发现">
        <h3 class="findings-title">关键发现</h3>
        <AsyncState v-if="analysisLoading" kind="loading" title="分析加载中" />
        <FindingPanel v-else :findings="findings" @locate="locateFinding" />
      </aside>

      <CommandCenterEvidence
        class="cc-evidence"
        :summary="analysis"
        :loading="analysisLoading"
      />

      <!-- 手机档专用：全屏三维入口（桌面档隐藏，内嵌主舞台直接在网格中） -->
      <div class="cc-phone-entry" data-test="phone-scene-entry">
        <template v-if="sceneResult">
          <p class="entry-note">三维成果：{{ sceneResult.materialized ? '已物化' : '未物化' }}</p>
          <button
            type="button"
            class="phone-scene-btn"
            data-test="phone-open-scene"
            @click="phoneSceneOpen = true"
          >
            打开全屏三维
          </button>
        </template>
        <p v-else class="entry-note">暂无成果：完成建模实验后可查看三维成果。</p>
      </div>

      <button
        v-if="phoneSceneOpen"
        type="button"
        class="phone-scene-close"
        data-test="phone-close-scene"
        aria-label="关闭全屏三维"
        @click="phoneSceneOpen = false"
      >
        关闭三维 ✕
      </button>
    </div>
  </div>
</template>

<style scoped>
.command-center {
  /* AppShell 的 app-main 为块级且有确定高度（flex 拉伸），此处直接占满 */
  height: 100%;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.cc-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 264px minmax(0, 1fr) 300px;
  grid-template-rows: minmax(0, 1fr) auto;
  grid-template-areas:
    'rail scene findings'
    'evidence evidence evidence';
  gap: var(--s1-space-4);
  padding: var(--s1-space-4) var(--s1-space-6) var(--s1-space-6);
}

.cc-grid > .case-rail {
  grid-area: rail;
}

.cc-grid > .scene-panel {
  grid-area: scene;
}

.cc-findings {
  grid-area: findings;
  min-width: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-3);
}

.findings-title {
  margin: 0;
  font-size: var(--s1-font-xs);
  font-weight: 600;
  letter-spacing: 0.1em;
  color: var(--s1-text-faint);
}

.cc-evidence {
  grid-area: evidence;
}

.cc-primary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--s1-font-md);
  font-weight: 600;
  color: #06110f;
  background: var(--s1-case-accent);
  border: none;
  border-radius: var(--s1-radius-sm);
  padding: 7px 16px;
  cursor: pointer;
  transition:
    filter var(--s1-motion-fast) var(--s1-ease-out),
    transform var(--s1-motion-fast) var(--s1-ease-out);
}

.cc-primary:hover {
  filter: brightness(1.12);
  transform: translateY(-1px);
}

@media (max-width: 1200px) {
  .cc-grid {
    grid-template-columns: 232px minmax(0, 1fr) 260px;
  }
}

@media (max-width: 960px) {
  .cc-grid {
    grid-template-columns: 220px minmax(0, 1fr);
    grid-template-areas:
      'rail scene'
      'findings findings'
      'evidence evidence';
  }

  .cc-findings {
    max-height: 320px;
  }
}

@media (max-width: 480px) {
  .cc-grid {
    display: flex;
    flex-direction: column;
    padding: var(--s1-space-3);
    gap: var(--s1-space-3);
  }

  /* 手机档信息顺序：案例选择 → 案例摘要（场景头部）→ 关键发现 →
     证据带 → 全屏三维入口；内嵌三维画面不先于发现出现 */
  .cc-grid > .case-rail {
    order: 1;
  }

  .cc-grid > .scene-panel {
    order: 2;
  }

  .cc-findings {
    order: 3;
    max-height: none;
  }

  .cc-evidence {
    order: 4;
  }

  .cc-phone-entry {
    order: 5;
  }

  /* 默认只显示场景摘要头，隐藏内嵌三维画面
     （:deep：scene-body 属于子组件， scoped 属性只落在子组件根上） */
  .cc-grid > .scene-panel :deep(.scene-body) {
    display: none;
  }

  /* 全屏打开：同一面板转为视口覆盖，iframe 不重建 */
  .scene-open .cc-grid > .scene-panel {
    position: fixed;
    inset: 0;
    z-index: 2000;
    border-radius: 0;
  }

  .scene-open .cc-grid > .scene-panel :deep(.scene-body) {
    display: flex;
  }

  .phone-scene-close {
    position: fixed;
    top: 10px;
    right: 10px;
    z-index: 2100;
    border: 1px solid var(--s1-border-strong);
    border-radius: 999px;
    background: var(--s1-surface-glass);
    color: var(--s1-text);
    font-size: var(--s1-font-sm);
    padding: 6px 14px;
    cursor: pointer;
  }
}

/* 手机入口卡默认隐藏（桌面档主舞台内嵌） */
.cc-phone-entry {
  display: none;
}

@media (max-width: 480px) {
  .cc-phone-entry {
    display: flex;
    flex-direction: column;
    gap: var(--s1-space-2);
    border: 1px solid var(--s1-border);
    border-radius: var(--s1-radius-md);
    background: var(--s1-surface-1);
    padding: var(--s1-space-3);
  }

  .entry-note {
    margin: 0;
    font-size: var(--s1-font-sm);
    color: var(--s1-text-dim);
  }

  .phone-scene-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    font-size: var(--s1-font-md);
    font-weight: 600;
    color: #06110f;
    background: var(--s1-case-accent);
    border: none;
    border-radius: var(--s1-radius-sm);
    padding: 10px 16px;
    cursor: pointer;
  }
}
</style>

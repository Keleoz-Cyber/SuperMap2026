<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ApiError, fetchCaseWorkspace } from '../api/client'
import type { CaseWorkspaceSummary } from '../api/types'
import DataPreparationPanel from '../components/cases/DataPreparationPanel.vue'
import RhoCaseView from './RhoCaseView.vue'

// v0.7.0：统一案例工作台壳——三种来源（builtin_legacy / builtin_preset /
// user_upload）共用同一页头、概览/数据/实验/成果四区与命令位置；
// 案例专有内容以只读子块注入（电阻率 → 内嵌 RhoCaseView）。
const route = useRoute()
const router = useRouter()
const caseId = computed(() => String(route.params.caseId))

const workspace = ref<CaseWorkspaceSummary | null>(null)
const loadError = ref<string | null>(null)
const notInitialized = ref(false)
const loading = ref(true)

const KIND_LABELS: Record<CaseWorkspaceSummary['workspace_kind'], string> = {
  builtin_legacy: '内置案例',
  builtin_preset: 'CSV 预置',
  user_upload: '用户上传',
}

const kindLabel = computed(() =>
  workspace.value ? KIND_LABELS[workspace.value.workspace_kind] : '',
)

const canOpenOfficial = computed(
  () =>
    !!workspace.value &&
    workspace.value.capabilities.official_result &&
    workspace.value.official_result !== null,
)
const canCreateExperiment = computed(
  () =>
    !!workspace.value &&
    workspace.value.capabilities.experiments &&
    workspace.value.primary_dataset !== null,
)
const officialAbnormal = computed(
  () =>
    !!workspace.value &&
    workspace.value.capabilities.official_result &&
    workspace.value.official_result === null,
)
const isResistivity = computed(
  () => workspace.value?.workspace_kind === 'builtin_legacy' && caseId.value === 'resistivity',
)
const mapping = computed(() => {
  const profile = workspace.value?.primary_dataset?.profile as
    | { mapping?: Record<string, unknown>; row_count?: number; valid_row_count?: number }
    | undefined
  return profile?.mapping ?? null
})
const rowCounts = computed(() => {
  const profile = workspace.value?.primary_dataset?.profile as
    | { row_count?: number; valid_row_count?: number; invalid_row_count?: number }
    | undefined
  return profile ?? null
})

function openOfficialResult() {
  const url = workspace.value?.official_result?.url
  if (url) router.push(url)
}
function createExperiment() {
  const datasetId = workspace.value?.primary_dataset?.id
  void router.push({
    path: `/cases/${caseId.value}/experiments/new`,
    query: datasetId ? { dataset: datasetId } : {},
  })
}

// 单调递增请求序号：只有最新一次 loadWorkspace 可以写状态；
// 快速连切时旧请求无论成功、失败还是 finally 都不得覆盖新请求
let workspaceRequestSeq = 0

async function loadWorkspace() {
  const targetId = caseId.value
  const seq = ++workspaceRequestSeq
  const isCurrent = () => seq === workspaceRequestSeq && targetId === caseId.value
  loading.value = true
  workspace.value = null
  loadError.value = null
  notInitialized.value = false
  try {
    const result = await fetchCaseWorkspace(targetId)
    if (!isCurrent()) return
    workspace.value = result
  } catch (exc) {
    if (!isCurrent()) return
    if (exc instanceof ApiError && exc.code === 'PRESET_NOT_INITIALIZED') {
      notInitialized.value = true
    } else {
      loadError.value = exc instanceof Error ? exc.message : String(exc)
    }
  } finally {
    if (isCurrent()) loading.value = false
  }
}

onMounted(loadWorkspace)

// 同一组件实例在 /cases/:caseId 之间复用：参数变化必须重新加载，
// 绝不显示上一个案例的 stale 内容
watch(caseId, (next, prev) => {
  if (next !== prev) void loadWorkspace()
})
</script>

<template>
  <div class="case-workspace-page">
    <div v-if="notInitialized" class="workspace-state" data-test="workspace-not-initialized">
      <el-result
        icon="warning"
        title="微震预置案例尚未初始化"
        sub-title="需由维护者执行文档化 seed 命令；初始化完成后官方普通克里金成果自动可用，无需任何用户操作。"
      >
        <template #extra>
          <el-button type="primary" data-test="back-home" @click="router.push('/')">
            返回首页
          </el-button>
        </template>
      </el-result>
    </div>

    <div v-else-if="loadError" class="workspace-state" data-test="workspace-load-error">
      <el-result icon="error" title="案例工作台加载失败" :sub-title="loadError">
        <template #extra>
          <el-button @click="router.push('/')">返回首页</el-button>
        </template>
      </el-result>
    </div>

    <div v-else v-loading="loading">
      <template v-if="workspace">
        <header class="workspace-header" data-test="case-workspace-header">
          <div class="header-left">
            <el-button :icon="ArrowLeft" circle title="返回首页" @click="router.push('/')" />
            <div class="header-title">
              <h1>{{ workspace.title }} · 案例工作台</h1>
              <p class="header-sub">
                <el-tag size="small" effect="dark" round>{{ kindLabel }}</el-tag>
                <span v-if="workspace.provenance_summary.data_form">
                  {{ workspace.provenance_summary.data_form }}
                </span>
                <span v-if="workspace.provenance_summary.value_unit">
                  单位：{{ workspace.provenance_summary.value_unit }}
                </span>
                <span v-if="workspace.provenance_summary.coordinate_kind">
                  坐标：{{ workspace.provenance_summary.coordinate_kind }}
                </span>
              </p>
            </div>
          </div>
        </header>

        <section class="workspace-section" data-test="workspace-overview">
          <h2 class="section-title">概览</h2>
          <p v-if="officialAbnormal" class="warn-line" data-test="official-abnormal">
            官方成果准备异常：已声明官方成果能力但缺少可用成果链接。
          </p>
          <div class="command-row">
            <el-button
              v-if="canOpenOfficial"
              type="primary"
              data-test="open-official-result"
              @click="openOfficialResult"
            >
              {{ workspace.workspace_kind === 'builtin_preset' ? '查看官方成果' : '查看成果' }}
            </el-button>
            <el-button
              v-if="canCreateExperiment"
              data-test="new-experiment"
              @click="createExperiment"
            >
              新建实验
            </el-button>
          </div>
        </section>

        <section class="workspace-section" data-test="workspace-data">
          <h2 class="section-title">数据</h2>
          <template v-if="workspace.primary_dataset">
            <p>
              数据版本 v{{ workspace.primary_dataset.version }} · 状态
              {{ workspace.primary_dataset.status }}
              <template v-if="rowCounts?.row_count">
                · 行数 {{ rowCounts.row_count }}
                <template v-if="rowCounts.valid_row_count !== undefined">
                  （有效 {{ rowCounts.valid_row_count }}）
                </template>
              </template>
            </p>
            <p v-if="mapping">
              字段：{{ mapping.x }}/{{ mapping.y }}/{{ mapping.z }} → {{ mapping.value }}（
              {{ mapping.value_name }}<template v-if="mapping.value_unit">
                ，{{ mapping.value_unit }}</template
              >）
            </p>
          </template>
          <p v-else>当前没有可查看的数据版本。</p>
          <p v-if="workspace.provenance_summary.badge" class="provenance-line">
            {{ workspace.provenance_summary.badge }}
          </p>
          <DataPreparationPanel
            v-if="workspace.data_preparation"
            :preparation="workspace.data_preparation"
            :case-id="caseId"
          />
        </section>

        <section class="workspace-section" data-test="workspace-experiments">
          <h2 class="section-title">实验</h2>
          <p v-if="canCreateExperiment">可基于当前数据版本创建通用建模实验。</p>
          <p v-else>当前案例不开放新建实验。</p>
        </section>

        <section class="workspace-section" data-test="workspace-results">
          <h2 class="section-title">成果</h2>
          <p v-if="workspace.official_result">
            {{ workspace.workspace_kind === 'builtin_preset' ? '官方成果' : '主打成果' }}：
            <el-link type="primary" @click="openOfficialResult">
              {{ workspace.official_result.url }}
            </el-link>
            （{{ workspace.official_result.materialized ? '已物化' : '未物化' }}）
          </p>
          <p v-else-if="workspace.workspace_kind !== 'builtin_legacy'" data-test="results-empty">
            暂无成果。
          </p>
          <div v-if="isResistivity" class="rho-block" data-test="workspace-rho-block">
            <RhoCaseView embedded />
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.case-workspace-page {
  min-height: 100vh;
  background: #0f141c;
  color: #d5dde8;
  padding: 16px 24px 40px;
}
.workspace-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.header-title h1 {
  margin: 0;
  font-size: 20px;
}
.header-sub {
  display: flex;
  gap: 12px;
  align-items: center;
  margin: 6px 0 0;
  color: #93a1b3;
  font-size: 13px;
}
.workspace-section {
  background: #151c26;
  border: 1px solid #263142;
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 14px;
}
.section-title {
  margin: 0 0 10px;
  font-size: 15px;
  color: #9db4d0;
}
.command-row {
  display: flex;
  gap: 10px;
}
.warn-line {
  color: #e6a23c;
}
.provenance-line {
  color: #7f8ca0;
  font-size: 12px;
}
.rho-block {
  margin-top: 10px;
}
</style>

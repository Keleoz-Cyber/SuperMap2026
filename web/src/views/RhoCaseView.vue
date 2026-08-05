<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import {
  ApiError,
  createLegacyRhoRenderAsset,
  fetchLegacyRhoRenderAsset,
  fetchLegacyRhoRenderCapability,
  fetchRhoCase,
  fetchRhoPoints,
  fetchRhoPublishStatus,
  importLegacyRhoRenderSource,
} from '../api/client'
import type {
  LegacyRenderSourceRegistration,
  PublishStatus,
  RenderCapability,
  RhoCaseDetail,
  RhoPoints,
} from '../api/types'
import NativeVolumePanel from '../components/rendering/NativeVolumePanel.vue'
import type {
  NativeVolumeAuxPoints,
  NativeVolumeRenderApi,
} from '../components/rendering/NativeVolumePanel.vue'
import LeaderboardPanel from '../components/LeaderboardPanel.vue'
import EvidenceChainPanel from '../components/EvidenceChainPanel.vue'
import ServiceStatusPanel from '../components/ServiceStatusPanel.vue'
import IssuesPanel from '../components/IssuesPanel.vue'

// v0.7.0：embedded 时隐藏本页顶栏（统一工作台壳提供页头）
const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

const router = useRouter()

const detail = ref<RhoCaseDetail | null>(null)
const publishStatus = ref<PublishStatus | null>(null)
const lineage = ref<RhoPoints | null>(null)
const loading = ref(true)
const probing = ref(false)
const loadError = ref<string | null>(null)
const leftCollapsed = ref(false)
const rightCollapsed = ref(false)

const voxelBands = computed<number | null>(() => {
  if (!detail.value || !publishStatus.value) return null
  const result = detail.value.supermap.results.find(
    (r) => r.dataset === publishStatus.value?.result_id,
  )
  return result?.bands ?? null
})

// ---------------------------------------------------------------------------
// v0.6.1 NetCDF 原生体渲染：legacy 能力接线
// 原生体积能力一律以后端 render-capability GET 为准；
// publishStatus.planned_services.volume.available 只是历史 S3M 发布证据，
// 绝不作为原生体渲染能力，也不决定 NetCDF 资产成败。
// ---------------------------------------------------------------------------

const renderCapability = ref<RenderCapability | null>(null)

// 面板数据层以回调注入：能力/资产状态一律纯 GET，创建是唯一 POST；
// 能力响应同步到本视图，用于决定辅助视图说明的展示
const volumeApi: NativeVolumeRenderApi = {
  fetchCapability: async () => {
    const cap = await fetchLegacyRhoRenderCapability()
    renderCapability.value = cap
    return cap
  },
  fetchAsset: fetchLegacyRhoRenderAsset,
  createAsset: (retryFailed) => createLegacyRhoRenderAsset(retryFailed),
}

// 未登记规则三维网格时：测点访问保留为显式分离的辅助视图
const showAuxOnlyNotice = computed(() => renderCapability.value?.supported === false)

// ---------------------------------------------------------------------------
// 产品内显式导入入口：未登记（LEGACY_RENDER_SOURCE_NOT_REGISTERED）时显示
// 「导入权威规则网格」动作；列名/属性名/单位显式传入（默认 X/Y/Z/RHO）。
// 登记成功后入口不再显示（展示登记身份），面板重挂载走既有 NativeVolumePanel
// 生成资产流程；导入是唯一会 POST render-sources/import 的入口。
// ---------------------------------------------------------------------------

const panelKey = ref(0)
const importFile = ref<File | null>(null)
const importing = ref(false)
const importError = ref<string | null>(null)
const importIdentity = ref<LegacyRenderSourceRegistration | null>(null)
const importColumns = ref({ x: 'X', y: 'Y', z: 'Z', value: 'RHO' })
const importPropertyName = ref('RHO')
const importUnits = ref('unknown')

const showImportEntry = computed(
  () =>
    importIdentity.value === null &&
    renderCapability.value?.supported === false &&
    renderCapability.value.reason_code === 'LEGACY_RENDER_SOURCE_NOT_REGISTERED',
)

function onImportFileChange(event: Event) {
  importFile.value = (event.target as HTMLInputElement).files?.[0] ?? null
}

async function submitImport() {
  const file = importFile.value
  if (!file || importing.value) return
  importing.value = true
  importError.value = null
  try {
    const record = await importLegacyRhoRenderSource(file, {
      xColumn: importColumns.value.x,
      yColumn: importColumns.value.y,
      zColumn: importColumns.value.z,
      valueColumn: importColumns.value.value,
      propertyName: importPropertyName.value,
      units: importUnits.value,
    })
    importIdentity.value = record
    // 登记成功 → 能力翻转：重取能力并重挂载面板，走既有显式生成资产流程
    renderCapability.value = await fetchLegacyRhoRenderCapability()
    panelKey.value += 1
  } catch (e) {
    importError.value = e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
  } finally {
    importing.value = false
  }
}

// 既有测点仅作为 legacy-measurements 辅助层：坐标为局部米制，
// 由能力 GET 返回的只读 display_transform 定位，握手后由面板发送；
// 辅助采样点绝不参与连续体渲染
const legacyMeasurementPoints = computed<NativeVolumeAuxPoints | null>(() => {
  const pts = lineage.value
  if (!pts || pts.served === 0) return null
  return {
    id: 'legacy-measurements',
    role: 'auxiliary',
    x: pts.x,
    y: pts.y,
    z: pts.z,
    values: pts.values,
    style: { color: '#f59e0b', pixelSize: 5 },
  }
})

async function loadAll() {
  loading.value = true
  loadError.value = null
  try {
    const [d, ps, pts] = await Promise.all([
      fetchRhoCase(),
      fetchRhoPublishStatus(),
      // 重抽稀减小传输量：数据血统元数据 + legacy-measurements 辅助采样点共用
      fetchRhoPoints(40),
    ])
    detail.value = d
    publishStatus.value = ps
    lineage.value = pts
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function reprobe() {
  probing.value = true
  try {
    publishStatus.value = await fetchRhoPublishStatus()
  } catch (e) {
    console.warn('iServer 重新探测失败：', e)
  } finally {
    probing.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="case-page">
    <header v-if="!props.embedded" class="case-topbar">
      <div class="topbar-left">
        <el-button :icon="ArrowLeft" circle title="返回首页" @click="router.push('/')" />
        <div class="case-title">
          <h1>{{ detail?.title ?? '地下电阻率' }} · 三维工作台</h1>
          <p>{{ detail?.coordinate.note ?? '局部工程坐标 · EPSG 未确认 · Z 向下为负' }}</p>
        </div>
      </div>
      <div class="topbar-right">
        <template v-if="publishStatus">
          <el-tag
            :type="publishStatus.iserver_available ? 'success' : 'danger'"
            effect="dark"
            class="iserver-badge"
          >
            <span class="dot" :class="publishStatus.iserver_available ? 'ok' : 'bad'"></span>
            iServer {{ publishStatus.iserver_available ? '在线' : '离线' }}
          </el-tag>
          <span class="mono base-url">{{ publishStatus.iserver.base_url }}</span>
        </template>
        <el-button size="small" :icon="Refresh" :loading="probing" @click="reprobe">
          重新探测
        </el-button>
        <el-divider direction="vertical" />
        <el-button size="small" text @click="leftCollapsed = !leftCollapsed">
          {{ leftCollapsed ? '展开左栏' : '收起左栏' }}
        </el-button>
        <el-button size="small" text @click="rightCollapsed = !rightCollapsed">
          {{ rightCollapsed ? '展开右栏' : '收起右栏' }}
        </el-button>
      </div>
    </header>

    <div v-if="loadError" class="case-error">
      <el-result icon="error" title="案例数据加载失败" :sub-title="loadError">
        <template #extra>
          <el-button type="primary" @click="loadAll">重试</el-button>
        </template>
      </el-result>
    </div>

    <div
      v-else
      v-loading="loading"
      class="case-grid"
      :class="{ 'no-left': leftCollapsed, 'no-right': rightCollapsed }"
    >
      <aside v-if="!leftCollapsed" class="panel panel-left">
        <h2 class="panel-title">模型排行榜</h2>
        <LeaderboardPanel
          v-if="detail"
          :models="detail.models"
          :metric-source="detail.metric_source"
          :common-valid="detail.metric_expectations.common_valid"
          :common-nodata="detail.metric_expectations.common_nodata"
        />
      </aside>

      <section class="panel panel-center">
        <el-alert
          v-if="publishStatus && !publishStatus.iserver_available"
          type="warning"
          :closable="false"
          class="iserver-alert"
          title="iServer 当前不可用：服务发布与元数据验证处于可恢复的未验证状态；模型与数据不受影响"
        />
        <h2 class="panel-title">三维场景 · NetCDF 原生体渲染（内置电阻率）</h2>
        <el-alert
          v-if="showAuxOnlyNotice"
          type="warning"
          :closable="false"
          class="legacy-aux-notice"
          data-test="legacy-aux-notice"
        >
          <template #title>
            <p class="aux-notice-line">
              当前案例尚未登记可审计的规则三维网格，因此不支持 NetCDF 体渲染。
            </p>
            <p class="aux-notice-line">测点仅用于数据分布检查，不是体渲染。</p>
          </template>
        </el-alert>
        <div v-if="showImportEntry" class="legacy-import" data-test="legacy-import">
          <p class="import-lead">
            上传权威规则网格 CSV（每个笛卡尔格点恰好一行）完成登记后，即可生成 NetCDF
            体渲染资产；登记经过完整校验（笛卡尔完整性 / 规则轴 / 重复坐标 / 非有限值），
            绝不从散点重跑插值。
          </p>
          <div class="import-form">
            <input
              type="file"
              accept=".csv"
              class="import-file"
              data-test="legacy-import-file"
              @change="onImportFileChange"
            />
            <div class="import-mapping">
              <label class="import-field">
                X 列
                <input v-model="importColumns.x" class="import-input" data-test="import-x-column" />
              </label>
              <label class="import-field">
                Y 列
                <input v-model="importColumns.y" class="import-input" data-test="import-y-column" />
              </label>
              <label class="import-field">
                Z 列
                <input v-model="importColumns.z" class="import-input" data-test="import-z-column" />
              </label>
              <label class="import-field">
                属性列
                <input
                  v-model="importColumns.value"
                  class="import-input"
                  data-test="import-value-column"
                />
              </label>
              <label class="import-field">
                属性名
                <input
                  v-model="importPropertyName"
                  class="import-input"
                  data-test="import-property-name"
                />
              </label>
              <label class="import-field">
                单位
                <input v-model="importUnits" class="import-input" data-test="import-units" />
              </label>
            </div>
            <el-button
              type="primary"
              size="small"
              data-test="legacy-import-submit"
              :disabled="!importFile || importing"
              :loading="importing"
              @click="submitImport"
            >
              {{ importing ? '正在导入…' : '导入权威规则网格' }}
            </el-button>
          </div>
          <div v-if="importError" class="import-error" data-test="legacy-import-error">
            {{ importError }}
          </div>
        </div>
        <div
          v-if="importIdentity"
          class="legacy-import-identity"
          data-test="legacy-import-identity"
        >
          已登记权威规则网格：{{ importIdentity.source_id }}，形状
          {{ importIdentity.shape.join('×') }}，网格 SHA-256
          {{ importIdentity.grid_sha256.slice(0, 16) }}…（{{ importIdentity.artifact_dir }}）
        </div>
        <NativeVolumePanel :key="panelKey" :api="volumeApi" :aux-points="legacyMeasurementPoints" />
      </section>

      <aside v-if="!rightCollapsed" class="panel panel-right">
        <template v-if="publishStatus">
          <h2 class="panel-title">发布证据链</h2>
          <EvidenceChainPanel :states="publishStatus.evidence_chain.states" />
          <el-divider />
          <h2 class="panel-title">iServer 服务</h2>
          <ServiceStatusPanel :publish-status="publishStatus" :voxel-bands="voxelBands" />
          <el-divider />
          <h2 class="panel-title">失败与边界</h2>
          <IssuesPanel
            v-if="detail"
            :issues="detail.issues"
            :failed-results="publishStatus.failed_results"
          />
          <el-divider />
        </template>
        <h2 class="panel-title">数据血统</h2>
        <div v-if="lineage" class="lineage">
          <div class="kv">
            <span>来源</span>
            <el-tag size="small" effect="plain" class="mono">{{ lineage.source }}</el-tag>
          </div>
          <div class="kv">
            <span>源文件</span>
            <span class="mono break-all">{{ lineage.source_label }}</span>
          </div>
          <div class="kv">
            <span>SHA-256</span>
            <span class="mono">{{ lineage.sha256.slice(0, 12) }}…</span>
          </div>
          <div class="kv">
            <span>总点数</span>
            <b>{{ lineage.count.toLocaleString() }}</b>
          </div>
          <div class="kv">
            <span>RHO 值域</span>
            <b>{{ lineage.value_range[0].toFixed(2) }} ~ {{ lineage.value_range[1].toFixed(2) }}</b>
          </div>
          <div class="kv">
            <span>单位说明</span>
            <span>{{ lineage.unit_note }}</span>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.case-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.case-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--gmp-border-soft);
  background: var(--gmp-bg-soft);
  flex-wrap: wrap;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.case-title h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.case-title p {
  margin: 2px 0 0;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.iserver-badge {
  display: inline-flex;
  align-items: center;
}

.base-url {
  color: var(--gmp-text-dim);
}

.case-error {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.case-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr) 360px;
  gap: 14px;
  padding: 14px 16px;
  box-sizing: border-box;
}

.case-grid.no-left {
  grid-template-columns: minmax(0, 1fr) 360px;
}

.case-grid.no-right {
  grid-template-columns: 320px minmax(0, 1fr);
}

.case-grid.no-left.no-right {
  grid-template-columns: minmax(0, 1fr);
}

.panel {
  background: var(--gmp-panel);
  border: 1px solid var(--gmp-border-soft);
  border-radius: 12px;
  padding: 14px;
  overflow-y: auto;
  min-height: 0;
}

.panel-center {
  /* 原生面板为普通文档流内容（含 16:9 iframe 与控件），超高时滚动而非裁剪 */
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.iserver-alert {
  margin-bottom: 12px;
}

.legacy-aux-notice {
  margin-bottom: 12px;
}

.aux-notice-line {
  margin: 0;
  line-height: 1.6;
}

.legacy-import {
  border: 1px solid var(--gmp-border-soft);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.import-lead {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text-dim);
  line-height: 1.6;
}

.import-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
}

.import-file {
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.import-mapping {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.import-field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.import-input {
  width: 72px;
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: inherit;
  border-radius: 6px;
  padding: 4px 8px;
}

.import-error {
  border: 1px solid #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
}

.legacy-import-identity {
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 12px;
  font-family: ui-monospace, monospace;
  color: var(--gmp-text-dim);
  word-break: break-all;
}

.lineage {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.lineage .kv {
  display: flex;
  gap: 10px;
  font-size: 13px;
  line-height: 1.5;
}

.lineage .kv > span:first-child {
  flex: 0 0 60px;
  color: var(--gmp-text-faint);
  font-size: 12px;
  padding-top: 1px;
}

.lineage .kv b {
  font-weight: 600;
}

@media (max-width: 1300px) {
  .case-page {
    overflow: auto;
  }

  .case-grid,
  .case-grid.no-left,
  .case-grid.no-right,
  .case-grid.no-left.no-right {
    grid-template-columns: 1fr;
  }

  .panel-center {
    order: -1;
    min-height: 720px;
  }
}
</style>

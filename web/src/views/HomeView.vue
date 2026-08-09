<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { Component } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  Bell,
  Connection,
  Cpu,
  Delete,
  Monitor,
  MoreFilled,
  Odometer,
  Plus,
} from '@element-plus/icons-vue'
import {
  fetchCases,
  fetchRhoPublishStatus,
  fetchTrashCases,
  PLATFORM_DEMO_3D_DOWNLOAD_URL,
  trashCase,
} from '../api/client'
import { WEB_VERSION } from '../version'
import type { CaseSummary } from '../api/types'
import { formatDateTime } from '../utils/datetime'

interface CaseMeta {
  icon: Component
  enterable: boolean
  badgeType: 'success' | 'warning' | 'info'
  badgeText: string
}

// v0.8.0 第三批 Task 7：旧 legacy 瓦斯卡（旧体元流程的占位卡）是最后一张
// legacy 卡，已随预置退役；首页不再保留任何按 case_id 的 legacy 卡元数据，
// builtin_legacy 一律走 FALLBACK_META 兜底（当前后端已绝不出产 legacy 卡）。

const UPLOAD_META: CaseMeta = {
  icon: Cpu,
  enterable: true,
  badgeType: 'success',
  badgeText: '上传案例 · 可建模',
}

const FALLBACK_META: CaseMeta = {
  icon: Odometer,
  enterable: false,
  badgeType: 'info',
  badgeText: '未接入',
}

const router = useRouter()
const cases = ref<CaseSummary[]>([])
const loading = ref(true)
const loadError = ref<string | null>(null)
const iserverOnline = ref<boolean | null>(null)
const trashCount = ref(0)

type WorkspaceKind = 'builtin_legacy' | 'builtin_preset' | 'user_upload'

// v0.7.0：身份与动作只读 DTO（workspace_kind/capabilities/official_result），
// 不再按 case_id 分支业务流程；旧客户端缺少新字段时按 source_kind 回退。
function kindOf(c: CaseSummary): WorkspaceKind {
  if (c.workspace_kind) return c.workspace_kind
  return c.source_kind === 'upload' ? 'user_upload' : 'builtin_legacy'
}

function meta(c: CaseSummary): CaseMeta {
  const kind = kindOf(c)
  if (kind === 'user_upload') return UPLOAD_META
  if (kind === 'builtin_preset') {
    return {
      icon: Bell,
      enterable: true,
      badgeType: 'success',
      badgeText: String(
        c.provenance_summary?.badge ?? 'CSV 预置 · 官方普通克里金成果',
      ),
    }
  }
  return { ...FALLBACK_META, badgeText: c.status }
}

// v0.8.0：预置卡字段行逐字读 DTO provenance_summary.fields（如电阻率 X/Y/Z/RHO）；
// 不携带 fields 键的预置卡（微震）不渲染该行，显示保持不变
function presetFields(c: CaseSummary): string | null {
  const fields = c.provenance_summary?.fields
  if (!Array.isArray(fields) || fields.length === 0) return null
  if (fields.some((f) => typeof f !== 'string')) return null
  return fields.join('/')
}

function enter(c: CaseSummary) {
  if (!meta(c).enterable) return
  // v0.7.0：三类案例卡片点击统一进入案例工作台；实验/成果只走显式按钮
  void router.push(`/cases/${c.case_id}`)
}

// v0.7.0：上传卡的「新建实验」显式次操作（与查看成果/进入工作台分离）
function newExperiment(c: CaseSummary) {
  void router.push(`/cases/${c.case_id}/experiments/new`)
}

// v0.6.1：有主打成果的上传卡提供「查看体渲染成果」直达入口，与新建实验分离
function openFeaturedResult(c: CaseSummary) {
  if (!c.featured_result) return
  void router.push(c.featured_result.url)
}

// v0.7.0：预置卡的官方成果直达（与进入工作台主命令分离）
function openOfficialResult(c: CaseSummary) {
  if (!c.official_result) return
  void router.push(c.official_result.url)
}

onMounted(async () => {
  await loadCases()
  try {
    const ps = await fetchRhoPublishStatus()
    iserverOnline.value = ps.iserver_available
  } catch {
    iserverOnline.value = false
  }
  await loadTrashCount()
})

async function loadCases() {
  try {
    const resp = await fetchCases()
    cases.value = resp.cases
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function loadTrashCount() {
  try {
    const resp = await fetchTrashCases()
    trashCount.value = resp.cases.length
  } catch {
    trashCount.value = 0
  }
}

async function handleTrashCase(caseId: string) {
  try {
    await trashCase(caseId)
    await loadCases()
    await loadTrashCount()
  } catch {
    // 静默失败：回收站操作错误不阻断首页浏览
  }
}

function openCaseMenu(event: KeyboardEvent) {
  const target = event.target as HTMLElement
  target.click()
}
</script>

<template>
  <div class="home-page">
    <header class="home-header">
      <div class="home-header-inner">
        <div class="brand">
          <div class="brand-text">
            <h1>GeoModelingPlatform <span>地矿属性模拟与三维建模平台</span></h1>
          </div>
          <el-tag type="primary" effect="dark" round>v{{ WEB_VERSION }} 建模平台</el-tag>
          <router-link
            to="/trash"
            class="trash-entry"
            data-test="trash-entry"
          >
            <el-badge :value="trashCount" :hidden="trashCount === 0" :max="99">
              <el-icon :size="18"><Delete /></el-icon>
            </el-badge>
            <span>回收站</span>
          </router-link>
        </div>
        <p class="tagline">
          上传点数据即可完成二维/三维插值建模、空间验证与成果导出；内置电阻率、微震与瓦斯预置案例可直接查看官方成果并新建实验。
        </p>
      </div>
    </header>

    <main class="home-main">
      <div v-loading="loading" class="case-cards">
        <el-result
          v-if="loadError"
          icon="error"
          title="案例列表加载失败"
          :sub-title="loadError"
        />
        <div
          v-for="c in cases"
          :key="c.case_id"
          class="case-card"
          :class="{ disabled: !meta(c).enterable }"
          @click="enter(c)"
        >
          <div class="case-head">
            <el-icon :size="20" class="case-icon"><component :is="meta(c).icon" /></el-icon>
            <h2>{{ c.title }}</h2>
            <el-tag :type="meta(c).badgeType" effect="dark" size="small">
              {{ meta(c).badgeText }}
            </el-tag>
            <div v-if="kindOf(c) === 'user_upload'" class="card-overflow" @click.stop>
              <el-dropdown
                data-test="trash-case-btn"
                @command="handleTrashCase(c.case_id)"
              >
                <el-icon :size="18" class="overflow-trigger" role="button" aria-label="案例操作菜单" tabindex="0"
                  @keydown.enter.prevent="openCaseMenu"
                  @keydown.space.prevent="openCaseMenu"
                ><MoreFilled /></el-icon>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="trash">移入回收站</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
          <div class="case-body">
            <template v-if="kindOf(c) === 'user_upload'">
              <p><span>案例类型</span>{{ c.case_type ?? 'generic' }}</p>
              <p><span>创建时间</span>{{ formatDateTime(c.created_at ?? '') }}</p>
            </template>
            <template v-else-if="kindOf(c) === 'builtin_preset'">
              <p><span>数据形态</span>{{ c.provenance_summary?.data_form }}</p>
              <p v-if="presetFields(c)"><span>字段</span>{{ presetFields(c) }}</p>
              <p><span>坐标</span>{{ c.provenance_summary?.coordinate_kind }}</p>
              <p><span>单位</span>{{ c.provenance_summary?.value_unit }}</p>
            </template>
            <template v-else>
              <p><span>数据形态</span>{{ c.data_form }}</p>
              <p><span>坐标</span>{{ c.coordinate }}</p>
              <p><span>单位</span>{{ c.unit_note }}</p>
            </template>
          </div>
          <div v-if="c.v03_stage" class="case-stage">{{ c.v03_stage }}</div>
          <div class="case-foot">
            <template v-if="kindOf(c) === 'builtin_preset'">
              <el-button type="primary" data-test="enter-case-workspace" @click.stop="enter(c)">
                进入案例工作台
                <el-icon style="margin-left: 4px"><ArrowRight /></el-icon>
              </el-button>
              <el-button
                v-if="c.official_result"
                size="small"
                text
                data-test="open-official-result"
                @click.stop="openOfficialResult(c)"
              >
                查看官方成果
              </el-button>
            </template>
            <el-button
              v-else-if="kindOf(c) === 'builtin_legacy' && meta(c).enterable"
              type="primary"
              data-test="enter-case-workspace"
              @click.stop="enter(c)"
            >
              进入案例工作台
              <el-icon style="margin-left: 4px"><ArrowRight /></el-icon>
            </el-button>
            <template v-else-if="kindOf(c) === 'user_upload'">
              <template v-if="c.featured_result">
                <el-button
                  type="primary"
                  data-test="open-featured-result"
                  @click.stop="openFeaturedResult(c)"
                >
                  查看体渲染成果
                  <el-icon style="margin-left: 4px"><ArrowRight /></el-icon>
                </el-button>
                <el-button
                  size="small"
                  text
                  data-test="new-experiment"
                  @click.stop="newExperiment(c)"
                >
                  新建实验
                </el-button>
              </template>
              <el-button
                v-else
                type="primary"
                data-test="enter-case-workspace"
                @click.stop="enter(c)"
              >
                进入案例工作台
                <el-icon style="margin-left: 4px"><ArrowRight /></el-icon>
              </el-button>
            </template>
            <span v-else class="enter-hint">三维接入排期中</span>
          </div>
        </div>

        <router-link
          to="/cases/new"
          class="case-card create-card"
          data-test="create-case-card"
        >
          <div class="case-head">
            <el-icon :size="20" class="case-icon"><Plus /></el-icon>
            <h2>新建建模案例</h2>
          </div>
          <div class="case-body">
            <p>上传 CSV / XLSX 点数据，完成字段映射与质量校验后开始二维 / 三维插值调参。</p>
          </div>
          <div class="case-foot">
            <el-button type="primary" plain tag="span">
              上传数据
              <el-icon style="margin-left: 4px"><ArrowRight /></el-icon>
            </el-button>
            <a
              class="demo-download"
              data-test="download-demo-data"
              :href="PLATFORM_DEMO_3D_DOWNLOAD_URL"
              download
              @click.stop
            >
              下载演示数据
            </a>
          </div>
        </router-link>
      </div>
    </main>

    <footer class="arch-footer">
      <div class="arch-chain">
        <div class="chain-node">
          <el-icon :size="22"><Connection /></el-icon>
          <div>
            <b>SuperMap iServer</b>
            <span>数据 / 地图 / 三维服务发布</span>
          </div>
        </div>
        <el-icon class="chain-arrow"><ArrowRight /></el-icon>
        <div class="chain-node">
          <el-icon :size="22"><Cpu /></el-icon>
          <div>
            <b>FastAPI 后端</b>
            <span>模型登记 · 证据链 · 实时探测</span>
          </div>
        </div>
        <el-icon class="chain-arrow"><ArrowRight /></el-icon>
        <div class="chain-node">
          <el-icon :size="22"><Monitor /></el-icon>
          <div>
            <b>浏览器三维展示</b>
            <span>SuperMap3D NetCDF 原生体渲染</span>
          </div>
        </div>
        <div class="iserver-status">
          <span v-if="iserverOnline === null" class="dot pending"></span>
          <span v-else class="dot" :class="iserverOnline ? 'ok' : 'bad'"></span>
          {{ iserverOnline === null ? 'iServer 探测中…' : iserverOnline ? 'iServer 在线' : 'iServer 未连接' }}
        </div>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.home-page {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  overflow-x: hidden;
}

.home-header {
  border-bottom: 1px solid var(--gmp-border-soft);
  background: linear-gradient(180deg, #0e151d 0%, var(--gmp-bg) 100%);
}

.home-header-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 34px 28px 26px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 14px;
}

.brand h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.brand h1 span {
  font-size: 16px;
  font-weight: 500;
  color: var(--gmp-text-dim);
  margin-left: 10px;
}

.trash-entry {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: 8px;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid var(--gmp-border);
  background: var(--gmp-card);
  color: var(--gmp-text-dim);
  font-size: 13px;
  text-decoration: none;
  transition: border-color 0.2s, color 0.2s;
}

.trash-entry:hover {
  border-color: var(--gmp-accent);
  color: var(--gmp-accent);
}

.tagline {
  margin: 14px 0 0;
  color: var(--gmp-text-dim);
  font-size: 14px;
  line-height: 1.7;
}

.home-main {
  flex: 1;
  max-width: 1200px;
  width: 100%;
  margin: 0 auto;
  padding: 28px;
  box-sizing: border-box;
}

.case-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 18px;
  min-height: 200px;
}

.case-card {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  transition:
    border-color 0.2s,
    background 0.2s,
    transform 0.2s;
  text-decoration: none;
  color: inherit;
}

.case-card:not(.disabled) {
  cursor: pointer;
}

.case-card:not(.disabled):hover {
  border-color: var(--gmp-accent);
  background: var(--gmp-card-hover);
  transform: translateY(-2px);
}

.case-card.disabled {
  opacity: 0.55;
}

.create-card {
  border-style: dashed;
  cursor: pointer;
  text-decoration: none;
  color: inherit;
}

.demo-download {
  margin-left: 12px;
  font-size: 12px;
  color: var(--gmp-text-dim);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.demo-download:hover {
  color: var(--gmp-accent);
}

.case-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.case-icon {
  color: var(--gmp-accent);
}

.case-head h2 {
  margin: 0;
  font-size: 17px;
  flex: 1;
}

.card-overflow {
  display: flex;
  align-items: center;
  cursor: pointer;
}

.overflow-trigger {
  color: var(--gmp-text-faint);
  transition: color 0.2s;
}

.card-overflow:hover .overflow-trigger {
  color: var(--gmp-accent);
}

.case-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.case-body p {
  margin: 0;
  font-size: 13px;
  color: var(--gmp-text);
  line-height: 1.5;
}

.case-body p span {
  display: inline-block;
  width: 60px;
  color: var(--gmp-text-faint);
  font-size: 12px;
}

.case-stage {
  font-size: 12px;
  color: var(--gmp-text-dim);
  background: var(--gmp-bg-soft);
  border: 1px dashed var(--gmp-border);
  border-radius: 8px;
  padding: 8px 10px;
  line-height: 1.6;
}

.case-foot {
  margin-top: auto;
  display: flex;
  align-items: center;
  min-height: 32px;
}

.enter-hint {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.arch-footer {
  border-top: 1px solid var(--gmp-border-soft);
  background: var(--gmp-bg-soft);
}

.arch-chain {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 18px;
  flex-wrap: wrap;
}

.chain-node {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 10px;
  padding: 12px 16px;
  color: var(--gmp-accent);
}

.chain-node div {
  display: flex;
  flex-direction: column;
}

.chain-node b {
  font-size: 13px;
  color: var(--gmp-text);
}

.chain-node span {
  font-size: 12px;
  color: var(--gmp-text-dim);
}

.chain-arrow {
  color: var(--gmp-text-faint);
}

.iserver-status {
  font-size: 13px;
  color: var(--gmp-text-dim);
  padding: 8px 14px;
  border: 1px solid var(--gmp-border);
  border-radius: 999px;
  background: var(--gmp-card);
}

@media (max-width: 480px) {
  .home-header-inner {
    padding: 20px 16px 18px;
  }

  .brand {
    flex-wrap: wrap;
    gap: 8px 10px;
  }

  .brand h1 {
    font-size: 18px;
  }

  .brand h1 span {
    display: block;
    margin-left: 0;
    margin-top: 2px;
    font-size: 13px;
  }

  .brand .el-tag {
    font-size: 11px;
  }

  .trash-entry {
    margin-left: 0;
    padding: 4px 10px;
    font-size: 12px;
  }

  .tagline {
    font-size: 13px;
  }

  .home-main {
    padding: 16px;
  }

  .case-cards {
    grid-template-columns: 1fr;
    gap: 14px;
  }

  .case-card {
    padding: 16px;
  }

  .case-head h2 {
    font-size: 15px;
  }

  .arch-chain {
    padding: 16px;
    gap: 10px;
  }

  .chain-node {
    padding: 10px 12px;
  }
}
</style>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { Component } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  Bell,
  Connection,
  Cpu,
  Lock,
  Monitor,
  Odometer,
} from '@element-plus/icons-vue'
import { fetchCases, fetchRhoPublishStatus } from '../api/client'
import type { CaseSummary } from '../api/types'

interface CaseMeta {
  icon: Component
  enterable: boolean
  badgeType: 'success' | 'warning' | 'info'
  badgeText: string
}

const CASE_META: Record<string, CaseMeta> = {
  resistivity: {
    icon: Odometer,
    enterable: true,
    badgeType: 'success',
    badgeText: '进行中 · 可进入',
  },
  microseismic: {
    icon: Bell,
    enterable: false,
    badgeType: 'warning',
    badgeText: '审计底座已合并 · 第二案例',
  },
  gas: {
    icon: Lock,
    enterable: false,
    badgeType: 'info',
    badgeText: '暂缓',
  },
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

function meta(c: CaseSummary): CaseMeta {
  return CASE_META[c.case_id] ?? { ...FALLBACK_META, badgeText: c.status }
}

function enter(c: CaseSummary) {
  if (c.case_id === 'resistivity') {
    void router.push('/case/resistivity')
  }
}

onMounted(async () => {
  try {
    const resp = await fetchCases()
    cases.value = resp.cases
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
  try {
    const ps = await fetchRhoPublishStatus()
    iserverOnline.value = ps.iserver_available
  } catch {
    iserverOnline.value = false
  }
})
</script>

<template>
  <div class="home-page">
    <header class="home-header">
      <div class="home-header-inner">
        <div class="brand">
          <div class="brand-text">
            <h1>GeoModelingPlatform <span>地矿属性模拟与三维建模平台</span></h1>
          </div>
          <el-tag type="primary" effect="dark" round>超图杯 v0.3</el-tag>
        </div>
        <p class="tagline">
          以可复算流水线完成地矿属性三维建模，打通 SuperMap iDesktopX / iServer 的发布、验证与证据链闭环。
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
          </div>
          <div class="case-body">
            <p><span>数据形态</span>{{ c.data_form }}</p>
            <p><span>坐标</span>{{ c.coordinate }}</p>
            <p><span>单位</span>{{ c.unit_note }}</p>
          </div>
          <div class="case-stage">{{ c.v03_stage }}</div>
          <div class="case-foot">
            <el-button v-if="c.case_id === 'resistivity'" type="primary">
              进入三维工作台
              <el-icon style="margin-left: 4px"><ArrowRight /></el-icon>
            </el-button>
            <span v-else-if="c.case_id === 'gas'" class="enter-hint">
              体元加载触发 iDesktopX 崩溃，暂缓接入
            </span>
            <span v-else class="enter-hint">三维接入排期中</span>
          </div>
        </div>
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
            <span>iClient3D for Cesium 点云与场景</span>
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
</style>

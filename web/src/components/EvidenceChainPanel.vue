<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheckFilled, RemoveFilled } from '@element-plus/icons-vue'
import type { EvidenceState } from '../api/types'

const props = defineProps<{
  states: EvidenceState[]
}>()

const STATE_LABELS: Record<string, string> = {
  model_succeeded: '建模成功',
  artifact_exported: '成果导出',
  iserver_published: 'iServer 发布',
  service_metadata_verified: '服务元数据验证',
  browser_loaded: '浏览器加载',
  manual_visual_checked: '人工目检确认',
}

const SOURCE_LABELS: Record<string, string> = {
  registry: '登记表',
  live_probe: '实时探测',
  browser_report: '浏览器回执',
  manual: '人工记录',
  none: '无证据',
}

interface ChainItem extends EvidenceState {
  label: string
  sourceLabel: string
}

const items = computed<ChainItem[]>(() =>
  props.states.map((s) => ({
    ...s,
    label: STATE_LABELS[s.state] ?? s.state,
    sourceLabel: SOURCE_LABELS[s.source] ?? s.source,
  })),
)

const browserPending = computed(() =>
  props.states.some((s) => s.state === 'browser_loaded' && !s.ok),
)

function fmtTime(t: string | null): string {
  if (!t) return ''
  const d = new Date(t)
  return Number.isNaN(d.getTime()) ? t : d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="evidence-chain">
    <div v-for="(item, idx) in items" :key="item.state" class="chain-item">
      <div class="chain-rail">
        <span class="chain-icon" :class="{ ok: item.ok }">
          <el-icon v-if="item.ok"><CircleCheckFilled /></el-icon>
          <el-icon v-else><RemoveFilled /></el-icon>
        </span>
        <span v-if="idx < items.length - 1" class="chain-line"></span>
      </div>
      <div class="chain-body">
        <div class="chain-title">
          <span class="chain-label">{{ item.label }}</span>
          <el-tag size="small" :type="item.ok ? 'success' : 'info'" effect="plain">
            {{ item.sourceLabel }}
          </el-tag>
        </div>
        <el-tooltip
          :content="`${item.detail ?? '无详情'}${item.checked_at ? ' · ' + fmtTime(item.checked_at) : ''}`"
          placement="left"
          :show-after="150"
        >
          <div class="chain-detail">{{ item.detail ?? '无详情' }}</div>
        </el-tooltip>
      </div>
    </div>
    <el-alert
      v-if="browserPending"
      type="info"
      :closable="false"
      class="browser-pending"
      title="等待本浏览器完成一次场景渲染后自动回执"
    />
  </div>
</template>

<style scoped>
.evidence-chain {
  display: flex;
  flex-direction: column;
}

.chain-item {
  display: flex;
  gap: 10px;
}

.chain-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 20px;
  flex: none;
}

.chain-icon {
  font-size: 17px;
  color: var(--gmp-text-faint);
  line-height: 1;
  margin-top: 2px;
}

.chain-icon.ok {
  color: var(--gmp-green);
}

.chain-line {
  flex: 1;
  width: 2px;
  background: var(--gmp-border);
  margin: 4px 0;
  min-height: 14px;
}

.chain-body {
  flex: 1;
  min-width: 0;
  padding-bottom: 14px;
}

.chain-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.chain-label {
  font-size: 13px;
  font-weight: 600;
}

.chain-detail {
  margin-top: 4px;
  font-size: 12px;
  color: var(--gmp-text-dim);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  cursor: default;
}

.browser-pending {
  margin-top: 2px;
}
</style>

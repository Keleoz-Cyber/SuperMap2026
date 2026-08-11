<script setup lang="ts">
// v0.9.0：指挥舱中央三维主舞台。复用 NativeVolumePanel 与统一
// RenderAsset API（候选成果/官方成果同一链）；无正式成果时显示解释性
// 空态，绝不回退装饰性假场景或点云冒充体渲染。
import { computed } from 'vue'
import {
  createRenderAssetSliceExport,
  createResultRenderAsset,
  fetchRenderAssetSliceAnalysis,
  fetchResultRenderAsset,
  fetchResultRenderCapability,
} from '../../api/client'
import AsyncState from '../states/AsyncState.vue'
import NativeVolumePanel from '../rendering/NativeVolumePanel.vue'
import type { NativeVolumeRenderApi } from '../rendering/NativeVolumePanel.vue'

const props = defineProps<{
  caseTitle: string
  variableLabel: string
  unitLabel: string | null
  narrativeLabel: string
  coordinateNote: string
  // 当前案例的正式/主打成果身份；null 表示暂无成果
  resultId: string | null
  resultUrl: string | null
  loading: boolean
  error: string | null
}>()

// 渲染 API 按当前成果身份绑定；成果身份切换由父级 :key 强制重建面板
const api = computed<NativeVolumeRenderApi | null>(() => {
  if (!props.resultId) return null
  const resultId = props.resultId
  return {
    fetchCapability: () => fetchResultRenderCapability(resultId),
    fetchAsset: () => fetchResultRenderAsset(resultId),
    createAsset: (retryFailed) => createResultRenderAsset(resultId, retryFailed),
    fetchSliceAnalysis: fetchRenderAssetSliceAnalysis,
    createSliceExport: createRenderAssetSliceExport,
  }
})
</script>

<template>
  <section class="scene-panel" data-test="command-center-scene" aria-label="三维成果主舞台">
    <header class="scene-head">
      <div class="scene-title">
        <h2>{{ caseTitle }}</h2>
        <span class="scene-chip variable">{{ variableLabel }}<template v-if="unitLabel"> · {{ unitLabel }}</template></span>
        <span class="scene-chip">{{ narrativeLabel }}</span>
        <span class="scene-chip muted">{{ coordinateNote }}</span>
      </div>
      <div class="scene-actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="scene-body">
      <AsyncState
        v-if="loading"
        kind="loading"
        title="案例成果加载中"
      />
      <AsyncState
        v-else-if="error"
        kind="error"
        title="案例成果加载失败"
        :impact="error"
        next-action="切换其他案例或稍后重试"
      />
      <AsyncState
        v-else-if="!resultId"
        kind="empty"
        title="暂无成果"
        impact="该案例还没有已物化的正式三维成果"
        next-action="完成建模实验并产生候选后，此处自动展示正式成果连续体"
      />
      <NativeVolumePanel
        v-else-if="api"
        :key="resultId"
        :api="api"
        :show-ready-diagnostics="false"
      />
    </div>
  </section>
</template>

<style scoped>
.scene-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-lg);
  background: var(--s1-stage-bg);
  overflow: hidden;
}

.scene-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s1-space-3);
  padding: var(--s1-space-3) var(--s1-space-4);
  border-bottom: 1px solid var(--s1-border-soft);
  flex-wrap: wrap;
}

.scene-title {
  display: flex;
  align-items: center;
  gap: var(--s1-space-2);
  flex-wrap: wrap;
  min-width: 0;
}

.scene-title h2 {
  margin: 0;
  font-size: var(--s1-font-xl);
  font-weight: 700;
  color: var(--s1-text-strong);
}

.scene-chip {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
  border: 1px solid var(--s1-border);
  border-radius: 999px;
  padding: 2px 10px;
  white-space: nowrap;
}

.scene-chip.variable {
  color: var(--s1-case-accent);
  border-color: var(--s1-case-accent);
  font-weight: 600;
}

.scene-chip.muted {
  color: var(--s1-text-faint);
}

.scene-actions {
  display: flex;
  align-items: center;
  gap: var(--s1-space-2);
}

.scene-body {
  flex: 1;
  min-height: 380px;
  display: flex;
  flex-direction: column;
  position: relative;
}

.scene-body :deep(.async-state) {
  border: none;
  background: transparent;
  flex: 1;
}
</style>

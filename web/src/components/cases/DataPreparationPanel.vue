<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import type { DataPreparationSummary } from '../../api/types'

const props = defineProps<{
  preparation: DataPreparationSummary | null
  caseId: string
}>()

const router = useRouter()

const step = computed(() => props.preparation?.next_action.step ?? null)
const state = computed(() => props.preparation?.state ?? null)

const STATUS_LABELS: Record<string, string> = {
  needs_upload: '尚未上传数据',
  needs_mapping: '已上传待映射',
  needs_quality_review: '待质量确认',
  ready: '数据已就绪',
  blocked: '数据异常，需修复',
}

const statusLabel = computed(() =>
  state.value ? STATUS_LABELS[state.value] ?? state.value : '',
)

// 后端 URL 带 hash 前缀（/#/...），路由 push 需要剥除
function stripHashPrefix(url: string | null | undefined): string | null {
  if (!url) return null
  if (url.startsWith('/#/')) return url.slice(2)
  return url
}

function navigate() {
  if (!props.preparation) return
  const rawUrl = props.preparation.next_action.url
  const url = stripHashPrefix(rawUrl) ?? fallbackUrl()
  if (url) void router.push(url)
}

function fallbackUrl(): string | null {
  if (!props.preparation) return null
  switch (props.preparation.next_action.step) {
    case 'upload':
      return `/cases/${props.caseId}/datasets/new`
    default:
      return null
  }
}
</script>

<template>
  <div data-test="data-preparation-panel">
    <template v-if="preparation">
      <p class="prep-status" data-test="preparation-status">
        <span class="prep-label" data-test="preparation-label">{{ statusLabel }}</span>
      </p>
      <p v-if="state === 'blocked'" class="prep-error" data-test="prep-blocked">
        数据文件异常（{{ preparation.error?.code ?? '未知错误' }}），需修复后继续。
      </p>
      <div class="command-row">
        <el-button
          v-if="step === 'upload'"
          type="primary"
          data-test="prep-action-upload"
          @click="navigate"
        >
          上传数据
        </el-button>
        <el-button
          v-else-if="step === 'mapping' || step === 'quality_review'"
          type="primary"
          data-test="prep-action-continue"
          @click="navigate"
        >
          继续
        </el-button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.command-row {
  display: flex;
  gap: 10px;
}
.prep-status {
  margin: 0 0 6px;
  font-size: 13px;
}
.prep-label {
  font-weight: 600;
  color: var(--gmp-text, #d5dde8);
}
.prep-error {
  color: #e6a23c;
  font-size: 13px;
}
</style>

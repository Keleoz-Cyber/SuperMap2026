<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  ApiError,
  createResultRenderAsset,
  fetchResult,
  fetchResultRenderAsset,
  fetchResultRenderCapability,
  materializeResult,
} from '../../api/client'
import type {
  CandidateRecord,
  RenderAssetRecord,
  RenderCapability,
  RunRecord,
} from '../../api/types'

// v0.6.1：实验运行 succeeded 只表示交叉验证完成。成果可见性分四个独立阶段：
// 验证完成（run 终态）→ 规则网格物化（GET /results 探测）→ NetCDF 资产
// （render-assets/netcdf 状态机）→ 浏览器体渲染（只在成果工作台内可观测）。
// 本面板把这四个阶段分层摆到运行状态区，绝不把 succeeded 表述成已渲染。

const props = defineProps<{
  run: RunRecord | null
  candidates: CandidateRecord[]
}>()

const ASSET_POLL_INTERVAL_MS = 2000

// 与排行榜同一口径：成功候选按公共有效 RMSE 升序，首名为代表成果；
// 单候选实验自然落到唯一候选，主按钮一键直达成果工作台。
const featured = computed<CandidateRecord | null>(() => {
  const succeeded = props.candidates.filter((c) => c.status === 'succeeded')
  if (succeeded.length === 0) return null
  return [...succeeded].sort(
    (a, b) =>
      (a.metrics.rmse ?? Number.POSITIVE_INFINITY) - (b.metrics.rmse ?? Number.POSITIVE_INFINITY),
  )[0]
})

const visible = computed(() => props.run?.status === 'succeeded' && featured.value !== null)

// 物化阶段：探测失败与物化失败是两个不同入口（重新探测 / 重试物化）
type MaterializeStage =
  | 'probing'
  | 'probe_failed'
  | 'unmaterialized'
  | 'materializing'
  | 'materialize_failed'
  | 'materialized'

const materializeStage = ref<MaterializeStage>('probing')
const materializeError = ref<string | null>(null)

const capability = ref<RenderCapability | null>(null)
const capabilityChecked = ref(false)
const capabilityError = ref<string | null>(null)

const asset = ref<RenderAssetRecord | null>(null)
const assetError = ref<string | null>(null)
const assetBusy = ref(false)

let assetTimer: ReturnType<typeof setInterval> | null = null

function stopAssetPolling() {
  if (assetTimer !== null) {
    clearInterval(assetTimer)
    assetTimer = null
  }
}

function describeError(e: unknown): string {
  if (e instanceof ApiError) return `${e.code}：${e.message}`
  return e instanceof Error ? e.message : String(e)
}

function maybePollAsset(id: string) {
  stopAssetPolling()
  if (asset.value?.status === 'creating') {
    assetTimer = setInterval(() => {
      void refreshAsset(id)
    }, ASSET_POLL_INTERVAL_MS)
  }
}

// 资产状态刷新是纯 GET：404 表示尚未创建，绝不隐式 POST
async function refreshAsset(id: string) {
  try {
    asset.value = await fetchResultRenderAsset(id)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      asset.value = null
    } else {
      assetError.value = describeError(e)
    }
  }
  maybePollAsset(id)
}

async function probeAsset(id: string) {
  capability.value = null
  capabilityChecked.value = false
  capabilityError.value = null
  asset.value = null
  assetError.value = null
  try {
    capability.value = await fetchResultRenderCapability(id)
  } catch (e) {
    capabilityError.value = describeError(e)
    capabilityChecked.value = true
    return
  }
  capabilityChecked.value = true
  if (!capability.value.supported) return
  await refreshAsset(id)
}

async function probe(id: string) {
  stopAssetPolling()
  materializeStage.value = 'probing'
  materializeError.value = null
  capability.value = null
  capabilityChecked.value = false
  capabilityError.value = null
  asset.value = null
  assetError.value = null
  try {
    await fetchResult(id)
    materializeStage.value = 'materialized'
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      materializeStage.value = 'unmaterialized'
    } else {
      materializeStage.value = 'probe_failed'
      materializeError.value = describeError(e)
    }
    return
  }
  await probeAsset(id)
}

async function onMaterialize() {
  const id = featured.value?.id
  if (!id) return
  materializeStage.value = 'materializing'
  materializeError.value = null
  try {
    // 显式物化是唯一创建入口（POST 一次），成功后再探测资产阶段
    await materializeResult(id)
    materializeStage.value = 'materialized'
    await probeAsset(id)
  } catch (e) {
    materializeStage.value = 'materialize_failed'
    materializeError.value = describeError(e)
  }
}

async function onCreateAsset(retryFailed: boolean) {
  const id = featured.value?.id
  if (!id) return
  assetBusy.value = true
  assetError.value = null
  try {
    asset.value = await createResultRenderAsset(id, retryFailed)
    maybePollAsset(id)
  } catch (e) {
    assetError.value = describeError(e)
    // 失败后以 GET 同步持久化资产状态（failed 行含稳定错误码）
    await refreshAsset(id)
  } finally {
    assetBusy.value = false
  }
}

// 深链/刷新恢复：候选列表从服务端到达后即按代表候选重新探测
watch(
  () => (visible.value ? (featured.value?.id ?? null) : null),
  (id) => {
    if (id) void probe(id)
  },
  { immediate: true },
)

onBeforeUnmount(stopAssetPolling)
</script>

<template>
  <section v-if="visible" class="result-status" data-test="result-status">
    <div class="status-head">
      <h3>成果状态</h3>
      <router-link class="view-result" :to="`/results/${featured?.id}`" data-test="view-result">
        查看成果
      </router-link>
    </div>
    <p class="status-note" data-test="status-note">
      实验验证完成不等于三维成果已可查看；三维网格、体渲染数据和浏览器显示仍是独立阶段。
    </p>
    <ul class="stage-list">
      <li class="stage" data-test="stage-validation">
        <span class="stage-name">验证完成</span>
        <span class="stage-detail">{{ run?.finished_at ?? run?.updated_at }}</span>
      </li>
      <li class="stage" data-test="stage-materialize">
        <span class="stage-name">三维规则网格</span>
        <span v-if="materializeStage === 'probing'" class="stage-detail">状态探测中…</span>
        <span v-else-if="materializeStage === 'unmaterialized'" class="stage-detail">等待生成</span>
        <span v-else-if="materializeStage === 'materializing'" class="stage-detail">生成中…</span>
        <span v-else-if="materializeStage === 'materialized'" class="stage-detail ok">三维网格已生成</span>
        <span v-else class="stage-detail bad">
          {{ materializeStage === 'probe_failed' ? '状态探测失败' : '网格生成失败' }}
        </span>
        <button
          v-if="materializeStage === 'unmaterialized'"
          class="gmp-btn"
          data-test="materialize-result"
          @click="onMaterialize"
        >
          生成三维网格
        </button>
        <button
          v-if="materializeStage === 'materialize_failed'"
          class="gmp-btn"
          data-test="materialize-retry"
          @click="onMaterialize"
        >
          重试生成网格
        </button>
        <button
          v-if="materializeStage === 'probe_failed'"
          class="gmp-btn"
          data-test="materialize-reprobe"
          @click="featured && probe(featured.id)"
        >
          重新探测
        </button>
        <span v-if="materializeError" class="stage-error" data-test="materialize-error">
          {{ materializeError }}
        </span>
      </li>
      <li class="stage" data-test="stage-netcdf">
        <span class="stage-name">体渲染数据</span>
        <span v-if="materializeStage !== 'materialized'" class="stage-detail">
          待三维网格生成后进行
        </span>
        <template v-else>
          <span v-if="!capabilityChecked" class="stage-detail">能力探测中…</span>
          <template v-else-if="capabilityError">
            <span class="stage-detail bad">能力探测失败</span>
            <button
              class="gmp-btn"
              data-test="capability-reprobe"
              @click="featured && probeAsset(featured.id)"
            >
              重新探测
            </button>
            <span class="stage-error" data-test="capability-error">{{ capabilityError }}</span>
          </template>
          <span v-else-if="capability && !capability.supported" class="stage-detail">
            不适用：{{ capability.reason_code }}（{{ capability.reason }}）
          </span>
          <template v-else>
            <span v-if="asset === null" class="stage-detail">未生成</span>
            <span v-else-if="asset.status === 'creating'" class="stage-detail">创建中…</span>
            <span v-else-if="asset.status === 'ready'" class="stage-detail ok">
              已生成（{{ asset.renderer }}）
            </span>
            <span v-else class="stage-detail bad">生成失败</span>
            <button
              v-if="asset === null"
              class="gmp-btn"
              data-test="create-netcdf-asset"
              :disabled="assetBusy"
              @click="onCreateAsset(false)"
            >
              {{ assetBusy ? '正在准备…' : '准备体渲染数据' }}
            </button>
            <button
              v-if="asset && (asset.status === 'failed' || asset.status === 'interrupted')"
              class="gmp-btn"
              data-test="retry-netcdf-asset"
              :disabled="assetBusy"
              @click="onCreateAsset(true)"
            >
              {{ assetBusy ? '正在重试…' : '重试准备体渲染数据' }}
            </button>
            <span v-if="asset?.error" class="stage-error" data-test="asset-record-error">
              {{ asset.error.code }}：{{ asset.error.message }}
            </span>
            <span v-if="assetError" class="stage-error" data-test="asset-error">{{ assetError }}</span>
          </template>
        </template>
      </li>
      <li class="stage" data-test="stage-render">
        <span class="stage-name">浏览器体渲染</span>
        <span class="stage-detail">在成果工作台打开后可见（仅浏览器侧状态，服务端不记录）</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.result-status {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.status-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.status-head h3 {
  margin: 0;
  font-size: 15px;
}

.view-result {
  background: var(--gmp-accent);
  border: 1px solid var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
  border-radius: 8px;
  padding: 6px 16px;
  font-size: 13px;
  text-decoration: none;
}

.status-note {
  margin: 0;
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.stage-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stage {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 12px;
}

.stage-name {
  color: var(--gmp-text-dim);
  min-width: 130px;
}

.stage-detail {
  color: var(--gmp-text);
}

.stage-detail.ok {
  color: #7fd6a4;
}

.stage-detail.bad {
  color: #ef9a9a;
}

.stage-error {
  color: #ef9a9a;
  font-size: 12px;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>

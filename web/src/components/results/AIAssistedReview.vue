<script setup lang="ts">
// v0.9.0 Task 10 前端：AI 辅助研判面板（DeepSeek 证据驱动复核）。
// AI 是规则研判之外的辅助意见：四视角归纳 + 共识/分歧 + 候选研判路径 +
// 复核清单 + 限制；未配置/离线/超时/失败全部类型化状态，规则研判始终可用。
// 不显示虚构置信度百分比，不渲染推理内容；evidence_refs 只来自后端
// EvidencePacket 合法 ID，点击发射 focus-evidence 由工作台联动组件/层段/切片。
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError, fetchLatestAiAnalysis, generateAiAnalysis } from '../../api/client'
import type { AIAnalysisMode, AIAnalysisRecord, AIPerspective } from '../../api/types'
import AsyncState from '../states/AsyncState.vue'

const props = defineProps<{
  resultId: string
  gridSha256: string | null
}>()

const emit = defineEmits<{
  (e: 'focus-evidence', ref: string): void
}>()

const record = ref<AIAnalysisRecord | null>(null)
// none = 无记录（404）；ready = 有记录；loading = 首次获取中；error = 获取失败
const loadState = ref<'loading' | 'none' | 'ready' | 'error'>('loading')
const loadError = ref<string | null>(null)
const generating = ref(false)
const generateError = ref<string | null>(null)
const mode = ref<AIAnalysisMode>('quick')

const PERSPECTIVES: Array<{ key: 'spatial_pattern' | 'model_reliability' | 'uncertainty_and_risk' | 'review_and_next_checks'; label: string }> = [
  { key: 'spatial_pattern', label: '空间格局' },
  { key: 'model_reliability', label: '模型可靠性' },
  { key: 'uncertainty_and_risk', label: '不确定性与风险' },
  { key: 'review_and_next_checks', label: '复核与下一步' },
]

const review = computed(() => (record.value?.status === 'succeeded' ? record.value.review : null))

function perspectiveOf(key: (typeof PERSPECTIVES)[number]['key']): AIPerspective | null {
  return review.value?.[key] ?? null
}

function formatError(e: unknown): string {
  return e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
}

async function loadLatest() {
  record.value = null
  loadError.value = null
  generateError.value = null
  loadState.value = 'loading'
  try {
    record.value = await fetchLatestAiAnalysis(props.resultId)
    loadState.value = 'ready'
  } catch (e) {
    if (e instanceof ApiError && e.code === 'AI_ANALYSIS_NOT_FOUND') {
      loadState.value = 'none'
    } else {
      loadError.value = formatError(e)
      loadState.value = 'error'
    }
  }
}

async function generate(regenerate: boolean) {
  if (generating.value) return
  generating.value = true
  generateError.value = null
  try {
    record.value = await generateAiAnalysis(props.resultId, { mode: mode.value, regenerate })
    loadState.value = 'ready'
  } catch (e) {
    // 生成失败保留既有记录；类型化错误明示，绝不清空规则可用性
    generateError.value = formatError(e)
  } finally {
    generating.value = false
  }
}

onMounted(loadLatest)

// 身份切换（成果或网格哈希变化）：旧 AI 记录立即清空并按新身份重新获取
watch(
  () => [props.resultId, props.gridSha256] as const,
  ([nextId], [prevId]) => {
    if (nextId === prevId) return
    void loadLatest()
  },
)
</script>

<template>
  <section class="ai-review" aria-label="AI 辅助研判">
    <p class="ai-note">AI 仅为辅助意见，不替代规则研判；规则研判始终可用。</p>

    <AsyncState v-if="loadState === 'loading'" kind="loading" title="AI 记录加载中" />

    <template v-else-if="loadState === 'error'">
      <AsyncState
        kind="error"
        title="AI 记录获取失败"
        :impact="loadError ?? '未知错误'"
        next-action="重试；规则研判不受影响"
        data-test="ai-load-error"
      />
      <button type="button" class="action-button" data-test="ai-reload" @click="loadLatest">
        重试
      </button>
    </template>

    <template v-else>
      <!-- 模式选择：quick 单次分析 / review 复核模式（服务端语义） -->
      <div class="mode-row">
        <span class="mode-label">分析模式</span>
        <button
          type="button"
          class="mode-button"
          :class="{ active: mode === 'quick' }"
          data-test="ai-mode-quick"
          @click="mode = 'quick'"
        >
          快速
        </button>
        <button
          type="button"
          class="mode-button"
          :class="{ active: mode === 'review' }"
          data-test="ai-mode-review"
          @click="mode = 'review'"
        >
          复核
        </button>
      </div>

      <!-- 无记录：真实空态 + 显式生成（唯一计费入口） -->
      <div v-if="loadState === 'none'" class="ai-empty" data-test="ai-empty">
        <p>尚未生成 AI 辅助分析。</p>
        <p class="ai-subnote">生成会调用外部 DeepSeek 服务并产生费用；规则研判无需该服务。</p>
        <button
          type="button"
          class="action-button primary"
          data-test="ai-generate"
          :disabled="generating"
          @click="generate(false)"
        >
          {{ generating ? '正在生成…' : '生成辅助分析' }}
        </button>
      </div>

      <!-- 未配置/不可用：类型化配置说明 -->
      <div
        v-else-if="record && record.status === 'unavailable'"
        class="ai-state"
        data-test="ai-unavailable"
      >
        <p class="state-title">AI 辅助分析不可用</p>
        <p class="ai-subnote mono">{{ record.error_code }}</p>
        <p class="ai-subnote">
          {{ record.error_message ?? '服务端未配置 DEEPSEEK_API_KEY；配置后可重新生成。' }}
        </p>
        <button
          type="button"
          class="action-button"
          data-test="ai-regenerate"
          :disabled="generating"
          @click="generate(true)"
        >
          {{ generating ? '正在重试…' : '重新生成' }}
        </button>
      </div>

      <!-- 服务错误：错误码 + 消息 + 重试 -->
      <div v-else-if="record && record.status === 'error'" class="ai-state" data-test="ai-error">
        <p class="state-title">AI 辅助分析失败</p>
        <p class="ai-subnote mono">{{ record.error_code }}</p>
        <p class="ai-subnote">{{ record.error_message }}</p>
        <button
          type="button"
          class="action-button"
          data-test="ai-retry"
          :disabled="generating"
          @click="generate(true)"
        >
          {{ generating ? '正在重试…' : '重试' }}
        </button>
      </div>

      <!-- 成功：四视角 + 共识/分歧 + 候选路径 + 复核清单 + 限制 + 身份 -->
      <div v-else-if="review" class="ai-state" data-test="ai-review">
        <p class="review-badge">AI 辅助意见</p>

        <article
          v-for="p in PERSPECTIVES"
          :key="p.key"
          class="perspective"
          :data-test="`ai-perspective-${p.key}`"
        >
          <h4 class="perspective-title">{{ p.label }}</h4>
          <p class="perspective-text">{{ perspectiveOf(p.key)?.summary }}</p>
          <div class="ref-row">
            <button
              v-for="ref in perspectiveOf(p.key)?.evidence_refs ?? []"
              :key="ref"
              type="button"
              class="ref-chip"
              :data-test="`ai-ref-${p.key}-${ref}`"
              @click="emit('focus-evidence', ref)"
            >
              {{ ref }}
            </button>
          </div>
        </article>

        <section class="consensus" data-test="ai-consensus">
          <h4 class="perspective-title">共识与分歧</h4>
          <p class="perspective-text">{{ review.consensus.consensus }}</p>
          <ul v-if="review.consensus.disagreements.length > 0" class="plain-list">
            <li v-for="item in review.consensus.disagreements" :key="item">分歧：{{ item }}</li>
          </ul>
        </section>

        <section v-if="review.consensus.decision_options.length > 0" data-test="ai-decision-options">
          <h4 class="perspective-title">候选研判路径</h4>
          <div
            v-for="option in review.consensus.decision_options"
            :key="option.label"
            class="option-card"
          >
            <p class="option-label">{{ option.label }}</p>
            <p class="ai-subnote">触发条件：{{ option.trigger }}</p>
            <p class="ai-subnote">收益：{{ option.benefit }} · 代价：{{ option.cost }}</p>
          </div>
        </section>

        <section v-if="review.consensus.recommended_checks.length > 0" data-test="ai-checks">
          <h4 class="perspective-title">建议复核清单</h4>
          <ul class="plain-list">
            <li v-for="item in review.consensus.recommended_checks" :key="item">{{ item }}</li>
          </ul>
        </section>

        <section v-if="review.consensus.limitations.length > 0" data-test="ai-limitations">
          <h4 class="perspective-title">限制</h4>
          <ul class="plain-list">
            <li v-for="item in review.consensus.limitations" :key="item">{{ item }}</li>
          </ul>
        </section>

        <p class="identity-footer" data-test="ai-identity">
          {{ record?.provider }}/{{ record?.model }} · {{ record?.created_at }} ·
          prompt {{ review.prompt_version }} · evidence
          {{ review.evidence_hash.slice(0, 12) }}…
        </p>

        <div class="action-row">
          <button
            type="button"
            class="action-button"
            data-test="ai-regenerate"
            :disabled="generating"
            @click="generate(true)"
          >
            {{ generating ? '正在生成…' : '重新生成' }}
          </button>
        </div>
      </div>

      <p v-if="generateError" class="generate-error" data-test="ai-generate-error" role="status">
        生成失败：{{ generateError }}（既有记录保留，规则研判不受影响）
      </p>
    </template>
  </section>
</template>

<style scoped>
.ai-review {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-3);
  min-width: 0;
}

.ai-note {
  margin: 0;
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
  border: 1px dashed var(--s1-border);
  border-radius: var(--s1-radius-sm);
  padding: 6px 10px;
}

.mode-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mode-label {
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
}

.mode-button {
  border: 1px solid var(--s1-border);
  background: transparent;
  color: var(--s1-text-dim);
  border-radius: 6px;
  padding: 3px 12px;
  font-size: var(--s1-font-xs);
  cursor: pointer;
}

.mode-button.active {
  border-color: var(--s1-cyan-dim);
  background: var(--s1-cyan-ghost);
  color: var(--s1-cyan-strong);
}

.ai-empty,
.ai-state {
  border: 1px solid var(--s1-border);
  border-radius: var(--s1-radius-md);
  background: var(--s1-surface-1);
  padding: var(--s1-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-2);
}

.ai-empty p {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
}

.state-title {
  margin: 0;
  font-size: var(--s1-font-sm);
  font-weight: 600;
  color: var(--s1-text);
}

.review-badge {
  margin: 0;
  align-self: flex-start;
  font-size: var(--s1-font-xs);
  color: var(--s1-gold);
  border: 1px solid rgba(217, 168, 78, 0.5);
  border-radius: 4px;
  padding: 1px 8px;
}

.perspective {
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-sm);
  padding: 8px 10px;
}

.perspective-title {
  margin: 0 0 4px;
  font-size: var(--s1-font-xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--s1-text-dim);
}

.perspective-text {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-text);
  line-height: var(--s1-leading);
}

.ref-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.ref-chip {
  border: 1px solid var(--s1-cyan-dim);
  background: var(--s1-cyan-ghost);
  color: var(--s1-cyan-strong);
  border-radius: 4px;
  padding: 1px 8px;
  font-size: var(--s1-font-xs);
  font-family: ui-monospace, monospace;
  cursor: pointer;
}

.ref-chip:hover {
  border-color: var(--s1-cyan-strong);
}

.option-card {
  border: 1px solid var(--s1-border-soft);
  border-radius: var(--s1-radius-sm);
  padding: 8px 10px;
  margin-bottom: 6px;
}

.option-label {
  margin: 0;
  font-size: var(--s1-font-sm);
  font-weight: 600;
  color: var(--s1-text);
}

.ai-subnote {
  margin: 2px 0 0;
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
  line-height: var(--s1-leading);
}

.plain-list {
  margin: 0;
  padding-left: 16px;
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
}

.identity-footer {
  margin: 0;
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
  font-family: ui-monospace, monospace;
  word-break: break-all;
}

.action-row {
  display: flex;
  gap: 8px;
}

.action-button {
  align-self: flex-start;
  border: 1px solid var(--s1-cyan-dim);
  background: var(--s1-cyan-ghost);
  color: var(--s1-cyan-strong);
  border-radius: 6px;
  padding: 5px 14px;
  font-size: var(--s1-font-sm);
  cursor: pointer;
}

.action-button.primary {
  background: var(--s1-cyan-strong);
  color: #0b0f14;
  font-weight: 600;
}

.action-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.generate-error {
  margin: 0;
  font-size: var(--s1-font-sm);
  color: var(--s1-warning);
  border: 1px solid rgba(217, 168, 78, 0.4);
  border-radius: var(--s1-radius-sm);
  background: rgba(217, 168, 78, 0.08);
  padding: 6px 12px;
}

.mono {
  font-family: ui-monospace, monospace;
}
</style>

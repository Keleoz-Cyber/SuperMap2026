<script setup lang="ts">
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
const loadState = ref<'loading' | 'none' | 'ready' | 'error'>('loading')
const loadError = ref<string | null>(null)
const generating = ref(false)
const generateError = ref<string | null>(null)
const mode = ref<AIAnalysisMode>('quick')
let loadSequence = 0

const MODES: Array<{ key: AIAnalysisMode; label: string; description: string }> = [
  { key: 'quick', label: '快速解读', description: '提炼主要结论、关键依据和下一步动作' },
  { key: 'review', label: '深度复核', description: '额外检查证据矛盾、解释边界和过度结论' },
]

const PERSPECTIVES: Array<{
  key: 'spatial_pattern' | 'model_reliability' | 'uncertainty_and_risk'
  label: string
  kicker: string
}> = [
  { key: 'spatial_pattern', label: '空间分布怎么理解', kicker: '分布特征' },
  { key: 'model_reliability', label: '这个模型是否可信', kicker: '模型表现' },
  { key: 'uncertainty_and_risk', label: '哪些地方需要谨慎', kicker: '解释边界' },
]

const review = computed(() => (record.value?.status === 'succeeded' ? record.value.review : null))
const activeMode = computed(() => MODES.find((item) => item.key === mode.value) ?? MODES[0])

function perspectiveOf(key: (typeof PERSPECTIVES)[number]['key']): AIPerspective | null {
  return review.value?.[key] ?? null
}

function formatError(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

function evidenceLabel(refId: string): string {
  const component = /^component-(\d+)$/.exec(refId)
  if (component) {
    const index = Number(component[1])
    const letter = index > 0 && index <= 26 ? String.fromCharCode(64 + index) : String(index)
    return `异常区域 ${letter}`
  }
  const depthBin = /^depth_bin-(\d+)$/.exec(refId)
  if (depthBin) return `深度层段 ${Number(depthBin[1]) + 1}`
  const labels: Record<string, string> = {
    identity: '成果身份',
    variable: '属性字段',
    result_grid: '成果网格',
    spatial_components: '异常区域汇总',
    depth_profile: '深度趋势',
    composition: '数值构成',
    model_evidence: '模型验证指标',
    uncertainty: '不确定性证据',
    input_quality: '输入数据质量',
    constraints: '解释边界',
    current_slice: '当前切片',
  }
  return labels[refId] ?? '相关分析依据'
}

function formatCreatedAt(value: string | null | undefined): string {
  if (!value) return '时间未知'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

async function loadLatest(selectedMode: AIAnalysisMode = mode.value) {
  const sequence = ++loadSequence
  record.value = null
  loadError.value = null
  generateError.value = null
  loadState.value = 'loading'
  try {
    const next = await fetchLatestAiAnalysis(props.resultId, selectedMode)
    if (sequence !== loadSequence) return
    // 兼容尚未重启的旧服务：若服务忽略 mode 查询参数，绝不把另一模式的
    // 记录冒充为当前模式结果。
    if (next.mode !== selectedMode) {
      loadState.value = 'none'
      return
    }
    record.value = next
    loadState.value = 'ready'
  } catch (error) {
    if (sequence !== loadSequence) return
    if (error instanceof ApiError && error.code === 'AI_ANALYSIS_NOT_FOUND') {
      loadState.value = 'none'
    } else {
      loadError.value = formatError(error)
      loadState.value = 'error'
    }
  }
}

function selectMode(nextMode: AIAnalysisMode) {
  if (mode.value === nextMode) return
  mode.value = nextMode
  void loadLatest(nextMode)
}

async function generate(regenerate: boolean) {
  if (generating.value) return
  generating.value = true
  generateError.value = null
  try {
    record.value = await generateAiAnalysis(props.resultId, { mode: mode.value, regenerate })
    loadState.value = 'ready'
  } catch (error) {
    generateError.value = formatError(error)
  } finally {
    generating.value = false
  }
}

onMounted(() => loadLatest())

watch(
  () => [props.resultId, props.gridSha256] as const,
  ([nextId], [previousId]) => {
    if (nextId === previousId) return
    mode.value = 'quick'
    void loadLatest('quick')
  },
)
</script>

<template>
  <section class="ai-review" aria-label="AI 辅助研判">
    <header class="ai-header">
      <div>
        <p class="ai-eyebrow">AI 辅助研判</p>
        <h3>把分析结果转成可执行判断</h3>
      </div>
      <span class="assist-badge">辅助意见</span>
    </header>

    <div class="mode-selector" aria-label="选择 AI 分析模式">
      <button
        v-for="item in MODES"
        :key="item.key"
        type="button"
        class="mode-card"
        :class="{ active: mode === item.key }"
        :aria-pressed="mode === item.key"
        :data-test="`ai-mode-${item.key}`"
        @click="selectMode(item.key)"
      >
        <strong>{{ item.label }}</strong>
        <span>{{ item.description }}</span>
      </button>
    </div>

    <p class="ai-note">
      当前查看：{{ activeMode.label }}。切换模式只读取已有结果，不会自动调用外部服务；生成或重做时才会产生请求。规则研判始终可用。
    </p>

    <AsyncState v-if="loadState === 'loading'" kind="loading" :title="`${activeMode.label}加载中`" />

    <template v-else-if="loadState === 'error'">
      <AsyncState
        kind="error"
        :title="`${activeMode.label}获取失败`"
        :impact="loadError ?? '未知错误'"
        next-action="可以重试；规则研判不受影响"
        data-test="ai-load-error"
      />
      <button type="button" class="action-button" data-test="ai-reload" @click="loadLatest()">
        重新读取
      </button>
    </template>

    <template v-else>
      <div v-if="loadState === 'none'" class="ai-empty" data-test="ai-empty">
        <p class="empty-title">尚未生成{{ activeMode.label }}</p>
        <p>{{ activeMode.description }}。生成会调用 DeepSeek；不生成也不影响规则分析。</p>
        <button
          type="button"
          class="action-button primary"
          data-test="ai-generate"
          :disabled="generating"
          @click="generate(false)"
        >
          {{ generating ? '正在生成…' : `生成${activeMode.label}` }}
        </button>
      </div>

      <div v-else-if="record?.status === 'unavailable'" class="ai-state" data-test="ai-unavailable">
        <p class="state-title">AI 服务尚未配置</p>
        <p>规则分析仍可正常使用。请配置服务后再生成{{ activeMode.label }}。</p>
        <details class="technical-details">
          <summary>查看配置提示</summary>
          <p class="mono">{{ record.error_code }}</p>
          <p>{{ record.error_message ?? '服务端未配置 DEEPSEEK_API_KEY。' }}</p>
        </details>
        <button type="button" class="action-button" data-test="ai-regenerate" :disabled="generating" @click="generate(true)">
          {{ generating ? '正在重试…' : '配置后重试' }}
        </button>
      </div>

      <div v-else-if="record?.status === 'error'" class="ai-state" data-test="ai-error">
        <p class="state-title">{{ activeMode.label }}生成失败</p>
        <p>{{ record.error_message }}</p>
        <details class="technical-details">
          <summary>技术详情</summary>
          <p class="mono error-code">{{ record.error_code }}</p>
        </details>
        <button type="button" class="action-button" data-test="ai-retry" :disabled="generating" @click="generate(true)">
          {{ generating ? '正在重试…' : '重新生成' }}
        </button>
      </div>

      <div v-else-if="review" class="ai-state review-content" data-test="ai-review">
        <section class="conclusion-card" data-test="ai-conclusion">
          <div class="conclusion-topline">
            <span>{{ record?.mode === 'review' ? '深度复核结论' : '快速解读结论' }}</span>
            <time>{{ formatCreatedAt(record?.created_at) }}</time>
          </div>
          <div data-test="ai-consensus">
            <p>{{ review.consensus.consensus }}</p>
            <p v-if="review.consensus.disagreements.length" class="disagreement-note">
              需注意：{{ review.consensus.disagreements[0] }}
            </p>
          </div>
          <div class="summary-counts">
            <span><strong>3</strong> 项关键判断</span>
            <span><strong>{{ review.consensus.recommended_checks.length }}</strong> 项建议动作</span>
            <span><strong>{{ review.consensus.decision_options.length }}</strong> 个备选方案</span>
          </div>
        </section>

        <section class="content-section">
          <div class="section-heading">
            <div><span>01</span><h4>关键判断</h4></div>
            <small>先看结论，再按需查看依据</small>
          </div>
          <article
            v-for="perspective in PERSPECTIVES"
            :key="perspective.key"
            class="perspective"
            :data-test="`ai-perspective-${perspective.key}`"
          >
            <p class="card-kicker">{{ perspective.kicker }}</p>
            <h5>{{ perspective.label }}</h5>
            <p class="perspective-text">{{ perspectiveOf(perspective.key)?.summary }}</p>
            <details
              v-if="(perspectiveOf(perspective.key)?.evidence_refs.length ?? 0) > 0"
              class="evidence-details"
              :data-test="`ai-evidence-${perspective.key}`"
            >
              <summary>查看数据依据</summary>
              <div class="ref-row">
                <button
                  v-for="refId in perspectiveOf(perspective.key)?.evidence_refs ?? []"
                  :key="refId"
                  type="button"
                  class="ref-chip"
                  :title="`定位到${evidenceLabel(refId)}`"
                  :data-test="`ai-ref-${perspective.key}-${refId}`"
                  @click="emit('focus-evidence', refId)"
                >
                  {{ evidenceLabel(refId) }}
                </button>
              </div>
            </details>
          </article>
        </section>

        <section class="content-section action-section" data-test="ai-checks">
          <div class="section-heading">
            <div><span>02</span><h4>建议先做</h4></div>
            <small>按顺序复核可疑环节</small>
          </div>
          <article class="next-step" data-test="ai-perspective-review_and_next_checks">
            <p>{{ review.review_and_next_checks.summary }}</p>
            <ol>
              <li v-for="item in review.consensus.recommended_checks" :key="item">{{ item }}</li>
            </ol>
            <details v-if="review.review_and_next_checks.evidence_refs.length" class="evidence-details" data-test="ai-evidence-review_and_next_checks">
              <summary>查看行动依据</summary>
              <div class="ref-row">
                <button
                  v-for="refId in review.review_and_next_checks.evidence_refs"
                  :key="refId"
                  type="button"
                  class="ref-chip"
                  :data-test="`ai-ref-review_and_next_checks-${refId}`"
                  @click="emit('focus-evidence', refId)"
                >
                  {{ evidenceLabel(refId) }}
                </button>
              </div>
            </details>
          </article>
        </section>

        <section v-if="review.consensus.decision_options.length" class="content-section" data-test="ai-decision-options">
          <div class="section-heading">
            <div><span>03</span><h4>方案怎么选</h4></div>
            <small>明确条件、收益和代价</small>
          </div>
          <div class="option-list">
            <article v-for="option in review.consensus.decision_options" :key="option.label" class="option-card">
              <h5>{{ option.label }}</h5>
              <dl>
                <div><dt>适用条件</dt><dd>{{ option.trigger }}</dd></div>
                <div><dt>预期收益</dt><dd>{{ option.benefit }}</dd></div>
                <div><dt>需要付出</dt><dd>{{ option.cost }}</dd></div>
              </dl>
            </article>
          </div>
        </section>

        <details v-if="review.consensus.disagreements.length || review.consensus.limitations.length" class="limitations" data-test="ai-limitations">
          <summary>需要注意的分歧与限制</summary>
          <ul>
            <li v-for="item in review.consensus.disagreements" :key="`d-${item}`">{{ item }}</li>
            <li v-for="item in review.consensus.limitations" :key="`l-${item}`">{{ item }}</li>
          </ul>
        </details>

        <details class="technical-details" data-test="ai-technical-details">
          <summary>技术信息</summary>
          <p class="identity-footer" data-test="ai-identity">
            服务 {{ record?.provider }} / {{ record?.model }} · 提示词 {{ review.prompt_version }} · 证据校验码 {{ review.evidence_hash.slice(0, 12) }}…
          </p>
        </details>

        <div class="action-row">
          <button type="button" class="action-button" data-test="ai-regenerate" :disabled="generating" @click="generate(true)">
            {{ generating ? '正在生成…' : `重新生成${activeMode.label}` }}
          </button>
          <span>AI 用于辅助理解，最终判断以平台规则分析与人工复核为准。</span>
        </div>
      </div>

      <p v-if="generateError" class="generate-error" data-test="ai-generate-error" role="status">
        生成失败：{{ generateError }}。原有分析仍保留，规则研判不受影响。
      </p>
    </template>
  </section>
</template>

<style scoped>
.ai-review { display: flex; flex-direction: column; gap: 14px; min-width: 0; color: var(--s1-text); }
.ai-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.ai-header h3 { margin: 3px 0 0; font-size: 20px; line-height: 1.3; }
.ai-eyebrow { margin: 0; color: var(--s1-cyan-strong); font-size: 12px; font-weight: 700; letter-spacing: .12em; }
.assist-badge { flex: none; padding: 4px 9px; border: 1px solid rgba(217,168,78,.5); border-radius: 999px; color: var(--s1-gold); font-size: 13px; }
.mode-selector { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.mode-card { min-height: 68px; padding: 10px 12px; text-align: left; border: 1px solid var(--s1-border); border-radius: 9px; background: var(--s1-surface-1); color: var(--s1-text); cursor: pointer; }
.mode-card strong, .mode-card span { display: block; }
.mode-card strong { font-size: 16px; }
.mode-card span { margin-top: 4px; color: var(--s1-text-faint); font-size: 13px; line-height: 1.45; }
.mode-card.active { border-color: var(--s1-cyan-strong); background: linear-gradient(135deg, var(--s1-cyan-ghost), var(--s1-surface-1)); box-shadow: inset 3px 0 var(--s1-cyan-strong); }
.mode-card.active span { color: var(--s1-text-dim); }
.ai-note { margin: 0; padding: 8px 10px; border: 1px dashed var(--s1-border); border-radius: 7px; color: var(--s1-text-faint); font-size: 13px; line-height: 1.5; }
.ai-empty, .ai-state { display: flex; flex-direction: column; gap: 12px; padding: 14px; border: 1px solid var(--s1-border); border-radius: 10px; background: var(--s1-surface-1); }
.ai-empty p, .ai-state p { margin: 0; }
.empty-title, .state-title { color: var(--s1-text); font-size: 17px; font-weight: 700; }
.review-content { padding: 0; border: 0; background: transparent; }
.conclusion-card { padding: 16px; border: 1px solid var(--s1-cyan-dim); border-radius: 10px; background: linear-gradient(145deg, rgba(61,208,180,.12), rgba(61,208,180,.025)); }
.conclusion-topline { display: flex; justify-content: space-between; gap: 10px; color: var(--s1-cyan-strong); font-size: 13px; font-weight: 700; }
.conclusion-topline time { color: var(--s1-text-faint); font-weight: 400; }
.conclusion-card > p { margin-top: 10px; font-size: 18px; font-weight: 650; line-height: 1.65; }
.conclusion-card [data-test='ai-consensus'] > p:first-child { margin-top: 10px; font-size: 18px; font-weight: 650; line-height: 1.65; }
.disagreement-note { margin-top: 8px !important; color: var(--s1-gold); font-size: 13px !important; font-weight: 500 !important; line-height: 1.5 !important; }
.summary-counts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin-top: 13px; }
.summary-counts span { padding: 7px; border: 1px solid var(--s1-border-soft); background: rgba(0,0,0,.12); color: var(--s1-text-dim); font-size: 12px; text-align: center; }
.summary-counts strong { color: var(--s1-cyan-strong); font-size: 16px; }
.content-section { display: flex; flex-direction: column; gap: 8px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.section-heading > div { display: flex; align-items: center; gap: 8px; }
.section-heading span { display: grid; place-items: center; width: 26px; height: 26px; background: var(--s1-cyan-strong); color: #06100d; font-size: 12px; font-weight: 800; }
.section-heading h4 { margin: 0; font-size: 17px; }
.section-heading small { color: var(--s1-text-faint); font-size: 12px; }
.perspective, .next-step, .option-card { padding: 12px; border: 1px solid var(--s1-border-soft); border-radius: 8px; background: var(--s1-surface-1); }
.perspective { border-left: 3px solid var(--s1-cyan-dim); }
.card-kicker { color: var(--s1-cyan-strong); font-size: 12px; font-weight: 700; }
.perspective h5, .option-card h5 { margin: 3px 0 7px; font-size: 16px; }
.perspective-text, .next-step > p { font-size: 15px; line-height: 1.7; }
.evidence-details, .technical-details, .limitations { color: var(--s1-text-dim); font-size: 13px; }
summary { cursor: pointer; user-select: none; }
.evidence-details { margin-top: 8px; }
.ref-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 7px; }
.ref-chip { min-height: 30px; padding: 4px 9px; border: 1px solid var(--s1-cyan-dim); border-radius: 5px; background: var(--s1-cyan-ghost); color: var(--s1-cyan-strong); font-size: 13px; cursor: pointer; }
.next-step { border-left: 3px solid var(--s1-gold); }
.next-step ol { margin: 10px 0 0; padding-left: 24px; }
.next-step li { margin: 7px 0; color: var(--s1-text); font-size: 15px; line-height: 1.55; }
.option-list { display: grid; gap: 8px; }
.option-card dl { display: grid; gap: 6px; margin: 0; }
.option-card dl div { display: grid; grid-template-columns: 66px 1fr; gap: 8px; font-size: 14px; line-height: 1.5; }
.option-card dt { color: var(--s1-text-faint); }
.option-card dd { margin: 0; color: var(--s1-text-dim); }
.limitations { padding: 11px 12px; border: 1px solid rgba(217,168,78,.35); border-radius: 8px; background: rgba(217,168,78,.06); }
.limitations ul { margin: 9px 0 0; padding-left: 18px; }
.limitations li { margin: 5px 0; line-height: 1.5; }
.technical-details { padding: 8px 10px; border-top: 1px solid var(--s1-border-soft); }
.technical-details p { margin-top: 7px; }
.identity-footer { color: var(--s1-text-faint); font-family: ui-monospace, monospace; font-size: 12px; line-height: 1.5; word-break: break-all; }
.action-row { display: flex; align-items: center; gap: 10px; }
.action-row span { color: var(--s1-text-faint); font-size: 12px; line-height: 1.45; }
.action-button { align-self: flex-start; min-height: 36px; padding: 7px 14px; border: 1px solid var(--s1-cyan-dim); border-radius: 7px; background: var(--s1-cyan-ghost); color: var(--s1-cyan-strong); font-size: 14px; font-weight: 650; cursor: pointer; }
.action-button.primary { background: var(--s1-cyan-strong); color: #07110e; }
.action-button:disabled { opacity: .5; cursor: not-allowed; }
.generate-error, .error-code { color: var(--s1-warning); }
.generate-error { margin: 0; padding: 8px 10px; border: 1px solid rgba(217,168,78,.4); border-radius: 7px; background: rgba(217,168,78,.08); font-size: 14px; line-height: 1.5; }
.mono { font-family: ui-monospace, monospace; }

@media (max-width: 520px) {
  .mode-selector, .summary-counts { grid-template-columns: 1fr; }
  .conclusion-topline, .section-heading, .action-row { align-items: flex-start; flex-direction: column; }
}
</style>

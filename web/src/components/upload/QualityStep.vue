<script setup lang="ts">
import { computed } from 'vue'
import type { QualityReport } from '../../api/types'

const props = defineProps<{
  report: QualityReport | null
  validating: boolean
  confirming: boolean
}>()

const emit = defineEmits<{
  (e: 'validate'): void
  (e: 'confirm'): void
  (e: 'start'): void
}>()

const blockers = computed(() => props.report?.issues.filter((i) => i.kind === 'blocker') ?? [])
const warnings = computed(() => props.report?.issues.filter((i) => i.kind === 'warning') ?? [])

// 质量就绪的唯一判定：ready，或 warnings 且已被用户显式确认
const qualityReady = computed(
  () =>
    props.report !== null &&
    (props.report.status === 'passed' || (props.report.status === 'warnings' && props.report.confirmed)),
)

const banner = computed(() => {
  if (!props.report) return null
  if (props.report.status === 'blocked') return { kind: 'bad', text: '质量校验未通过：存在阻断项' }
  if (props.report.status === 'warnings' && !props.report.confirmed)
    return { kind: 'warn', text: '存在警告：须逐条知悉并整体确认后才能开始实验' }
  if (props.report.status === 'warnings') return { kind: 'ok', text: '警告已确认，可以开始实验' }
  return { kind: 'ok', text: '质量校验通过' }
})
</script>

<template>
  <section class="wizard-step" data-test="step-quality">
    <h3><span class="step-no">3</span> 质量校验</h3>

    <div v-if="!report" class="quality-empty">
      <p class="step-hint">尚未执行质量校验。完成字段映射后会自动校验，也可手动重新校验。</p>
      <button class="gmp-btn" data-test="run-validate" :disabled="validating" @click="emit('validate')">
        {{ validating ? '校验中…' : '重新校验' }}
      </button>
    </div>

    <template v-else>
      <div class="quality-banner" :class="banner?.kind" data-test="quality-banner">
        {{ banner?.text }}
      </div>

      <div class="quality-stats">
        <span>总行 {{ report.row_count }}</span>
        <span>有效 {{ report.valid_row_count }}</span>
        <span>数值失败 {{ report.invalid_row_count }}</span>
        <span>唯一点位 {{ report.statistics.unique_coordinate_count }}</span>
        <span>重复 {{ report.statistics.duplicate_count }}</span>
        <span>冲突 {{ report.statistics.conflict_count }}</span>
      </div>

      <ul v-if="blockers.length" class="issue-list blockers" data-test="blocker-list">
        <li v-for="issue in blockers" :key="issue.code">
          <b>{{ issue.code }}</b>
          <span>{{ issue.message }}</span>
        </li>
      </ul>

      <ul v-if="warnings.length" class="issue-list warnings" data-test="warning-list">
        <li v-for="issue in warnings" :key="issue.code">
          <b>{{ issue.code }}</b>
          <span>{{ issue.message }}</span>
        </li>
      </ul>

      <div class="quality-actions">
        <button
          v-if="report.status === 'warnings' && !report.confirmed"
          class="gmp-btn warn"
          data-test="confirm-warnings"
          :disabled="confirming"
          @click="emit('confirm')"
        >
          {{ confirming ? '确认中…' : `确认全部 ${warnings.length} 条警告` }}
        </button>
        <button class="gmp-btn" data-test="run-validate-again" :disabled="validating" @click="emit('validate')">
          重新校验
        </button>
        <button
          class="gmp-btn primary"
          data-test="start-experiment"
          :disabled="!qualityReady"
          @click="emit('start')"
        >
          开始实验
        </button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.wizard-step {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 18px 20px;
}

.wizard-step h3 {
  margin: 0 0 14px;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.step-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--gmp-accent);
  color: #0b0f14;
  font-size: 12px;
  font-weight: 700;
}

.step-hint {
  color: var(--gmp-text-faint);
  font-size: 13px;
}

.quality-banner {
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  margin-bottom: 12px;
  border: 1px solid var(--gmp-border);
}

.quality-banner.ok {
  border-color: #2e7d4f;
  background: rgba(46, 125, 79, 0.15);
  color: #7fd6a4;
}

.quality-banner.warn {
  border-color: #9a7b2d;
  background: rgba(154, 123, 45, 0.15);
  color: #e5c76b;
}

.quality-banner.bad {
  border-color: #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
}

.quality-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  font-size: 12px;
  color: var(--gmp-text-dim);
  margin-bottom: 12px;
}

.issue-list {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.issue-list li {
  display: flex;
  gap: 10px;
  align-items: baseline;
  font-size: 13px;
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  padding: 8px 12px;
}

.issue-list.blockers li {
  border-color: #a43d3d;
}

.issue-list.blockers b {
  color: #ef9a9a;
}

.issue-list.warnings b {
  color: #e5c76b;
}

.quality-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 8px 18px;
  font-size: 13px;
  cursor: pointer;
}

.gmp-btn.primary {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.gmp-btn.warn {
  border-color: #9a7b2d;
  color: #e5c76b;
}

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.quality-empty {
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
}
</style>

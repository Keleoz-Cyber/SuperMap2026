<script setup lang="ts">
// v0.9.0：关键发现面板。最多五条有序结论卡 + 解释性空状态；
// 定位动作统一向上抛出，由工作台接入三维选择控制器。
import { computed } from 'vue'
import type { PresentationFinding } from '../../domain/findings'
import FindingCard from './FindingCard.vue'

const props = defineProps<{ findings: PresentationFinding[] }>()
const emit = defineEmits<{ locate: [finding: PresentationFinding] }>()

const visibleFindings = computed(() => props.findings.slice(0, 5))
</script>

<template>
  <section class="finding-panel" aria-label="关键发现">
    <div v-if="visibleFindings.length === 0" class="findings-empty" data-test="findings-empty">
      <p>暂无可展示的关键发现</p>
      <p class="empty-note">分析摘要缺少可用模块或数据尚未验证；完成建模验证后此处自动生成结论。</p>
    </div>
    <FindingCard
      v-for="finding in visibleFindings"
      :key="finding.id"
      :finding="finding"
      @locate="emit('locate', $event)"
    />
  </section>
</template>

<style scoped>
.finding-panel {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-3);
}

.findings-empty {
  border: 1px dashed var(--s1-border);
  border-radius: var(--s1-radius-sm);
  padding: var(--s1-space-4);
  text-align: center;
  color: var(--s1-text-dim);
  font-size: var(--s1-font-md);
}

.findings-empty p {
  margin: 0;
}

.empty-note {
  margin-top: 6px !important;
  font-size: var(--s1-font-xs);
  color: var(--s1-text-faint);
  line-height: var(--s1-leading);
}
</style>

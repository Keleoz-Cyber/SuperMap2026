<script setup lang="ts">
// v0.9.0：调参实验室布局。顶部上下文栏（唯一主动作）+ 左侧参数区 +
// 中央实验画布 + 右侧候选摘要 + 底部实验队列。布局只组合插槽，
// 不承载建模逻辑。
defineProps<{
  title: string
  datasetLabel?: string | null
}>()
</script>

<template>
  <div class="lab-layout" data-test="lab-layout">
    <div class="lab-context">
      <div class="lab-title">
        <h2>{{ title }}</h2>
        <span v-if="datasetLabel" class="lab-dataset">{{ datasetLabel }}</span>
      </div>
      <div class="lab-actions" data-test="lab-actions">
        <slot name="actions" />
      </div>
    </div>

    <div class="lab-grid">
      <div class="lab-params" data-test="lab-params">
        <slot name="params" />
      </div>
      <div class="lab-canvas" data-test="lab-canvas">
        <slot name="canvas" />
      </div>
      <div class="lab-summary" data-test="lab-summary">
        <slot name="summary" />
      </div>
    </div>

    <div class="lab-queue" data-test="lab-queue">
      <slot name="queue" />
    </div>
  </div>
</template>

<style scoped>
.lab-layout {
  display: flex;
  flex-direction: column;
  gap: var(--s1-space-4);
}

.lab-context {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s1-space-3);
  flex-wrap: wrap;
}

.lab-title {
  display: flex;
  align-items: baseline;
  gap: var(--s1-space-3);
  min-width: 0;
}

.lab-title h2 {
  margin: 0;
  font-size: var(--s1-font-xl);
  color: var(--s1-text-strong);
}

.lab-dataset {
  font-size: var(--s1-font-sm);
  color: var(--s1-text-dim);
}

.lab-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr) minmax(0, 0.9fr);
  gap: var(--s1-space-4);
  align-items: start;
}

.lab-params,
.lab-canvas,
.lab-summary {
  min-width: 0;
}

.lab-queue {
  min-width: 0;
}

@media (max-width: 1100px) {
  .lab-grid {
    grid-template-columns: 1fr 1fr;
  }

  .lab-summary {
    grid-column: 1 / -1;
  }
}

@media (max-width: 640px) {
  .lab-grid {
    grid-template-columns: 1fr;
  }
}
</style>

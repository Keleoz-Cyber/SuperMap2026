<script setup lang="ts">
import PageNavigation from './PageNavigation.vue'

defineProps<{
  title: string
  subtitle?: string
  eyebrow?: string
  caseId?: string
  caseName?: string
  datasetId?: string
  experimentId?: string
  resultId?: string
  currentLabel?: string
}>()
</script>

<template>
  <header class="page-context" data-test="page-context-header">
    <PageNavigation
      :case-id="caseId"
      :case-name="caseName"
      :dataset-id="datasetId"
      :experiment-id="experimentId"
      :result-id="resultId"
      :current-label="currentLabel ?? title"
    />
    <div class="page-context__row">
      <div class="page-context__copy">
        <p v-if="eyebrow" class="page-context__eyebrow">{{ eyebrow }}</p>
        <h1>{{ title }}</h1>
        <p v-if="subtitle" class="page-context__subtitle">{{ subtitle }}</p>
        <slot name="meta" />
      </div>
      <div v-if="$slots.actions" class="page-context__actions">
        <slot name="actions" />
      </div>
    </div>
  </header>
</template>

<style scoped>
.page-context {
  display: grid;
  gap: var(--s1-space-3);
  margin-bottom: var(--s1-space-6);
}

.page-context__row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s1-space-6);
  min-width: 0;
}

.page-context__copy {
  min-width: 0;
}

.page-context__eyebrow,
.page-context__subtitle {
  margin: 0;
}

.page-context__eyebrow {
  color: var(--s1-case-accent, var(--s1-cyan));
  font-size: var(--s1-font-xs);
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

h1 {
  margin: var(--s1-space-1) 0 0;
  color: var(--s1-text-strong);
  font-size: var(--s1-font-3xl);
  line-height: var(--s1-leading-tight);
}

.page-context__subtitle {
  margin-top: var(--s1-space-2);
  color: var(--s1-text-dim);
  font-size: var(--s1-font-md);
  line-height: 1.5;
}

.page-context__actions {
  display: flex;
  align-items: center;
  gap: var(--s1-space-2);
  flex: 0 0 auto;
}

@media (max-width: 700px) {
  .page-context__row {
    align-items: stretch;
    flex-direction: column;
    gap: var(--s1-space-3);
  }

  .page-context__actions {
    width: 100%;
  }
}
</style>

<script setup lang="ts">
import { computed } from 'vue'
import type { MLCapability } from '../../api/types'

const props = defineProps<{ capability: MLCapability }>()

const title = computed(() => {
  if (props.capability.level === 'supported') return '适合机器学习空间对照'
  if (props.capability.level === 'experimental') return '仅建议实验性评估'
  return '当前数据不建议使用机器学习'
})
</script>

<template>
  <section
    class="ml-notice"
    :class="`is-${capability.level}`"
    data-test="ml-capability-notice"
  >
    <div>
      <span class="ml-notice-label">数据适用性</span>
      <strong>{{ title }}</strong>
      <p>{{ capability.message }}</p>
    </div>
    <dl>
      <div><dt>有效样本</dt><dd>{{ capability.valid_sample_count }} 个有效样本</dd></div>
      <div><dt>空间分组</dt><dd>{{ capability.spatial_group_count }} 个独立分组</dd></div>
      <div><dt>验证口径</dt><dd>空间交叉验证</dd></div>
    </dl>
  </section>
</template>

<style scoped>
.ml-notice {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(300px, 1fr);
  gap: 18px;
  padding: 14px 16px;
  border: 1px solid var(--gmp-border);
  border-left: 3px solid var(--s1-cyan);
  background: color-mix(in srgb, var(--gmp-bg-soft) 88%, var(--s1-cyan) 12%);
}
.ml-notice.is-experimental { border-left-color: #d6a84b; }
.ml-notice.is-not_recommended { border-left-color: #c76161; }
.ml-notice-label { display: block; margin-bottom: 4px; color: var(--gmp-text-faint); font-size: 11px; }
.ml-notice strong { color: var(--gmp-text); font-size: 14px; }
.ml-notice p { margin: 5px 0 0; color: var(--gmp-text-dim); font-size: 12px; line-height: 1.55; }
.ml-notice dl { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 0; }
.ml-notice dl > div { min-width: 0; padding-left: 10px; border-left: 1px solid var(--gmp-border); }
.ml-notice dt { color: var(--gmp-text-faint); font-size: 10px; }
.ml-notice dd { margin: 4px 0 0; color: var(--gmp-text); font-size: 12px; overflow-wrap: anywhere; }
@media (max-width: 720px) {
  .ml-notice { grid-template-columns: 1fr; }
  .ml-notice dl { grid-template-columns: 1fr; }
}
</style>

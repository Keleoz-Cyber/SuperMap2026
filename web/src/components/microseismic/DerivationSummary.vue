<script setup lang="ts">
import type { MicroseismicDerivation, MicroseismicMapping } from '../../api/types'

// 派生证据全部来自服务端响应；前端不做任何统计计算。
defineProps<{
  derivation: MicroseismicDerivation
  mapping: MicroseismicMapping
}>()

function formatValue(value: unknown): string {
  if (typeof value === 'string' && value.length > 16) return `${value.slice(0, 12)}…`
  if (typeof value === 'object' && value !== null) return JSON.stringify(value)
  return String(value)
}
</script>

<template>
  <div class="derivation-summary">
    <div class="summary-grid">
      <div class="summary-block">
        <h4>分层计数</h4>
        <dl class="kv" data-test="layer-counts">
          <div><dt>源记录</dt><dd>{{ derivation.layer_counts.source_records }}</dd></div>
          <div><dt>有限记录</dt><dd>{{ derivation.layer_counts.finite_records }}</dd></div>
          <div><dt>无效记录</dt><dd>{{ derivation.layer_counts.invalid_records }}</dd></div>
          <div><dt>3σ剔除</dt><dd>{{ derivation.layer_counts.rejected_3sigma }}</dd></div>
          <div><dt>黄金候选</dt><dd>{{ derivation.layer_counts.accepted_modeling }}</dd></div>
          <div><dt>唯一建模节点</dt><dd>{{ derivation.layer_counts.aggregated_nodes }}</dd></div>
        </dl>
      </div>

      <div class="summary-block">
        <h4>测线计数</h4>
        <dl class="kv" data-test="line-counts">
          <div v-for="(count, line) in derivation.line_counts" :key="line">
            <dt>{{ line }}</dt>
            <dd>{{ count }}</dd>
          </div>
        </dl>
      </div>

      <div class="summary-block">
        <h4>同坐标聚合证据</h4>
        <dl class="kv" data-test="aggregation-evidence">
          <div><dt>同坐标冲突组</dt><dd>{{ derivation.aggregation.conflict_group_count }}</dd></div>
          <div><dt>冲突记录</dt><dd>{{ derivation.aggregation.conflict_row_count }}</dd></div>
          <div><dt>折叠记录</dt><dd>{{ derivation.aggregation.collapsed_row_count }}</dd></div>
          <div><dt>组内最大值域</dt><dd>{{ derivation.aggregation.max_value_range }}</dd></div>
        </dl>
      </div>

      <div class="summary-block">
        <h4>坐标与 Z 规则</h4>
        <dl class="kv wide" data-test="coordinate-rules">
          <div><dt>坐标类型</dt><dd>{{ derivation.coordinates.coord_type }}</dd></div>
          <div><dt>深度规则</dt><dd>{{ derivation.coordinates.depth_rule }}</dd></div>
          <div><dt>Z 规则</dt><dd>{{ derivation.coordinates.z_rule }}</dd></div>
          <div><dt>Vx 单位</dt><dd>{{ derivation.coordinates.vx_unit }}</dd></div>
          <div><dt>绝对坐标系</dt><dd>{{ derivation.coordinates.absolute_crs }}</dd></div>
        </dl>
      </div>
    </div>

    <div class="summary-block">
      <h4>黄金基准比对</h4>
      <p class="golden-status" :class="{ ok: derivation.golden.passed, bad: !derivation.golden.passed }" data-test="golden-status">
        {{ derivation.golden.passed ? '黄金比对通过' : '黄金比对未通过' }}
        <span class="rule-version">规则 {{ derivation.rule_version }} · 适配器 {{ derivation.adapter_version }}</span>
      </p>
      <ul class="golden-checks" data-test="golden-checks">
        <li v-for="check in derivation.golden.checks" :key="check.name" :class="{ bad: !check.passed }">
          <span class="check-mark">{{ check.passed ? '✓' : '✗' }}</span>
          <span class="check-name">{{ check.name }}</span>
          <span class="check-values">期望 {{ formatValue(check.expected) }} · 实际 {{ formatValue(check.actual) }}</span>
        </li>
      </ul>
    </div>

    <div class="summary-block">
      <h4>自动字段映射（合同固定，只读）</h4>
      <dl class="kv wide" data-test="auto-mapping">
        <div><dt>X</dt><dd class="mono">{{ mapping.x }}</dd></div>
        <div><dt>Y</dt><dd class="mono">{{ mapping.y }}</dd></div>
        <div><dt>Z</dt><dd class="mono">{{ mapping.z ?? '—' }}</dd></div>
        <div><dt>value</dt><dd class="mono">{{ mapping.value }}</dd></div>
        <div><dt>属性名</dt><dd>{{ mapping.value_name }}</dd></div>
        <div><dt>单位</dt><dd>{{ mapping.value_unit ?? '—' }}</dd></div>
        <div><dt>坐标类型</dt><dd>{{ mapping.coordinate_kind }}</dd></div>
      </dl>
    </div>

    <div class="summary-block">
      <h4>可下载工件（逻辑名）</h4>
      <ul class="artifact-list" data-test="artifact-list">
        <li v-for="(artifact, name) in derivation.artifacts" :key="name">
          <span class="mono">{{ name }}</span>
          <span class="artifact-file mono">{{ artifact.file }}</span>
          <span class="artifact-meta">{{ artifact.rows }} 行 · sha256 {{ artifact.sha256.slice(0, 12) }}…</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.derivation-summary {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
}

.summary-block h4 {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--gmp-text-dim);
}

.kv {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kv div {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
  border: 1px solid var(--gmp-border);
  border-radius: 6px;
  padding: 6px 10px;
}

.kv.wide div {
  justify-content: flex-start;
}

.kv.wide dt {
  width: 90px;
  flex-shrink: 0;
}

.kv dt {
  color: var(--gmp-text-faint);
}

.kv dd {
  margin: 0;
  color: var(--gmp-text);
  font-weight: 600;
  text-align: right;
  word-break: break-all;
}

.mono {
  font-family: ui-monospace, monospace;
}

.golden-status {
  margin: 0 0 10px;
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 13px;
  border: 1px solid var(--gmp-border);
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.golden-status.ok {
  border-color: #2e7d4f;
  background: rgba(46, 125, 79, 0.15);
  color: #7fd6a4;
}

.golden-status.bad {
  border-color: #a43d3d;
  background: rgba(164, 61, 61, 0.15);
  color: #ef9a9a;
}

.rule-version {
  font-size: 12px;
  color: var(--gmp-text-faint);
}

.golden-checks,
.artifact-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.golden-checks li,
.artifact-list li {
  display: flex;
  gap: 10px;
  align-items: baseline;
  font-size: 13px;
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  padding: 8px 12px;
}

.check-mark {
  color: #7fd6a4;
  font-weight: 700;
}

.golden-checks li.bad .check-mark,
.golden-checks li.bad .check-name {
  color: #ef9a9a;
}

.check-name {
  font-family: ui-monospace, monospace;
  color: var(--gmp-text);
}

.check-values,
.artifact-meta {
  font-size: 12px;
  color: var(--gmp-text-faint);
  word-break: break-all;
}

.artifact-file {
  color: var(--gmp-text);
}
</style>

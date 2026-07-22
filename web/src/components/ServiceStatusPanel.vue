<script setup lang="ts">
import { computed } from 'vue'
import type { PublishStatus } from '../api/types'

const props = defineProps<{
  publishStatus: PublishStatus
  voxelBands?: number | null
}>()

const plannedEntries = computed(() => {
  const p = props.publishStatus.planned_services
  return [
    { label: '数据服务 data', url: p.data },
    { label: '地图服务 map', url: p.map },
    { label: '三维服务 realspace', url: p.realspace },
  ]
})

const hasImageFileLayer = computed(() =>
  props.publishStatus.service_checks.some((c) =>
    (c.detail.layers ?? []).some((l) => l.layer3DType === 'ImageFileLayer'),
  ),
)
</script>

<template>
  <div class="service-panel">
    <div class="sub-title">规划服务</div>
    <div class="planned-list">
      <div v-for="e in plannedEntries" :key="e.label" class="planned-row">
        <span class="planned-label">{{ e.label }}</span>
        <span class="mono planned-url break-all">{{ e.url }}</span>
      </div>
      <div class="planned-row">
        <span class="planned-label">场景名称</span>
        <span class="mono">{{ publishStatus.planned_services.scene_name }}</span>
      </div>
    </div>
    <el-alert :type="publishStatus.planned_services.volume.available ? 'success' : 'info'" :closable="false" class="s3m-tip">
      <template #title>
        <span class="s3m-text">S3M 体元缓存：{{ publishStatus.planned_services.volume.note }}</span>
      </template>
    </el-alert>

    <div class="sub-title">服务检查</div>
    <div v-for="c in publishStatus.service_checks" :key="c.name" class="service-card">
      <div class="service-head">
        <span class="dot" :class="c.reachable ? 'ok' : 'bad'"></span>
        <span class="service-name">{{ c.name }}</span>
        <el-tag size="small" effect="plain">{{ c.service_type }}</el-tag>
        <span v-if="c.http_status !== null" class="http-status mono">HTTP {{ c.http_status }}</span>
      </div>
      <div class="mono service-url break-all">{{ c.url }}</div>
      <div v-if="c.error" class="service-error">{{ c.error }}</div>

      <template v-if="c.detail.dataset_info">
        <div class="kv-grid">
          <div>
            <span>类型</span>
            <b>{{ c.detail.dataset_info.type }}</b>
          </div>
          <div>
            <span>网格</span>
            <b>
              {{ c.detail.dataset_info.width }} × {{ c.detail.dataset_info.height
              }}<template v-if="voxelBands"> × {{ voxelBands }}</template>
            </b>
          </div>
          <div>
            <span>值域</span>
            <b>
              {{ c.detail.dataset_info.minValue.toFixed(2) }} ~
              {{ c.detail.dataset_info.maxValue.toFixed(2) }}
            </b>
          </div>
          <div>
            <span>投影</span>
            <b>{{ c.detail.dataset_info.prjCoordSys }}</b>
          </div>
        </div>
        <div class="bounds mono">
          bounds: [{{ c.detail.dataset_info.bounds.left }}, {{ c.detail.dataset_info.bounds.right }}]
          × [{{ c.detail.dataset_info.bounds.bottom }}, {{ c.detail.dataset_info.bounds.top }}]
        </div>
        <div v-if="c.detail.mismatches && c.detail.mismatches.length" class="service-error">
          <div v-for="(m, i) in c.detail.mismatches" :key="i">{{ m }}</div>
        </div>
        <div v-else class="match-ok">✓ 与登记一致</div>
      </template>

      <template v-if="c.detail.scene_names">
        <div class="scene-names">
          <el-tag
            v-for="s in c.detail.scene_names"
            :key="s"
            size="small"
            effect="plain"
            class="scene-tag"
          >
            {{ s }}
          </el-tag>
        </div>
        <div v-for="l in c.detail.layers ?? []" :key="l.name" class="layer-row">
          <span class="mono break-all">{{ l.name }}</span>
          <el-tag size="small" type="warning" effect="plain">{{ l.layer3DType }}</el-tag>
          <span :class="l.visible ? 'match-ok' : 'service-error'">
            {{ l.visible ? '可见' : '隐藏' }}
          </span>
        </div>
        <p v-if="hasImageFileLayer" class="panel-note">
          当前图层类型 ImageFileLayer，即体元经工作空间发布为平面影像层。
        </p>
      </template>
    </div>
  </div>
</template>

<style scoped>
.planned-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.planned-row {
  display: flex;
  gap: 10px;
  font-size: 12px;
  line-height: 1.5;
}

.planned-label {
  flex: 0 0 108px;
  color: var(--gmp-text-faint);
}

.planned-url {
  color: var(--gmp-text-dim);
}

.s3m-tip {
  margin-top: 10px;
}

.s3m-text {
  font-size: 12px;
  line-height: 1.5;
}

.service-card {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border-soft);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 10px;
}

.service-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.service-name {
  font-size: 13px;
  font-weight: 600;
}

.http-status {
  color: var(--gmp-text-dim);
}

.service-url {
  color: var(--gmp-text-faint);
  margin: 6px 0;
}

.service-error {
  font-size: 12px;
  color: var(--gmp-red);
  line-height: 1.5;
}

.match-ok {
  font-size: 12px;
  color: var(--gmp-green);
}

.kv-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
  margin: 8px 0 6px;
}

.kv-grid div {
  display: flex;
  flex-direction: column;
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border-soft);
  border-radius: 6px;
  padding: 5px 8px;
}

.kv-grid span {
  font-size: 11px;
  color: var(--gmp-text-faint);
}

.kv-grid b {
  font-size: 12px;
  margin-top: 2px;
}

.bounds {
  color: var(--gmp-text-dim);
  margin-bottom: 6px;
}

.scene-names {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0;
}

.scene-tag {
  max-width: 100%;
  height: auto;
  white-space: normal;
  line-height: 1.4;
  padding-top: 2px;
  padding-bottom: 2px;
}

.layer-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 4px;
}
</style>

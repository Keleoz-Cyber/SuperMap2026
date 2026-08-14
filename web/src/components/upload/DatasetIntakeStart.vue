<script setup lang="ts">
import { computed } from 'vue'
import { Document, UploadFilled } from '@element-plus/icons-vue'

const props = defineProps<{
  mode: 'create' | 'version'
  file: File | null
  inputTest: string
  busy: boolean
  canSubmit: boolean
  error: string | null
  errorTest: string
  submitTest: string
}>()

const emit = defineEmits<{
  (e: 'file-change', event: Event): void
  (e: 'submit'): void
}>()

const title = computed(() => (props.mode === 'create' ? '创建案例并接入数据' : '新增数据版本'))
const description = computed(() =>
  props.mode === 'create'
    ? '先建立案例身份，再上传首个数据版本；后续字段映射和质量检查都在同一流程完成。'
    : '为当前案例追加一个独立数据版本，不会覆盖既有数据与成果。',
)
const submitLabel = computed(() =>
  props.mode === 'create' ? '创建并进入数据准备' : '上传并进入数据准备',
)
const busyLabel = computed(() =>
  props.mode === 'create'
    ? '正在创建案例并上传数据，文件较大时可能需要数秒'
    : '正在上传新数据版本，完成后将自动进入字段确认',
)
const fileType = computed(() => props.file?.name.split('.').pop()?.toUpperCase() ?? '文件')
const fileSize = computed(() => {
  if (!props.file) return ''
  const kib = props.file.size / 1024
  return kib >= 1024 ? `${(kib / 1024).toFixed(1)} MiB` : `${Math.max(1, Math.round(kib))} KiB`
})
</script>

<template>
  <section class="intake-start" data-test="intake-start-workbench">
    <header class="intake-heading">
      <div>
        <span class="eyebrow">数据接入</span>
        <h1 data-test="intake-mode-title">{{ title }}</h1>
        <p>{{ description }}</p>
      </div>
      <ol class="intake-steps" aria-label="数据准备流程">
        <li data-test="intake-step-upload" class="active"><b>1</b><span>选择数据</span></li>
        <li data-test="intake-step-map"><b>2</b><span>字段与坐标</span></li>
        <li data-test="intake-step-quality"><b>3</b><span>质量确认</span></li>
      </ol>
    </header>

    <div class="intake-body">
      <div class="intake-form">
        <slot name="before-file" />
        <label class="drop-zone" :class="{ selected: file }">
          <input
            class="file-input"
            :data-test="inputTest"
            type="file"
            accept=".csv,.xlsx"
            @change="emit('file-change', $event)"
          />
          <el-icon :size="28"><UploadFilled /></el-icon>
          <strong>{{ file ? '更换数据文件' : '选择 CSV 或 XLSX 文件' }}</strong>
          <span>单文件不超过 50 MiB，最多 50 万行</span>
        </label>

        <div v-if="file" class="file-summary" data-test="selected-file-summary">
          <el-icon><Document /></el-icon>
          <div><strong>{{ file.name }}</strong><span>{{ fileType }} · {{ fileSize }}</span></div>
          <span class="ready">已选择</span>
        </div>

        <div v-if="error" class="intake-error" :data-test="errorTest">{{ error }}</div>
        <div class="intake-actions">
          <el-button
            type="primary"
            :data-test="submitTest"
            :loading="busy"
            :disabled="!canSubmit"
            @click="emit('submit')"
          >{{ submitLabel }}</el-button>
          <slot name="secondary-action" />
        </div>
        <p
          v-if="busy"
          class="intake-busy-status"
          data-test="intake-busy-status"
          role="status"
          aria-live="polite"
        >
          <span class="intake-busy-dot" aria-hidden="true" />
          {{ busyLabel }}
        </p>
      </div>

      <aside class="intake-guide">
        <h2>文件准备要求</h2>
        <dl>
          <div><dt>坐标字段</dt><dd>至少包含 X、Y；三维建模还需 Z。</dd></div>
          <div><dt>属性字段</dt><dd>至少一个可转为有限数值的地质属性。</dd></div>
          <div><dt>后续处理</dt><dd>上传后仍会确认字段映射、单位和质量问题。</dd></div>
        </dl>
        <details>
          <summary>查看 CSV 示例</summary>
          <pre>x,y,z,value
100.0,200.0,-30.0,12.5</pre>
        </details>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.intake-start { display:flex; flex-direction:column; gap:22px; }
.intake-heading { display:flex; justify-content:space-between; gap:32px; align-items:end; }
.eyebrow { color:var(--s1-cyan-strong); font-size:var(--s1-font-sm); font-weight:600; }
.intake-heading h1 { margin:6px 0 8px; font-size:28px; }
.intake-heading p { margin:0; max-width:680px; color:var(--s1-text-dim); line-height:1.65; }
.intake-steps { display:flex; margin:0; padding:0; list-style:none; }
.intake-steps li { display:flex; align-items:center; gap:8px; color:var(--s1-text-faint); font-size:var(--s1-font-sm); white-space:nowrap; }
.intake-steps li:not(:last-child)::after { content:''; width:36px; height:1px; margin:0 10px; background:var(--s1-border); }
.intake-steps b { display:grid; place-items:center; width:24px; height:24px; border:1px solid var(--s1-border); border-radius:50%; }
.intake-steps .active { color:var(--s1-text); }
.intake-steps .active b { color:#081116; border-color:var(--s1-cyan); background:var(--s1-cyan); }
.intake-body { display:grid; grid-template-columns:minmax(0,1.7fr) minmax(280px,.8fr); border-block:1px solid var(--s1-border); }
.intake-form { min-width:0; padding:28px 32px 28px 0; display:flex; flex-direction:column; gap:18px; }
.intake-guide { padding:28px 0 28px 32px; border-left:1px solid var(--s1-border); }
.intake-guide h2 { margin:0 0 18px; font-size:var(--s1-font-lg); }
.intake-guide dl { margin:0; display:grid; gap:18px; }
.intake-guide dt { color:var(--s1-text); font-size:var(--s1-font-sm); font-weight:600; }
.intake-guide dd { margin:5px 0 0; color:var(--s1-text-dim); font-size:var(--s1-font-sm); line-height:1.55; }
.intake-guide details { margin-top:22px; color:var(--s1-text-dim); font-size:var(--s1-font-sm); }
.intake-guide summary { cursor:pointer; }
.intake-guide pre { overflow:auto; padding:12px; background:var(--s1-surface-2); border:1px solid var(--s1-border); }
.drop-zone { min-height:190px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px; border:1px dashed var(--s1-border-strong); background:var(--s1-surface-1); color:var(--s1-text-dim); cursor:pointer; }
.drop-zone:hover,.drop-zone.selected { border-color:var(--s1-cyan-dim); background:var(--s1-cyan-ghost); }
.drop-zone strong { color:var(--s1-text); }
.drop-zone span { font-size:var(--s1-font-sm); }
.file-input { position:absolute; width:1px; height:1px; opacity:0; }
.file-summary { display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:12px; align-items:center; padding:12px 14px; border:1px solid var(--s1-border); background:var(--s1-surface-1); }
.file-summary div { min-width:0; display:flex; flex-direction:column; gap:3px; }
.file-summary strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.file-summary span { color:var(--s1-text-faint); font-size:var(--s1-font-xs); }
.file-summary .ready { color:var(--s1-success); }
.intake-error { padding:10px 14px; border:1px solid rgba(224,104,94,.5); background:rgba(224,104,94,.12); color:var(--s1-error); }
.intake-actions { display:flex; gap:12px; align-items:center; }
.intake-busy-status { margin:0; display:flex; align-items:center; gap:8px; color:var(--s1-cyan-strong); font-size:var(--s1-font-sm); animation:gmp-intake-status-in var(--s1-motion-base) var(--s1-ease-out) both; }
.intake-busy-dot { width:8px; height:8px; flex:none; border-radius:50%; background:var(--s1-cyan); animation:gmp-intake-pulse 1.15s var(--s1-ease-in-out) infinite; }
@keyframes gmp-intake-status-in { from { opacity:0; transform:translateY(-3px); } to { opacity:1; transform:translateY(0); } }
@keyframes gmp-intake-pulse { 0%,100% { opacity:.4; transform:scale(.8); } 50% { opacity:1; transform:scale(1.15); } }
@media (max-width:800px) {
  .intake-heading { align-items:start; flex-direction:column; }
  .intake-steps { width:100%; justify-content:space-between; }
  .intake-steps li:not(:last-child)::after { width:18px; }
  .intake-body { grid-template-columns:1fr; }
  .intake-form { padding:22px 0; }
  .intake-guide { padding:22px 0; border-left:0; border-top:1px solid var(--s1-border); }
}
@media (max-width:480px) {
  .intake-steps span { display:none; }
  .intake-steps li:not(:last-child)::after { width:64px; }
  .intake-heading h1 { font-size:24px; }
}
</style>

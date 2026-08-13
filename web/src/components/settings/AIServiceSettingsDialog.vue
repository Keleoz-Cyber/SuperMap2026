<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  ApiError,
  clearAISettings,
  fetchAISettings,
  saveAISettings,
  testAISettings,
} from '../../api/client'
import type { AISettingsPayload, AISettingsStatus } from '../../api/types'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
  (event: 'configured', value: AISettingsStatus): void
}>()

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const clearing = ref(false)
const status = ref<AISettingsStatus | null>(null)
const feedback = ref<{ kind: 'ok' | 'error' | 'info'; text: string } | null>(null)
const form = reactive<AISettingsPayload>({
  api_key: '',
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-v4-flash',
  timeout_sec: 90,
  max_tokens: 4096,
})

const sourceLabel = computed(() => {
  if (status.value?.source === 'environment') return '已由环境变量配置（只读）'
  if (status.value?.source === 'windows_credential') return '已安全保存到 Windows 凭据管理器'
  return '尚未配置'
})

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.code}：${error.message}` : String(error)
}

function applyStatus(value: AISettingsStatus) {
  status.value = value
  form.base_url = value.base_url
  form.model = value.model
  form.timeout_sec = value.timeout_sec
  form.max_tokens = value.max_tokens
  form.api_key = ''
}

async function load() {
  loading.value = true
  feedback.value = null
  try {
    applyStatus(await fetchAISettings())
  } catch (error) {
    feedback.value = { kind: 'error', text: errorText(error) }
  } finally {
    loading.value = false
  }
}

async function testConnection() {
  testing.value = true
  feedback.value = null
  try {
    const result = await testAISettings({
      ...(form.api_key ? { api_key: form.api_key } : {}),
      base_url: form.base_url,
      model: form.model,
      timeout_sec: form.timeout_sec,
      max_tokens: form.max_tokens,
    })
    feedback.value = { kind: result.ok ? 'ok' : 'error', text: `${result.code}：${result.message}` }
  } catch (error) {
    feedback.value = { kind: 'error', text: errorText(error) }
  } finally {
    testing.value = false
  }
}

async function save() {
  if (!form.api_key.trim()) {
    feedback.value = { kind: 'error', text: '请输入 API Key 后再保存' }
    return
  }
  saving.value = true
  feedback.value = null
  try {
    const next = await saveAISettings({ ...form, api_key: form.api_key.trim() })
    applyStatus(next)
    feedback.value = { kind: 'ok', text: '配置已安全保存，无需重启平台' }
    emit('configured', next)
  } catch (error) {
    feedback.value = { kind: 'error', text: errorText(error) }
  } finally {
    saving.value = false
  }
}

async function clearCredential() {
  clearing.value = true
  feedback.value = null
  try {
    const next = await clearAISettings()
    applyStatus(next)
    feedback.value = { kind: 'info', text: '本机保存的 API Key 已清除' }
    emit('configured', next)
  } catch (error) {
    feedback.value = { kind: 'error', text: errorText(error) }
  } finally {
    clearing.value = false
  }
}

watch(
  () => props.modelValue,
  (open) => { if (open) void load() },
  { immediate: true },
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="AI 服务设置"
    width="min(560px, calc(100vw - 32px))"
    :teleported="false"
    data-test="ai-settings-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-loading="loading" class="settings-body">
      <div class="status-card" data-test="ai-settings-status">
        <span class="status-dot" :class="status?.configured ? 'configured' : 'empty'" />
        <div>
          <strong>{{ sourceLabel }}</strong>
          <p>AI 为可选辅助能力；未配置时不影响数据校验、插值、三维展示和规则分析。</p>
        </div>
      </div>

      <el-form label-position="top">
        <el-form-item label="DeepSeek API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="输入后可测试或保存；已保存的 Key 不会回显"
            :disabled="status?.editable === false"
            data-test="ai-settings-key"
          />
        </el-form-item>
        <div class="two-column">
          <el-form-item label="模型">
            <el-select v-model="form.model" :disabled="status?.editable === false">
              <el-option label="DeepSeek V4 Flash（推荐）" value="deepseek-v4-flash" />
              <el-option label="DeepSeek V4 Pro" value="deepseek-v4-pro" />
            </el-select>
          </el-form-item>
          <el-form-item label="服务地址">
            <el-input v-model="form.base_url" disabled />
          </el-form-item>
        </div>
      </el-form>

      <p
        v-if="feedback"
        class="feedback"
        :class="feedback.kind"
        role="status"
        data-test="ai-settings-feedback"
      >{{ feedback.text }}</p>

      <p class="security-note">
        Key 仅发送到本机后端并由当前 Windows 用户的凭据管理器保存；不会写入浏览器、项目文件、SQLite、日志、成果包或 Git。
      </p>
    </div>

    <template #footer>
      <button
        type="button"
        class="dialog-action danger"
        :disabled="!status?.configured || status?.editable === false || clearing"
        data-test="ai-settings-clear"
        @click="clearCredential"
      >清除密钥</button>
      <span class="footer-spacer" />
      <button type="button" class="dialog-action" :disabled="testing" data-test="ai-settings-test" @click="testConnection">
        {{ testing ? '检测中…' : '测试连接' }}
      </button>
      <button
        type="button"
        class="dialog-action primary"
        :disabled="status?.editable === false || saving"
        data-test="ai-settings-save"
        @click="save"
      >{{ saving ? '保存中…' : '保存配置' }}</button>
    </template>
  </el-dialog>
</template>

<style scoped>
.settings-body { display: grid; gap: 16px; }
.status-card { display: flex; gap: 12px; padding: 14px; border: 1px solid var(--s1-border); border-radius: var(--s1-radius-md); background: var(--s1-surface-2); }
.status-card p { margin: 5px 0 0; color: var(--s1-text-dim); font-size: var(--s1-font-sm); line-height: 1.6; }
.status-dot { flex: 0 0 auto; width: 9px; height: 9px; margin-top: 6px; border-radius: 50%; }
.status-dot.configured { background: var(--s1-success); box-shadow: 0 0 8px color-mix(in srgb, var(--s1-success) 55%, transparent); }
.status-dot.empty { background: var(--s1-warning); }
.two-column { display: grid; grid-template-columns: 0.8fr 1.2fr; gap: 12px; }
.feedback { margin: 0; padding: 9px 12px; border-radius: var(--s1-radius-sm); font-size: var(--s1-font-sm); }
.feedback.ok { color: var(--s1-success); background: color-mix(in srgb, var(--s1-success) 10%, transparent); }
.feedback.error { color: var(--s1-danger); background: color-mix(in srgb, var(--s1-danger) 10%, transparent); }
.feedback.info { color: var(--s1-cyan-strong); background: var(--s1-cyan-ghost); }
.security-note { margin: 0; color: var(--s1-text-faint); font-size: var(--s1-font-sm); line-height: 1.65; }
.dialog-action { padding: 8px 14px; border: 1px solid var(--s1-border); border-radius: var(--s1-radius-sm); color: var(--s1-text); background: transparent; cursor: pointer; }
.dialog-action.primary { color: #06110f; border-color: var(--s1-cyan); background: var(--s1-cyan-strong); }
.dialog-action.danger { color: #eb6a5b; }
.dialog-action:disabled { opacity: 0.45; cursor: not-allowed; }
.footer-spacer { display: inline-block; width: 12px; }
@media (max-width: 560px) { .two-column { grid-template-columns: 1fr; } }
</style>

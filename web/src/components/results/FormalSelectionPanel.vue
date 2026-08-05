<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ApiError, fetchFormalSelections, selectFormal } from '../../api/client'
import type { FormalSelectionRecord } from '../../api/types'

const props = defineProps<{
  resultId: string
  caseId: string
}>()

const selections = ref<FormalSelectionRecord[]>([])
// 能力未知默认不可写：仅成功响应明确允许后才显示选择表单；
// 请求失败保持隐藏（后端 409 仍是最终防线）
const selectionAllowed = ref(false)
const note = ref('')
const selectedBy = ref('')
const error = ref<string | null>(null)
const submitting = ref(false)

async function refresh() {
  try {
    const body = await fetchFormalSelections(props.caseId)
    selections.value = body.selections
    selectionAllowed.value = body.selection_allowed !== false
  } catch {
    // 列表/能力加载失败：保持不可写，不阻塞只读展示
  }
}

onMounted(async () => {
  try {
    await refresh()
  } catch {
    // 列表加载失败不阻塞选择操作
  }
})

async function submit() {
  error.value = null
  // 理由必填：正式选择的可追溯性不接受空备注
  if (!note.value.trim()) {
    error.value = '必须填写选择理由（公共验证指标依据或人工判断说明）'
    return
  }
  submitting.value = true
  try {
    await selectFormal(props.resultId, note.value.trim(), selectedBy.value.trim() || undefined)
    note.value = ''
    await refresh()
  } catch (e) {
    error.value = e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="panel" data-test="formal-selection-panel">
    <h3>正式模型选择</h3>
    <ul v-if="selections.length" class="selection-list">
      <li v-for="item in selections" :key="item.id" data-test="selection-item">
        <span class="when">{{ item.created_at.slice(0, 19).replace('T', ' ') }}</span>
        <span class="who">{{ item.selected_by ?? '未署名' }}</span>
        <span class="why">{{ item.note }}</span>
      </li>
    </ul>
    <p v-else class="empty">尚未选择正式模型</p>

    <div v-if="selectionAllowed" class="selection-form">
      <input
        v-model="note"
        class="gmp-input"
        data-test="selection-note"
        placeholder="选择理由（必填）：如 公共验证 RMSE 最低且覆盖率最高"
        maxlength="2000"
      />
      <input
        v-model="selectedBy"
        class="gmp-input who"
        data-test="selection-by"
        placeholder="选择人（可选）"
        maxlength="128"
      />
      <button class="gmp-btn primary" data-test="selection-submit" :disabled="submitting" @click="submit">
        登记为正式模型
      </button>
    </div>
    <p v-else class="readonly-note" data-test="selection-readonly">
      官方案例为只读：正式成果已由官方登记，不能另行选择。
    </p>
    <p v-if="error" class="selection-error" data-test="selection-error">{{ error }}</p>
  </section>
</template>

<style scoped>
.panel {
  background: var(--gmp-card);
  border: 1px solid var(--gmp-border);
  border-radius: 12px;
  padding: 16px 18px;
}

.panel h3 {
  margin: 0 0 12px;
  font-size: 15px;
}

.selection-list {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.selection-list li {
  display: flex;
  gap: 12px;
  font-size: 12px;
  border: 1px solid var(--gmp-border);
  border-radius: 8px;
  padding: 8px 12px;
}

.when {
  color: var(--gmp-text-faint);
}

.who {
  color: var(--gmp-text-dim);
}

.empty {
  color: var(--gmp-text-faint);
  font-size: 12px;
}

.selection-form {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.gmp-input {
  flex: 1;
  min-width: 220px;
  background: var(--gmp-bg-soft);
  border: 1px solid var(--gmp-border);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
}

.gmp-input.who {
  flex: 0 1 160px;
  min-width: 120px;
}

.gmp-btn {
  border: 1px solid var(--gmp-border);
  background: var(--gmp-bg-soft);
  color: var(--gmp-text);
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 13px;
  cursor: pointer;
}

.gmp-btn.primary {
  background: var(--gmp-accent);
  border-color: var(--gmp-accent);
  color: #0b0f14;
  font-weight: 600;
}

.gmp-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.selection-error {
  color: #ef9a9a;
  font-size: 12px;
  margin: 8px 0 0;
}
</style>

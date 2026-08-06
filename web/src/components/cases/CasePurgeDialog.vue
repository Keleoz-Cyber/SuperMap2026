<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = defineProps<{
  visible: boolean
  caseName: string
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  confirm: [name: string]
  close: []
}>()

const typedName = ref('')

watch(
  () => props.visible,
  (val) => {
    if (val) {
      typedName.value = ''
    }
  },
)

const isMatch = computed(() => typedName.value === props.caseName)

function handleVisibleChange(val: boolean) {
  if (!val) {
    emit('update:visible', false)
    emit('close')
  }
}

function handleConfirm() {
  if (!isMatch.value) return
  emit('confirm', typedName.value)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="永久删除确认"
    width="440px"
    :close-on-click-modal="false"
    data-test="purge-dialog"
    @update:model-value="handleVisibleChange"
  >
    <p class="purge-warning">
      此操作不可恢复。请输入案例名称 <b>{{ caseName }}</b> 以确认永久删除。
    </p>
    <el-input
      v-model="typedName"
      data-test="purge-name-input"
      placeholder="输入案例名称以确认"
    />
    <template #footer>
      <el-button @click="handleVisibleChange(false)">取消</el-button>
      <el-button
        type="danger"
        :disabled="!isMatch"
        data-test="purge-confirm-btn"
        @click="handleConfirm"
      >
        永久删除
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.purge-warning {
  margin: 0 0 16px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--gmp-text);
}

.purge-warning b {
  color: var(--gmp-accent);
}
</style>

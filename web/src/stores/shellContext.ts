// v0.9.0：全局壳上下文。当前页面把业务身份（案例/阶段）登记到这里，
// AppHeader 只负责展示，不主动 fetch 页面数据，也不解析路由参数猜身份。

import { reactive, readonly } from 'vue'

export interface ShellContext {
  caseId: string | null
  caseTitle: string | null
  stageLabel: string | null
  // 与 CASE_PRESENTATION.accent 对应的案例辅助色键
  caseAccent: 'gold' | 'violet' | 'jade' | 'cyan' | null
  datasetId: string | null
  experimentId: string | null
  resultId: string | null
}

const context = reactive<ShellContext>({
  caseId: null,
  caseTitle: null,
  stageLabel: null,
  caseAccent: null,
  datasetId: null,
  experimentId: null,
  resultId: null,
})

export function setShellContext(patch: Partial<ShellContext>): void {
  Object.assign(context, patch)
}

export function clearShellContext(): void {
  context.caseId = null
  context.caseTitle = null
  context.stageLabel = null
  context.caseAccent = null
  context.datasetId = null
  context.experimentId = null
  context.resultId = null
}

export function useShellContext() {
  return readonly(context)
}

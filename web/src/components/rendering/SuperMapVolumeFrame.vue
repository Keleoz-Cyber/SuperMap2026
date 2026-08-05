<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { DisplayTransform, PointLayerPayload, RenderAssetRecord, RenderIdentity } from '../../api/types'
import {
  buildApplyRenderState,
  buildFrameUrl,
  buildInitMessage,
  buildResetView,
  buildSetPointLayer,
  isVolumeFrameEvent,
  newFrameRequestId,
  parseChildMessage,
  type FrameCapabilities,
  type ParentMessageV2,
  type RenderStateV2,
} from './renderProtocol'

// 父页面侧 v2 安全桥：iframe 生命周期 + 四重校验 + revision 单调跟踪。
// INIT 只在新 FRAME_READY 后发送（每次握手恰好一次，携带完整初始状态）；
// applyRenderState 拒绝非单调 revision；STATE_APPLIED 只在等于最新发送
// revision 时向上派发；requestId 每实例随机，资产变化由父级 key 重挂。

const props = defineProps<{
  asset: RenderAssetRecord | null
  displayTransform: DisplayTransform
  initialState: RenderStateV2
}>()

const emit = defineEmits<{
  ready: [info: { sdkVersion: string; contextType: number; capabilities: FrameCapabilities }]
  rendered: [identity: RenderIdentity | null]
  applied: [ack: { commandId: string; revision: number; appliedState: RenderStateV2 }]
  'command-applied': [ack: { commandId: string; commandType: 'SET_POINT_LAYER' | 'RESET_VIEW' }]
  failed: [error: { code: string; message: string; commandId?: string; revision?: number }]
}>()

const requestId = newFrameRequestId()
const frameUrl = computed(() => buildFrameUrl(requestId))
const iframeRef = ref<HTMLIFrameElement | null>(null)

// postMessage 走结构化克隆：Vue 响应式 Proxy 不可克隆（DataCloneError）。
function toWire(msg: ParentMessageV2): ParentMessageV2 {
  return JSON.parse(JSON.stringify(msg)) as ParentMessageV2
}

function post(msg: ParentMessageV2) {
  const target = iframeRef.value?.contentWindow
  if (!target) return
  // 目标 origin 恒为本源，绝不 "*"
  target.postMessage(toWire(msg), window.location.origin)
}

function newCommandId(): string {
  return `cmd-${crypto.randomUUID()}`
}

// 最新发送 revision：STATE_APPLIED 只在严格等于时向上派发
let lastSentRevision = 0

function sendInit() {
  post(buildInitMessage(requestId, props.asset, props.displayTransform, props.initialState))
}

function onMessage(event: MessageEvent) {
  const expected = iframeRef.value?.contentWindow ?? null
  if (!isVolumeFrameEvent(event, expected, requestId)) return
  const msg = parseChildMessage(event.data)
  if (!msg) return
  switch (msg.type) {
    case 'FRAME_READY':
      // 每次新的握手恰好一次 INIT（携带完整初始状态）
      sendInit()
      emit('ready', {
        sdkVersion: msg.sdkVersion,
        contextType: msg.contextType,
        capabilities: msg.capabilities,
      })
      return
    case 'RENDER_STATE':
      if (msg.phase === 'rendered') emit('rendered', msg.identity)
      return
    case 'STATE_APPLIED':
      // 旧回执不得把 UI 标成已应用
      if (msg.revision === lastSentRevision) {
        emit('applied', {
          commandId: msg.commandId,
          revision: msg.revision,
          appliedState: msg.appliedState,
        })
      }
      return
    case 'COMMAND_APPLIED':
      emit('command-applied', { commandId: msg.commandId, commandType: msg.commandType })
      return
    case 'ERROR':
      emit('failed', {
        code: msg.code,
        message: msg.message,
        commandId: msg.commandId,
        revision: msg.revision,
      })
  }
}

onMounted(() => {
  window.addEventListener('message', onMessage)
})

onBeforeUnmount(() => {
  window.removeEventListener('message', onMessage)
})

// ---------------------------------------------------------------------------
// 命令方法（父级经模板引用调用）
// ---------------------------------------------------------------------------

function applyRenderState(state: RenderStateV2): boolean {
  if (!Number.isInteger(state.revision) || state.revision <= lastSentRevision) return false
  lastSentRevision = state.revision
  post(buildApplyRenderState(requestId, newCommandId(), state))
  return true
}

function setPointLayer(layer: PointLayerPayload) {
  post(buildSetPointLayer(requestId, newCommandId(), layer))
}

function resetView() {
  post(buildResetView(requestId, newCommandId()))
}

defineExpose({ requestId, applyRenderState, setPointLayer, resetView })
</script>

<template>
  <div class="volume-frame" data-test="volume-frame">
    <iframe
      ref="iframeRef"
      class="volume-frame-iframe"
      :src="frameUrl"
      title="SuperMap3D NetCDF 原生体渲染"
    />
  </div>
</template>

<style scoped>
.volume-frame {
  width: 100%;
  aspect-ratio: 16 / 9;
  min-height: 420px;
  max-height: 680px;
  border: 1px solid var(--gmp-border);
  border-radius: 10px;
  overflow: hidden;
  background: #000;
}

.volume-frame-iframe {
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
}
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import type { DisplayTransform, PointLayerPayload, RenderAssetRecord, RenderIdentity } from '../../api/types'
import {
  VOLUME_FRAME_PROTOCOL,
  buildFrameUrl,
  isVolumeFrameEvent,
  newFrameRequestId,
  parseChildMessage,
  type ParentMessage,
  type VolumeMode,
} from './renderProtocol'

// 父页面侧安全桥：iframe 生命周期 + 四重校验 + 命令方法。
// INIT 只在新 FRAME_READY 后发送（每次握手恰好一次）；requestId 每实例随机，
// 资产身份变化应由父级通过 key 重挂本组件（新 requestId、新握手、新 INIT）。

const props = defineProps<{
  asset: RenderAssetRecord | null
  displayTransform: DisplayTransform
}>()

const emit = defineEmits<{
  ready: [info: { sdkVersion: string; contextType: number }]
  rendered: [identity: RenderIdentity | null]
  failed: [error: { code: string; message: string }]
}>()

const requestId = newFrameRequestId()
const frameUrl = computed(() => buildFrameUrl(requestId))
const iframeRef = ref<HTMLIFrameElement | null>(null)

// postMessage 走结构化克隆：Vue 响应式 Proxy 不可克隆（DataCloneError）。
// 协议消息本就是纯 JSON 形态，出站一律深拷贝为纯数据后再发送。
function toWire(msg: ParentMessage): ParentMessage {
  return JSON.parse(JSON.stringify(msg)) as ParentMessage
}

function post(msg: ParentMessage) {
  const target = iframeRef.value?.contentWindow
  if (!target) return
  // 目标 origin 恒为本源，绝不 "*"
  target.postMessage(toWire(msg), window.location.origin)
}

function sendInit() {
  post({
    protocol: VOLUME_FRAME_PROTOCOL,
    type: 'INIT',
    requestId,
    asset: props.asset,
    displayTransform: props.displayTransform,
  })
}

function onMessage(event: MessageEvent) {
  const expected = iframeRef.value?.contentWindow ?? null
  if (!isVolumeFrameEvent(event, expected, requestId)) return
  const msg = parseChildMessage(event.data)
  if (!msg) return
  if (msg.type === 'FRAME_READY') {
    // 每次新的 FRAME_READY 恰好触发一次 INIT（重发只发生在新的握手之后）。
    // INIT 必须先于 'ready' 事件发出：父级 ready 回调会立即推送点层，
    // 子帧要求 INIT 先于 SET_POINT_LAYER（否则 POINT_LAYER_INVALID）。
    sendInit()
    emit('ready', { sdkVersion: msg.sdkVersion, contextType: msg.contextType })
    return
  }
  if (msg.type === 'RENDER_STATE') {
    if (msg.phase === 'rendered') emit('rendered', msg.identity)
    return
  }
  emit('failed', { code: msg.code, message: msg.message })
}

onMounted(() => {
  window.addEventListener('message', onMessage)
})

onBeforeUnmount(() => {
  window.removeEventListener('message', onMessage)
})

// ---------------------------------------------------------------------------
// 命令方法（父级经模板引用调用；非法输入在出站前拦截，与子帧守卫同语义）
// ---------------------------------------------------------------------------

function setMode(mode: VolumeMode) {
  post({ protocol: VOLUME_FRAME_PROTOCOL, type: 'SET_MODE', requestId, mode })
}

function setFilter(min: number, max: number) {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min > max) return
  post({ protocol: VOLUME_FRAME_PROTOCOL, type: 'SET_FILTER', requestId, min, max })
}

function setOpacity(opacity: number) {
  if (!Number.isFinite(opacity)) return
  const clamped = Math.min(1, Math.max(0, opacity))
  post({ protocol: VOLUME_FRAME_PROTOCOL, type: 'SET_OPACITY', requestId, opacity: clamped })
}

function setPointLayer(layer: PointLayerPayload) {
  post({ protocol: VOLUME_FRAME_PROTOCOL, type: 'SET_POINT_LAYER', requestId, layer })
}

function resetView() {
  post({ protocol: VOLUME_FRAME_PROTOCOL, type: 'RESET_VIEW', requestId })
}

defineExpose({ requestId, setMode, setFilter, setOpacity, setPointLayer, resetView })
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

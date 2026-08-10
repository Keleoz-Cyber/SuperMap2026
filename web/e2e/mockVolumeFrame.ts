// gmp-supermap-volume/v2 协议 mock 子帧（无 SuperMap3D SDK）：与
// web/public/supermap-volume-frame/app.js 同一份信封纪律（request_id 关联、
// 目标 origin 恒为本源），但不做任何 SDK 调用；INIT 后按 asset 回
// RENDER_STATE，命令回 STATE_APPLIED / COMMAND_APPLIED，并记录全部父级
// 消息供断言。mock e2e 只证明协议与产品接线正确，绝不宣称真实渲染。

/** 安装同源路由拦截，以协议 mock 子帧替代真实体渲染 iframe。 */
export const MOCK_VOLUME_FRAME_PATH = '/supermap-volume-frame/index.html'

export const MOCK_VOLUME_FRAME_HTML = `<!doctype html>
<html><head><meta charset="utf-8"><style>html,body{margin:0;height:100%;background:#05080c}</style></head><body>
<script>
(function () {
  var PROTOCOL = 'gmp-supermap-volume/v2'
  var requestId = new URLSearchParams(window.location.search).get('request_id') || ''
  var received = []
  window.__GMP_MOCK_FRAME__ = { requestId: requestId, received: received }
  function post(msg) {
    var out = { protocol: PROTOCOL, requestId: requestId }
    for (var k in msg) out[k] = msg[k]
    window.parent.postMessage(out, window.location.origin)
  }
  window.addEventListener('message', function (event) {
    var msg = event.data
    if (!msg || msg.protocol !== PROTOCOL || msg.requestId !== requestId) return
    received.push(msg)
    if (msg.type === 'INIT') {
      var asset = msg.asset
      post({
        type: 'RENDER_STATE',
        phase: asset ? 'rendered' : 'unsupported',
        identity: asset
          ? {
              sourceKind: asset.source_kind,
              sourceId: asset.source_id,
              gridSha256: asset.grid_sha256,
              netcdfSha256: asset.netcdf_sha256,
            }
          : null,
      })
    } else if (msg.type === 'APPLY_RENDER_STATE') {
      post({
        type: 'STATE_APPLIED',
        commandId: msg.commandId,
        revision: msg.state.revision,
        appliedState: msg.state,
      })
    } else if (
      msg.type === 'SET_POINT_LAYER' ||
      msg.type === 'RESET_VIEW' ||
      msg.type === 'SET_CAMERA_PRESET' ||
      msg.type === 'FOCUS_ANNOTATION'
    ) {
      post({ type: 'COMMAND_APPLIED', commandId: msg.commandId, commandType: msg.type })
    }
  })
  // mock e2e 用：模拟三维标注点击（真实子帧由 pick 路径发出 ANNOTATION_SELECTED）
  window.__GMP_MOCK_SELECT__ = function (annotationId) {
    post({ type: 'ANNOTATION_SELECTED', annotationId: annotationId })
  }
  post({
    type: 'FRAME_READY',
    sdkVersion: 'mock-frame/0',
    contextType: 2,
    capabilities: {
      singleAxisSlice: true,
      lighting: true,
      gradientOpacity: true,
      boundingBox: true,
      transferFunction: true,
    },
  })
})()
</script>
</body></html>`

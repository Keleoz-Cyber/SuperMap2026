# warm-cache 升级黑屏：根因复现证据（修复前代码）

本目录记录 PR #13 发布阻断的根因复现（一次性诊断脚本在修复前代码上运行，
脚本本体不入库；修复后的四场景回归证据见 `run-*-warm-cache/`）。

## 场景

- 持久化 Chromium profile；v0.6.1 dist（v1 协议对）经真实静态托管建立旧会话
  （iframe 资产 Last-Modified 设为 7 天前 → RFC 7234 启发式缓存 ~16.8h）；
  渲染成功后关闭。
- 同一 profile、同一端口换当前 dist（v2 父页，index/主包 mtime 刷为现在以
  模拟重新部署），普通刷新，不清缓存。

## 结论（warm-cache-repro.json verdict）

- A 阶段：v1 父页 + v1 子帧，1.0s rendered，一切正常。
- B 阶段：v2 父页 + **缓存中的 v1 app.js**（`B_appjs_from_cache=true`）：
  子帧发出 v1 `FRAME_READY`，父页按 v2 协议四重校验静默丢弃；父页永不发送
  INIT → 子帧空转 → 永久黑屏（`待初始化`），无类型化错误、无渲染身份。
- 附带发现：若重新部署的 dist 文件 mtime 早于客户端缓存的 Last-Modified，
  If-Modified-Since 重验证会 304 让旧父页继续存活——版本化必须基于内容哈希
  而非 mtime。

## 文件

- `warm-cache-repro.json`：双阶段相位/身份/diag/协议消息/缓存命中全量记录；
- `A-old-version-rendered-page.png`：旧版本会话正常渲染；
- `B-after-upgrade-refresh-page.png`：升级后黑屏（资产 ready、无渲染身份、
  相位停在待初始化）。

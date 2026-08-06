/// <reference types="vite/client" />

// vite.config.ts 构建期注入：体渲染 iframe 运行时与 SDK 的内容版本（warm-cache 升级安全）
declare const __VOLUME_FRAME_VERSION__: string
declare const __VOLUME_SDK_VERSION__: string

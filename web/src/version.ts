// 前端版本唯一来源：package.json（由 npm version 与发布门禁统一维护）。
// `with { type: 'json' }` 是 Node/Playwright 直接执行时的必需属性；Vite 同样接受。
import pkg from '../package.json' with { type: 'json' }

export const WEB_VERSION: string = pkg.version

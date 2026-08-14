# web 前端

Vue 3 + TypeScript + Vite 单页应用，构建产物由 FastAPI StaticFiles 托管（`base: './'` 相对路径 + 哈希路由，保证深链刷新不 404）。

## 常用命令（Node 22）

```powershell
npm --prefix web ci
npm --prefix web run dev          # 开发（/api 代理到 127.0.0.1:8000）
npm --prefix web run build        # 构建 -> web/dist
npm --prefix web run type-check   # vue-tsc
npm --prefix web run test:unit    # Vitest
npm --prefix web run test:e2e     # Playwright Mock E2E（preview + mock API）
npm --prefix web run test:e2e:live -- e2e-live/platform-live.spec.ts   # 真实后端 Live E2E
```

## 结构与约定

- `src/api/client.ts`：全部 HTTP 的唯一封装（错误封套解析、FormData 上传、blob 下载）；`src/api/types.ts` 为 DTO 类型层。
- `src/views/`：13 个路由视图；`src/components/` 按域分 15 个子目录（多数带 `__tests__`）。
- 状态：无全局状态库；组件局部状态 + 单调请求序号守卫防竞态；长任务为 setInterval 轮询（无 WebSocket）。
- `public/SuperMap3D-2026/`：SuperMap3D SDK（不入库，由 `scripts/install_supermap3d.py` 安装并钉哈希）。
- `public/supermap-volume-frame/`：体渲染隔离 iframe 运行时（协议 `gmp-supermap-volume/v2`），构建期注入内容哈希实现缓存安全升级。
- `src/mocks/`：仅自动化测试使用的 mock API，不进生产业务。
- 纪律：POST 是唯一显式变异；统计一律后端权威计算；浏览器不伪造零值证据。

## 相关文档

- 架构与渲染链：[docs/architecture.md](../docs/architecture.md)
- API 参考：[docs/api-reference.md](../docs/api-reference.md)

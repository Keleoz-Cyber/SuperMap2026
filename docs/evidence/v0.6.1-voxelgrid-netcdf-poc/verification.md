# v0.6.1 VoxelGridLayer3D + NetCDF POC 验收记录

> 日期：2026-08-04。结论：**`voxelgrid_netcdf_poc_verified`**。
> 任务书：`docs/v0.6.1-supermap-voxelgrid-netcdf-poc.md`。本记录只写实测事实，机器可读证据在本目录。

## 1. 验证的问题与答案

> 项目物化的三维规则网格能否不经 iDesktopX/iServer/S3M/载体模型，转换为 NetCDF v3 后由 SuperMap3D 12.1 的 `VoxelGridLayer3D` 在浏览器直接完成彩色连续体渲染？

**能。** 固定成果 `35348bb3-be03-4862-b764-ee165ae0c7dc`（IDW，11×11×11）经 `grid.npz → volume.nc（classic/v3）→ API → scene.addVoxelGridLayer → startRender → VolumeRendering` 全链贯通，色带、阈值、不透明度、Slice/ContourValue 模式均有像素级响应。

## 2. 身份与确定性

- `grid_sha256 = 54c313c9328f8c06e079efacf8099a4b07446e284121369a10b846c4b71bb69f`（与任务书钉死值一致）
- `export_id = 35348bb3-be03-4862-b764-ee165ae0c7dc-54c313c9328f8c06-voxelgrid-netcdf-v1`
- `netcdf_sha256 = 278db7e67908fc74ea720b02048c0d61fabb32d92c8f0b23c7480141549a1bad`（6516 B；API 下载复算一致；重复导出字节确定）
- SDK：本地 12i(2026) 构建，自报 `iClient3D 12.1.0 SVN 50939`；`SuperMap3D.js` SHA-256 `d69dadab01fc452a79f1fa88a46aced3cf29885df7bf4febbd6f24ce5b578120`（与源包逐字节一致，整树 diff 干净）

## 3. NetCDF 契约（读回实测，见 netcdf-inspection.json）

- classic/v3；dims `x=y=z=11`；`rho(x,y,z)` Float32（XDR `>f4`）；坐标变量 x/y/z Float32 且严格递增
- `_FillValue/missing_value = -9999.0f`（Float32 类型）；本成果 nodata_count=0，有效 1,331 个，读回值域 `[6.284669876, 105.356400]`（源 Float64 `[6.284669897, 105.3564]`，Float32 容差内）
- 轴顺序 `values[i,j,k] ↔ x[i],y[j],z[k]`，C-order 原样写入；非对称夹具（X+1/Y+10/Z+100 步进）证明无转置无翻转
- 包围盒经 `wgs84_display_anchor_v1`（锚点 120,30,0）：`[119.99937815, 29.99801538, 120.00062185, 30.00198462]` × z `[-833.0047143, -19.5999]`，与任务书钉死值一致

## 4. 后端

- `src/geomodeling/platform/supermap_voxel_netcdf.py`（复用 `supermap_volume` 的物化/ID 校验/显示锚点转换；独立格式版本与 `supermap-voxel-netcdf/` 目录；不写时间戳保证字节确定）
- API：`POST/GET /api/results/{id}/supermap-voxel-netcdf-export`、`GET /api/supermap-voxel-netcdf-exports/{eid}/manifest`（application/json）、`GET .../volume.nc`（application/x-netcdf）；`export_id` 白名单校验，路径穿越 404；不暴露本机路径
- 单测 `tests/test_supermap_voxel_netcdf.py`：12 passed（结构/dtype/容差/fill/单调/包围盒/方向/确定性/幂等/2D 拒绝/不规则轴/形状不符/全 NoData/非法 ID/checksums）

## 5. 浏览器像素验收（web/e2e/supermap-voxel-netcdf.spec.ts，1 passed / 53s）

环境：HeadlessChrome 149，RTX 4060 Laptop（ANGLE D3D11），WebGL2，`environment.json` 有全量字段。

| 判据（§9.3） | 实测 |
|---|---|
| NetCDF 身份一致 | result_id + grid_sha256 页面侧断言通过 |
| 维度/dtype/NoData | 11³ Float32 rho(x,y,z)，inspection 复核 |
| 真实 VoxelGridLayer3D 图层 | `layer.type=VoxelGridLayer3D` |
| 初始 VolumeRendering | ✓ |
| 非背景像素（面板掩码外） | 66,428 |
| 噪声基线 | 静止连拍 0 像素差；阈值取 max(200, 噪声×3+50) |
| 阈值变化 | minFiltration→55%：61,633 像素差 |
| 不透明度变化 | opacityTransferFunction→0.12：61,622 像素差 |
| Slice 切换 | 61,538 像素差 |
| ContourValue 切换 | 42,096 像素差 |
| 页面异常/失败请求 | 0（pageerror/rejection/4xx/5xx 均无） |
| 降级冒充 | 无（失败即 fail，无点云/自研渲染兜底） |

五张截图：`01-volume-default.png` … `05-contour.png`。

## 6. 本构建包实测 API 事实（阶段 A 探针沉淀，详见 phaseA-findings.md）

1. `startRender` 前须等图层 `_frameState` 就绪（首帧后），否则抛 TypeError；
2. `layerBounds` 赋裸角度 `new SuperMap3D.Rectangle(...)`（构建包内部再做 fromDegrees）；
3. 相机须 `lookAt` 体数据中心（`setView` 不指向目标）；
4. **`opaqueRate` 属性不进着色器 uniform（no-op）**，不透明度走 `opacityTransferFunction`；
5. 色带分量 0–1 浮点；
6. `minFiltration/maxFiltration` 经 uniform 闭包实时生效。

## 7. 回归门

- 后端 `pytest -q`：1151 passed / 29 skipped（含新增 12+1，无缩减）
- 前端 vitest 110 passed；vue-tsc type-check 通过；vite build 通过
- Playwright 全量 5 passed（4 mock + 本规格 live）；`git diff --check` 干净

## 8. 非声明边界

- 本 POC 只证明 11³ 小网格的浏览器原生体素渲染可行；**不证明**大数据性能、真实地理配准（显示锚点 `display_anchor_only`）、iServer 发布、S3M 生产部署；
- 不经过/不评价既有 `/volume-demo`（Three.js 光线步进）与 S3M 路线；两路线均保持原状；
- WebGPU（contextType 3）未测，属后续第二组兼容性实验；
- POC 页面不进导航/首页，不产生正式成果登记。

## 9. 复现

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_supermap_voxel_netcdf.py -q
# 平台运行中（127.0.0.1:8000）：
cd web; npx playwright test e2e\supermap-voxel-netcdf.spec.ts
# 页面：http://127.0.0.1:8000/supermap-voxel-netcdf/index.html?result_id=35348bb3-be03-4862-b764-ee165ae0c7dc&clean=1
```

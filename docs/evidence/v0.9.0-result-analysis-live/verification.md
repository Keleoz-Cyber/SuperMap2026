# v0.9.0 成果级分析真实 SDK 集成验证

验证日期：2026-08-11。此目录记录 Task 11 集成负责人在隔离运行时中对后端、前端与 SuperMap3D 的真实连通验证，不替代前后端单元测试，也不代表已发布。

## 验证链

1. `python -m geomodeling.preset_cli seed-resistivity` 在独立 `GEOMODELING_DATA_DIR` 登记官方电阻率普通克里金成果；
2. 浏览器进入真实 `/results/{result_id}`，显式创建候选成果 NetCDF RenderAsset；
3. SuperMap3D 12.1 `VoxelGridLayer3D` 读取真实 `volume.nc`，回报协议 `gmp-supermap-volume/v2`、成果身份与网格哈希；
4. 规则研判、完整网格组成、八个高值连通区、当前切片、模型证据与三维标注保持同一成果身份；
5. 组件 A 触发三维聚焦，四相机预设和 Volume/Slice/Contour 互斥切换通过；切片统计明确沿用完整网格 p25/p75 阈值；
6. 未设置 `DEEPSEEK_API_KEY` 时，AI 端点创建 `unavailable / DEEPSEEK_NOT_CONFIGURED` 记录，规则研判仍可恢复使用；
7. 1920×1080 视口页面级 X/Y 溢出均不超过 1 px，长内容只在右栏或证据带内部滚动。

## 真实结果

- 截图：[result-analysis-live-1920x1080.png](result-analysis-live-1920x1080.png)
- 机器可读记录：[result-analysis-live.json](result-analysis-live.json)
- 网格 SHA-256：`079c410f071b86980fe56f09f70cfb1cdfb489c48e525cb74e416a4463721534`
- 有效网格：6,762；连通区：8；标注：8/8 可见；焦点：`component-1`
- 图层：`VoxelGridLayer3D`；坐标语义：局部线性 + `display_anchor_only`
- 浏览器页面溢出：document/body 的 X=0，Y=1 px
- 网络失败：0；iframe `diag.errors`：0
- 两个初始 404 是合同内探测：NetCDF 资产尚未创建、AI 最新记录尚不存在；随后分别经显式 POST 创建资产和未配置 AI 记录，不属于静默失败。

## 回归结果

- 后端：`python -m pytest tests -q -m "not local_data"` → `1895 passed, 32 deselected`
- 前端：`npm --prefix web run test:unit` → `501 passed`
- 类型与构建：`npm --prefix web run type-check`、`npm --prefix web run build` → 通过
- Mock E2E：`npm --prefix web run test:e2e` → `41 passed`
- 真实成果门：`npm --prefix web run test:e2e:live -- result-analysis-live.spec.ts` → `1 passed`

## 未宣称

- 没有配置真实 DeepSeek 密钥，因此不宣称本机完成外部模型成功调用；成功/错误响应由假服务单测覆盖，真实浏览器只验证未配置降级。
- 真实 GPU 已验证“组件列表→三维聚焦”；三维标注的真实鼠标 pick 命中率仍缺独立 GPU 门，当前由协议单测与 Mock E2E 覆盖。
- `display_anchor_only` 不是地理配准，八个连通区是规则网格支持量，不是已确认地质体积或风险区。
- PR 仍应保持 OPEN；本验证不授权合并、标签或 Release。

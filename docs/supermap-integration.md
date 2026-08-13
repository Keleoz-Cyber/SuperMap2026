# SuperMap 与 iServer 集成说明

## 1. 文档和版本

- iServer 帮助：<https://help.supermap.com/iServer/1201/zh/>
- iDesktopX 帮助：<https://help.supermap.com/iDesktopX/zh/>
- SuperMap3D/iClient3D API 以本机实际 SDK 包和官方文档为准。

网址中的 `1201` 是官方文档路径，不应仅凭路径判断本机产品过期。演示前必须同时核对安装构建号、前端 SDK、许可证和服务元数据。

## 2. 在平台中的职责

SuperMap 负责：

- iDesktopX 中的人工复核和必要数据准备；
- iServer 数据、地图、三维和瓦片服务；
- 浏览器中的 SuperMap3D 原生体渲染；
- Volume、Contour 和正交切片表达。

平台自身负责：

- 数据合同、质量门禁和来源哈希；
- 插值/预测、空间验证和候选比较；
- 规则网格物化、NetCDF 生成和 RenderAsset 登记；
- 切片统计、规则/AI 研判、导出与证据链。

因此 iServer 离线不应破坏通用建模，但所有服务和发布状态必须如实显示为不可用或 `manual_required`。

## 3. 当前正式渲染路径

```text
CandidateResult 规则网格
  → NetCDF RenderAsset
  → 浏览器隔离 iframe
  → SuperMap3D VoxelGridLayer3D
  → Volume / Contour / X/Y/Z Slice
```

NetCDF 资产必须登记：成果 ID、数据版本、网格哈希、维度、坐标、变量、单位、值域、NoData 和显示锚点。页面读取资产不会隐式创建资产；物化必须是显式动作。

三个案例都使用局部工程坐标。`display_anchor_only` 只用于把局部模型放到浏览器可见位置，不代表真实 EPSG 配准。

## 4. iframe 协议

协议名：`gmp-supermap-volume/v2`。

- 父页面发送完整渲染状态，不发送容易乱序的零散命令。
- `revision` 必须单调递增；iframe 忽略旧状态。
- Slice 模式必须携带权威切片 API 返回的 axis、index、coordinate 和 relativePosition。
- iframe 通过 `FRAME_READY` 报告版本与能力。
- 错误必须携带阶段和诊断；页面不得把空白、点云或线框标为原生体渲染成功。

单轴切片通过把两个非活动轴移到负坐标隐藏，这是 SuperMap3D 12.1 本机实测行为，证据见[单轴切片探针](evidence/v0.7.0-single-axis-probe/)。它不是官方公开 API 承诺，升级 SDK 后必须重跑真实 GPU 门。

## 5. S3M 历史兼容

早期电阻率闭环使用 iDesktopX“体元栅格生成瓦片”产生 S3M 2.0 `PointCloudFile`。当前代码只保留严格兼容读取和证据探测：

- 只接受固定类型、版本、头部和压缩合同；
- 远程瓦片清单和 digest 固定；
- 值域、数量和包围盒与登记合同一致；
- 任一异常返回 503，不返回可疑格点。

它不是当前原生体渲染主路径，也不能宣传为 GPU 连续体渲染。

## 6. iServer 配置

凭据只通过环境变量提供，例如：

```powershell
$env:GEOMODELING_ISERVER_BASE_URL = 'http://127.0.0.1:8090/iserver'
$env:GEOMODELING_ISERVER_USERNAME = '<local-admin>'
$env:GEOMODELING_ISERVER_PASSWORD = '<local-secret>'
```

不要把真实用户名、密码、许可证或安装绝对路径提交到仓库。若本机存在多个 iServer/Tomcat，启动前清理可能污染运行时的全局 `CATALINA_HOME`、`CATALINA_BASE` 等变量，并确认 8090 实际进程身份。

## 7. 发布和回执

发布证据分层：

1. 配置已登记；
2. 工作空间或资产文件存在；
3. iServer 服务可访问；
4. 服务元数据与登记一致；
5. 浏览器真正加载目标图层/体元；
6. 成功回执由服务器接收并通过身份校验。

浏览器回执按 render kind 严格验证：

- `iserver_scene`：精确服务 URL、场景名、实际图层数一致且大于 0；
- `s3m_voxel_cache`：精确服务 URL、缓存数据名、正式成果 ID 和有效单元数一致。

只完成 `scene.open()` Promise、只画包围盒或只返回 fallback 点，不构成正式渲染证据。

## 8. 刷新语义

- iServer 可能在服务启动时读取 SCP 元数据；重新生成缓存后应重启或重新发布服务。
- FastAPI 中的兼容缓存可通过带 `refresh=true` 的接口刷新，或重启后端。
- 浏览器刷新页面重新拉取资产和状态。
- NetCDF 资产按成果哈希登记；新成果应创建新资产，而不是静默覆盖旧文件。

## 9. 演示前检查

```powershell
python -m geomodeling.cli demo-check
python -m geomodeling.cli verify-supermap -o outputs\verify
npm --prefix web run build
```

随后人工确认：

- 8000 和 8090 的监听进程身份；
- iServer 许可证与目标服务；
- 首页三案例可切换；
- 体渲染不是点云或线框；
- Volume/Contour/X/Y/Z Slice 有真实像素变化；
- iServer 停止时页面如实降级，通用建模仍可使用。

真实产品证据见[v0.9.0 浏览器验收](evidence/v0.9.0/)和[成果级分析验收](evidence/v0.9.0-result-analysis-live/)。

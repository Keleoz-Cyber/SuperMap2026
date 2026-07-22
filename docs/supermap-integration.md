# SuperMap iServer 与浏览器集成说明

> 更新时间：2026-07-22。本文是开发阶段阅读SuperMap文档、探测本机环境和实现发布闭环的入口，不代表当前已经发布成功。

## 1. 职责边界

- **Python/FastAPI**：文件接入、契约校验、插值、调参、空间验证、任务状态和证据登记；
- **SuperMap iServer**：发布工作空间、数据、地图和三维缓存服务；
- **SuperMap iClient3D for Cesium**：浏览器三维场景、体渲染、采样、切片/裁剪和交互；
- **iDesktopX**：人工制作、检查或转换SuperMap成果，不作为浏览器系统的自动化后端。

浏览器不得持有iServer管理员密码或长期管理Token。管理和发布请求由FastAPI后端发起；浏览器只访问允许公开或经过短期授权的业务服务。

## 2. 本机运行时事实

```text
SUPERMAP_ISERVER_HOME=
D:\supermap\supermap-iserver-2026-windows-x64-deploy\supermap-iserver-2026-windows-x64-deploy
```

- 构建标识：`iServer-Version: 12.1.0.0-260626-9297`；
- 启动/停止脚本：`bin/startup.bat`、`bin/shutdown.bat`；
- 默认服务入口：`http://localhost:8090/iserver/`；
- **2026-07-22 v0.3 实测更新**：
  - 8090 已启动监听；首次初始化完成（管理员已创建，凭据本机保管不入库）；试用许可有效至 2026-09-20（`licenseStatus=true`）；
  - 环境坑：全局 `CATALINA_BASE/CATALINA_HOME/CATALINA_TMPDIR` 指向其他 Tomcat 会让 iServer 以错误 `catalina.base` 启动（8090 不监听、无日志），须先清理再启动；
  - `WorkSpace.smwu`（电阻率）已发布 `data-WorkSpace`、`map-WorkSpace`、`3D-WorkSpace` 三服务；`Project\电阻率.smwu` 实为瓦斯数据源（gas2d/gas3d），名称误导，误发布的服务已删除；
  - `POST /iserver/manager/workspaces.rjson` 程序化快速发布在本机 500（`String cannot be cast to PublishServiceParameter`），管理 UI 发布正常；列为未解决问题（管理 UI 走加密 tunnel 通道）；
  - 数据服务 VOLUME 数据集元数据可查（type/尺寸/值域/平面坐标），但单元值经 `features` 读取返回 500；三维场景中体元图层以 `ImageFileLayer`（二维影像瓦片）发布，**不等于** S3M 体渲染，浏览器真体渲染须先在 iDesktopX 生成三维缓存（.scp）再发布；
  - iClient3D SDK 已获取：官方 npm 包 `@supermap/iclient3d-vue-for-webgl@1.2.2` 内嵌 `public/Cesium`（Cesium 1.67 + SuperMap 插件，44MB，经 `scripts/fetch_iclient3d.py` 安装，不入库）；实测可 `scene.open` 本机三维服务；
  - 本机`iClient`目录仅含占位页，页面明确提示产品包不含iClient，不能当作可直接引用的SDK；
  - 本机 iDesktopX 2026 位于 `D:\supermap\supermap-idesktopx-2026-windows-x64-bin`（人工操作用途）。

项目代码不得硬编码上述路径。使用环境变量或不入库的本地配置；密钥、管理员凭据和Token不得提交Git。

## 3. 官方文档最小阅读顺序

### 必读：iServer REST与发布

1. [iServer官方帮助](https://help.supermap.com/iServer/1201/zh/)
2. [REST API概述](https://help.supermap.com/iServer/1201/zh/mergedProjects/SuperMapiServerRESTAPI/Overview.htm)
3. [业务REST OpenAPI](https://help.supermap.com/iServer/1201/zh/mergedProjects/SuperMapiServerRESTAPI/iServerOpenAPI.htm)
4. [管理REST OpenAPI](https://help.supermap.com/iServer/1201/zh/mergedProjects/SuperMapiServerRESTAPI/iServerOpenAPI_manager.htm)
5. [通过REST API快速发布工作空间](https://help.supermap.com/iServer/1201/zh/Server_Service_Management/StartaServicebyREST_API.htm)
6. [服务列表与元信息](https://help.supermap.com/iServer/1201/zh/Service_introduce/serviceslist.htm)
7. [Token获取与访问控制](https://help.supermap.com/iServer/1201/zh/Subject_introduce/Security/config_role/token/AcquiringSuperMap_Token.htm)

REST快速发布文档说明`workspaces` POST当前面向UGC工作空间；三维缓存发布是另一条能力链，不能假设一次发布工作空间就自动获得可用体渲染场景。

### 必读：三维Web展示

1. [发布三维切片缓存](https://help.supermap.com/iServer/1201/zh/Server_Service_Management/quickPublish/Publish_3D_cache.htm)
2. [iClient3D for Cesium](https://help.supermap.com/iServer/1201/zh/webgl/web/index.html)
3. [iClient3D API](https://help.supermap.com/iServer/1201/zh/webgl/web/apis/3dwebgl.html)
4. [iClient3D示例中心](https://help.supermap.com/iServer/1201/zh/webgl/examples/webgl/examples.html)

示例中心优先阅读：

- `S3M_Volume`：体数据渲染、颜色表、可见值范围；
- `nearestFilterMode`：体数据临近采样；
- `planScene`：平面场景；
- `geologicBodyOperation`：地质体剖切；
- `geologicBodyClip`：地质体裁剪。

开发前先验证官方SDK的获取和许可方式，再决定npm、静态资源或其他集成方式；不要根据本机占位目录猜测依赖名。

## 4. 首个纵向闭环

首个闭环使用已有电阻率成果，不等待瓦斯体元问题解决：

1. 启动iServer并登记进程、版本、许可和基础URL；
2. 调用`/iserver/services.rjson`验证服务列表；
3. 通过后端验证鉴权和工作空间/成果发布；
4. 保存服务类型、服务URL、请求时间、HTTP状态和响应摘要；
5. FastAPI提供案例、成果、发布状态和健康检查接口；
6. 浏览器加载至少一个SuperMap服务，展示参数、指标、证据等级和失败提示；
7. iServer不可用时，建模结果仍保留，前端显示可恢复的“发布失败”，不得把建模状态改成失败。

## 5. 发布与加载证据

每个成果分别登记：

```text
model_succeeded
artifact_exported
iserver_published
service_metadata_verified
browser_loaded
manual_visual_checked
```

后一步失败不能覆盖前一步证据。浏览器“发出请求”不等于图层加载成功；至少检查HTTP状态、服务元信息、场景/图层对象存在和一次可见渲染或自动化截图。

## 6. 当前已知风险

- ~~本机iServer尚未启动验证，许可证和可用模块未知~~（2026-07-22 已启动验证，试用许可至 2026-09-20）；
- ~~iClient3D SDK未随本机包提供~~（已通过官方 npm 包获取并验证 scene.open，见第 2 节）；
- 电阻率垂直切片未正式验证，原生等值面为空；
- 瓦斯体元在iDesktopX加载阶段触发`setSliceCoordinate`原生崩溃；
- **iServer 发布的三维服务中，UDBX 体元以 ImageFileLayer（二维影像）提供；「体元栅格生成缓存」（S3M 2.0）产出点云瓦片（PointCloudFile 为正常形态，值域在 `wDescript`），但 SCP 把平面米制坐标写成球面，且旧版 iClient3D（1.67 系）无法遍历其瓦片树（根瓦片可下载、子瓦片不请求、图层无包围盒）；v0.3 落地路径为 FastAPI 经 iServer REST 取瓦片自研解析 + 浏览器自定义渲染**（见 v0.3 运行说明 3.4/4.1）；
- `workspaces` REST 程序化发布在本机构建上 500，发布目前依赖管理 UI 人工步骤；
- 局部工程坐标案例需要平面场景和明确的单位/原点说明，不能伪装成全球地理坐标；
- 试用许可 2026-09-20 到期，答辩环境需在此之前复核。

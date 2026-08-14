# portable 免安装包模板源

本目录是发行包启动脚本与声明文件的**模板源**，由 `scripts/build_portable.py` 在打包时复制进发行 ZIP；本目录本身不是可运行的平台。

| 文件 | 作用 |
|---|---|
| `启动平台.cmd` | 最终用户双击启动：查找可用端口、启动内嵌服务、健康等待后打开浏览器。 |
| `停止平台.cmd` | 停止平台进程。 |
| `THIRD_PARTY_NOTICES.txt` | 第三方组件声明（Python 运行时、SuperMap3D SDK、前端依赖等）。 |

## 说明

- 发行包内的 `使用说明.txt`、`portable-manifest.json`（逐文件 SHA-256 清单）与 `GeoModelingPlatform.exe`（支持 `start`/`doctor`）在构建时生成，不在本目录维护。
- 修改启动/停止脚本后必须重新执行便携包构建并跑冒烟测试（中文/空格路径移动验收）。
- 用户数据只写入发行包内独立 `runtime/` 目录（首次启动从只读模板复制）。

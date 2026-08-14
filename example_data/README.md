# example_data 内置案例源

三个官方案例的内置数据源，**字节级冻结**：文件 SHA-256、行数、表头、数值有限性与 XYZ 唯一性由 `config/presets/*.json` 声明并由 `tests/test_example_data_contract.py` 锁定；任一不符即 `PRESET_SOURCE_INVALID` 拒绝入库（fail-closed）。

| 文件 | 案例 | 内容 |
|---|---|---|
| `地下电阻率节点_标准化.csv` | 电阻率 | `X,Y,Z,RHO`（Ω·m），17,549 行唯一 XYZ |
| `微震局部三维点_3Sigma_去重均值_1911.csv` | 微震波速 | 22 个 DAT 经「局部 XYZ -> 3σ -> 黄金门禁 -> 去重均值」派生链的 1,911 建模节点产物；列：`SAMPLE_IDS,POINT_ID,LINE_ID,X_LOCAL_M,Y_LOCAL_M,DEPTH_M,Z_LOCAL_M,VX_KM_S,N_MERGED` |
| `瓦斯含量_合格样品.csv` | 瓦斯含量 | `X,Y,Z,CH4_content`（ml/g），58 条合格样品 |

## 使用规则

- 只读：本目录文件一经冻结不可修改；需要变更数据时走新案例与新文件名，并同步预置合同。
- 入库：由 `python -m geomodeling.preset_cli seed-resistivity|seed-microseismic|seed-gas --data-dir <目录>` 幂等 seed 为只读案例（含官方基线校验）。
- 案例指标、边界与基线数字的唯一权威说明见 [docs/product-guide.md](../docs/product-guide.md) 第 12 节。
- 私有论文原件、未授权数据与运行数据库不进入本目录。

# Findings & Decisions

## Requirements
- Build a first-version underground resistivity closed-loop MVP for Windows and SuperMap iDesktopX 2026 workflow.
- Register and validate standardized `X,Y,Z,RHO` data.
- Manage training set, validation set, model configuration, and task status.
- Import existing ordinary Kriging and IDW validation results.
- Recompute and display quality metrics on the unified common valid points.
- Manage SuperMap voxel datasets, slices, threshold anomalies, and failed results.
- Output traceable model metadata, issue lists, and result inventories.
- Reserve clear interfaces for microseismic, coalbed methane, and DSI-like modules without implementing unverified science in MVP.
- Keep original materials read-only and store all derived work inside `GeoModelingPlatform`.

## Research Findings
- Master prompt confirms standardized resistivity source path: `../超图杯资料/标准化数据/地下电阻率节点_标准化.csv`.
- Confirmed baseline facts: 17,549 total records; 15,827 training rows in 264 spatial columns; 1,722 validation rows in 29 spatial columns; zero train/validation spatial-column overlap.
- Five-model common valid validation points: 1,481; common NoData: 241; common coverage about 86.0%.
- Prediction `-9999` is NoData and must be converted to missing/null with `is_nodata`, excluded from error statistics, coloring, and re-interpolation.
- Default display candidate: `Kriging 20m/40点`, MAE 3.222594, RMSE 5.841043.
- Formal comparison candidate: `IDW 20m/25点`, MAE 3.475606, RMSE 5.787635.
- Ordinary Kriging is not better than IDW on every metric; `Kriging 10m/40点` is not a formal candidate.
- Required metrics: MAE, RMSE, R², median absolute error, mean/median relative error, log10 RMSE, Bias, P90 absolute error, and coverage on the same common valid subset.
- SuperMap formal candidate voxel dataset: `RHO_KRIG_FINAL_20M_40`, ordinary Kriging, 20 m horizontal resolution, 40 neighbors, voxel dimensions 7 × 23 × 42, display range about 1.418283—133.146194.
- `RHO >= 77` is an engineering demo threshold, not a proven geological hazard threshold.
- Native isosurface extraction with threshold 77 and range 77—133.146 failed and left empty datasets `RHO_ISO_77_K40`, `RHO_ISO_HIGH_P95_K40`; these must not be registered as successful results.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Preserve original materials as read-only | Prevents damage to evidence and keeps derived work reproducible inside the project |
| Record architecture choice in `docs/decisions/` before implementation | Master prompt requires evidence-based selection rather than framework habit |
| Use Python 3.12 with pandas/numpy/pydantic/Typer/Rich/PyYAML/pytest | Available locally and best fit for CSV validation, metrics, CLI reports, and tests |
| Use file-backed JSON registry plus Markdown/HTML reports for MVP UI | Provides a clear analysis entry without overbuilding web/desktop UI before the data contract is stable |
| Prefer formal succeeded openable non-empty SuperMap records when multiple records share a `model_id` | Failed isosurface shells and formal voxel datasets can share a model; selection must be integrity-aware |
| Use explicit SuperMap evidence levels | Configuration registration, file existence checks, dataset API checks, and manual iDesktopX evidence must not be conflated |
| Keep `dataset_verified=false` until a supported SuperMap API adapter succeeds | Current `dataset_api=none`; guessing UDBX internals would violate evidence requirements |
| Split portable fixtures from local real-data regression | GitHub CI cannot assume adjacent private research data, while local regression must still protect the real baseline |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Duplicate `model_id` SuperMap records caused failed isosurface metadata to override formal voxel metadata | Added `select_supermap_result_for_model()` to prefer formal succeeded openable non-empty results |
| Missing report import caused end-to-end report export failure | Added the missing import and reran the failing test |
| Selection metadata file was parsed as a model task | Skipped underscore-prefixed registry metadata files and added a regression test |

## Resources
- `KIMI3_MASTER_PROMPT.md`
- `README.md`
- `开发交接包/00_项目总览/README.md`
- `开发交接包/00_项目总览/开发交接包设计说明.md`
- `开发交接包/01_需求与范围/MVP功能清单.md`
- `开发交接包/03_数据规范/数据契约.md`
- `开发交接包/05_SuperMap验证/已知问题.md`
- `../超图杯资料/项目说明.md`
- `../超图杯资料/三类数据开发方向与优先级.md`
- `../超图杯资料/DSI插值转化可行性方案.md`
- `../超图杯资料/标准化数据/插值验证方案.md`
- `../超图杯资料/标准化数据/插值精度对比_总体指标.csv`
- `../超图杯资料/标准化数据/插值精度对比_分析摘要.json`

## Additional Requirements From Handover Documents
- Repository currently contains only handover docs, planning files, `.git/`, `.gitattributes`, `.gitignore`, `KIMI3_MASTER_PROMPT.md`, and `README.md`; code engineering has not been initialized.
- First code batch must establish project structure, configuration model, logging/error model, CSV contract validation, file hash/record/range registration, model task and SuperMap dataset-name management, existing prediction-result import, unified quality metrics, and result inventory distinguishing success/failure/preview.
- DATA-01..DATA-06 require dataset registration with path, SHA-256, type, version, creation time, source note, duplicate-hash prompt, strict `X,Y,Z,RHO` field/type/range/null checks, expected row counts, statistics, and data-layer separation.
- MODEL-01..MODEL-06 require unique `model_id`, config snapshots, `KRIGING_ORDINARY`/`IDW` only, key parameters, SuperMap result registration, fixed task states, and default/comparison model rationale.
- QA-01..QA-06 require 1,722 validation rows, zero XY mismatch, `-9999` NoData exclusion, unified metrics on common valid points, fair model comparison, spatial-column/depth-band summaries, and non-overclaiming selection conclusions.
- VIEW-01..VIEW-06 require locating `RHO_KRIG_FINAL_20M_40`, horizontal slice config, vertical slice only after verification, configurable threshold anomaly view, isosurface status shown as not verified, and RHO unit marked as pending source confirmation.
- AUDIT-01..AUDIT-05 require operation logs, data-quality issue records, machine-readable JSON plus human-readable Markdown exports, result inventory by formal/validation/preview/failed-empty, and anti-false-success checks.
- Data contract defines layers L0 raw_observation, L1 standardized_observation, L2 train_validation_split, L3 model_result, L4 visual_derivative; common metadata includes `dataset_id`, `dataset_type`, `version`, `source_path`, `sha256`, `row_count`, `created_at`, `created_by`, `source_reference`, `quality_status`, `notes`.
- CSV contract: UTF-8, comma delimiter, header `X,Y,Z,RHO`, finite numeric fields, `RHO > 0`, no `-9999` in observations, duplicate `(X,Y,Z)` check, local engineering CRS, horizontal/vertical unit meters, `z_positive=up`, and no extra negation of Z on import.
- Prediction contract: SuperMap export `Attribute=-9999` maps to null plus `is_nodata=true`; metrics only on common valid points; current common valid = 1,481, common NoData = 241, coverage = 0.8600464576074333.
- Model metadata JSON must include property, unit, method, input dataset/hash, CRS, axis, grid, parameters, SuperMap version/datasource/dataset, status, and generated time; sample time/hash must not be copied into real metadata.
- SuperMap known issues: RHO may import as text; use real field names not aliases; 241 common NoData are concentrated in four fully uncovered spatial columns plus one single-point column; native section display can be blank; native isosurface extraction failed twice and created empty datasets; X direction has only 7 voxel rows; failed empty datasets must not enter formal result lists.

## Data File Structure Findings
- `地下电阻率节点_标准化.csv`, `地下电阻率节点_训练集90.csv`, and `地下电阻率节点_验证集10.csv` all use header `X,Y,Z,RHO` and finite numeric-looking rows.
- Five prediction exports use SuperMap-style header `SmUserID,Attribute,Geometry`; early rows show `Attribute=-9999.0` and WKT-like `POINT (x y)` geometry without Z.
- Prediction exports have 1,722 data rows and can be aligned to the validation set by row order; XY mismatch must still be verified as zero.
- Prediction `Attribute` is the model prediction field; `-9999` must be converted to null plus `is_nodata=true` before metric computation.

## Environment Findings
- Python 3.12.3 is available; first resolved executable is `D:\Anaconda\python.exe`.
- Node.js v24.13.1 and npm 11.13.0 are available.
- Git repository exists on `main...origin/main`; current untracked files are the three planning files.
- SuperMap iDesktopX executable exists at the documented path `D:\supermap\supermap-idesktopx-2026-windows-x64-bin\supermap-idesktopx-2026-windows-x64-bin\SuperMap iDesktopX.exe`.
- Python packages already available include pandas, numpy, scipy, pytest, pydantic, typer, rich, yaml, and openpyxl.
- Required standardized data, train/validation splits, five prediction exports, overall metrics CSV, and analysis summary JSON all exist under `../超图杯资料/标准化数据`.

## Architecture-Relevant Facts
- MVP should prioritize stable configuration, file exchange, data validation, result registration, and tests over UI automation of iDesktopX controls.
- SuperMap integration should begin as a boundary/adapter: register UDBX path, datasource alias, dataset names, parameters, status, and error evidence; deeper iObjects/GPA/Python integration must be optional and replaceable.
- DSI-like and GOCAD are later external backends; MVP must not rename IDW or ordinary Kriging as DSI and must not re-interpolate DSI outputs while claiming original results.
- Microseismic and coalbed methane modules require future contracts/interfaces only; no trusted 3D fusion for gas until CRS, axis order, collar elevation, and depth datum are confirmed.

## Implementation Findings
- The repository now has a runnable Python MVP under `src/geomodeling/` with CLI commands for validation, prediction import, metric computation, SuperMap registration, report export, and end-to-end smoke execution.
- Real-data tests confirm standardized/training/validation row counts, zero train/validation spatial-column overlap, five prediction files with 1,722 rows each, zero XY mismatch, 1,481 common valid points, and 241 common NoData points.
- Recomputed metrics match `插值精度对比_总体指标.csv` within configured tolerance; `Kriging 20m/40点` has the lowest MAE while `IDW 20m/25点` has the lowest RMSE.
- SuperMap registration separates one formal succeeded voxel dataset from two failed/empty isosurface datasets; duplicate `model_id` records must be resolved by preferring formal succeeded openable non-empty results.
- Actual adjacent UDBX path found at `../Project/expore1.udbx` and written to `config/default.yaml` as a configurable path.

## Microseismic v0.2a Requirements
- Current branch must start from clean `main` at `b160405ac10b3eb0b5973481a967a17d9bbf7084` / `v0.1.0`; verified before branch creation.
- New branch: `feat/microseismic-data-audit-v0.2a`; PR required but must remain unmerged; no new tag or Release.
- Scope is data audit and standardization foundation only: source manifest, DAT parsing, survey lines/points/velocity samples, raw count consistency, 1D cumulative distance, conflicts/issues, reports, CLI, tests, audit logs.
- Formal lines: L1=W1—W9 (9), L2=W12—W20 (9), L3=W24—W27 (4); W28 is conflict/source-only and excluded from formal L3, cumulative distance, cleaning set, and later models.
- Measured DAT facts: 22 ASCII whitespace-separated DAT files, 66,880 bytes total, header `WL/2(km)  Vx`; each file ends with one NUL pseudo-line (22 total); generic first-pass rows are 2,028 = 2,006 real source records + 22 NUL pseudo-lines.
- Record-count layers: source records L1=823/L2=819/L3=364 (total 2,006); W8.dat line 2 holds MSVC token `1.#QNAN0`, so finite valid values are L1=822/L2=819/L3=364 (total 2,005); invalid numeric is exactly 1 and stays traceable in the standard table.
- Paper table `823/818/364=2,005` conflicts with file facts and is registered as `LINE_COUNT_CONFLICT`; records are never moved between lines to match the paper.
- DAT source field `WL/2(km)` must be preserved verbatim; depth/Z derivation remains unconfirmed and empty unless direct evidence exists.
- Paper cleaning statements conflict: 80/2,005≈3.99% vs 3.59%, and linear interpolation vs nearest-5-point IDW; v0.2a must not choose a formal cleaning algorithm.
- No trusted absolute 3D coordinates; do not generate claimed-real X/Y/Z. v0.2a may compute one-dimensional along-line `s_m` only with point order, interval source, and confidence state.
- Git may contain code, config, contracts, tests, tiny fixtures, and quality summaries without original numeric research data; it must not contain raw DAT/PDF/XLSX/images, complete derived observation tables, outputs/artifacts/logs, secrets, or unnecessary absolute paths.
- Interval evidence from `点间距.xlsx` (GBK workbook): L1 W1—W9 = 150/100/100/50/50/150/250/300 m; L2 W12—W20 = 275/275/250/195/110/600/300/300 m; L3 W24—W27 = 800/320/335 m; W28 350 m is conflict-only.
- v0.2a implemented: `src/geomodeling/microseismic/` (config, parser, inventory, geometry, contracts, issues, reports, service, CLI sub-app) plus `config/microseismic.yaml`; CLI group `geomodeling microseismic inventory/parse/validate/export-reports/run-audit`; full local audit passes with 15 contract checks and 11 registered issues.

## Visual/Browser Findings
- None yet.

---
*Update this file after every 2 view/browser/search operations*

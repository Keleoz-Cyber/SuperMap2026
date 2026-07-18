# MVP Progress Evidence

## 2026-07-18

### Implemented

- Python package scaffold under `src/geomodeling/` with Typer CLI.
- Configuration-driven paths, expected counts, model definitions, SuperMap result registrations, NoData value, metric tolerance, view configurations, and output directories in `config/default.yaml`.
- Dataset registration and validation reports for standardized, training, and validation resistivity CSVs.
- SHA-256 registration, required field checks, finite numeric checks, positive RHO checks, duplicate XYZ statistics, ranges, null counts, and train/validation spatial-column overlap check.
- SuperMap prediction export import for five models with `SmUserID,Attribute,Geometry` parsing and row-order alignment to the 1,722-record validation set.
- `-9999` NoData normalization to null/`is_nodata=true` and common-valid metric recomputation.
- Baseline comparison against `插值精度对比_总体指标.csv` with configured tolerance.
- Model task registry with unique `model_id`, config snapshots, method restrictions, status restrictions, idempotent config sync, and default/comparison selection rationale.
- SuperMap evidence levels: `declared`, `file_verified`, `dataset_verified`, and `manual_evidence`; current dataset API is `none`, so dataset-level verification is not claimed.
- `verify-supermap` file-level verification with UDBX existence, file size, mtime, optional SHA-256, machine-readable report, and explicit per-result evidence output.
- View configuration export for full voxel entry, horizontal slice config, demo threshold config, unverified vertical slice, failed isosurface, and external open information.
- Audit JSONL logging for CLI commands with command, operator, UTC time, input hashes, parameters, SuperMap version, status, outputs, and error text.
- Structured issue list export covering RHO unit, local CRS/EPSG, vertical slice, failed isosurface, and SuperMap dataset-level verification boundary.
- Portable CI test layer using `tests/fixtures/` and GitHub Actions; local real-data regression remains marked as `local_data`.

### Verification Evidence

- Baseline before hardening: `python -m pytest -q` was 18 passed; `run-all -o outputs/mvp_baseline_verify` completed with `baseline_passed=True`.
- After hardening: `python -m pytest -q` is 36 passed.
- Portable layer: `python -m pytest -q -m "not local_data"` is 24 passed, 12 deselected.
- Local real-data layer: `python -m pytest -q -m local_data` is 12 passed, 24 deselected.
- `python -m geomodeling.cli run-all -o outputs/hardening_smoke`: completed successfully.
- `python -m geomodeling.cli verify-supermap -o outputs/hardening_smoke`: `udbx_exists=True`, `udbx_file_verified=True`, `dataset_verified=False`.
- SuperMap configured results output: 3 registered configuration results, 1 formal configuration result, 3 file-verified results, 0 dataset-verified results.
- `create-model`, `list-models`, and `select-models` smoke commands completed; selection keeps `Kriging 20m/40点` as default and `IDW 20m/25点` as comparison with `single_overall_winner=False`.

### Current Boundaries

- The MVP does not automate iDesktopX controls.
- SuperMap internal dataset content is not programmatically verified in v0.1.
- Full voxel and horizontal slice support are manual iDesktopX evidence.
- Vertical slices and native isosurface extraction remain unverified/failed as documented in known issues.
- RHO physical unit is still marked as pending source confirmation.
- Coalbed methane and DSI-like modules are interfaces/documentation only.

## 2026-07-18 — Microseismic v0.2a data audit foundation

### Implemented

- `config/microseismic.yaml` and `src/geomodeling/microseismic/` package: config model, DAT parser (ASCII whitespace, trailing NUL pseudo-line detection, MSVC `1.#QNAN0`-class token handling), source inventory with SHA-256, 1D survey geometry, pydantic contracts, 11 standard issues, JSON/Markdown reports, orchestration service, and a `geomodeling microseismic` Typer sub-app (`inventory`, `parse`, `validate`, `export-reports`, `run-audit`).
- Three standard tables: `survey_lines.csv` (3 rows), `survey_points.csv` (23 rows, 22 formal + W28 conflict-only), `velocity_samples.csv` (2,006 rows).
- Reports: `source_manifest.json`, `microseismic_validation.json`, `microseismic_issue_list.json/.md`, `microseismic_data_quality.md`, `microseismic_data_dictionary.md`, `microseismic_audit_summary.md`, plus audit JSONL.
- Portable tests with tmp-generated fixtures and `local_data` real-data regression.

### Verification Evidence

- `python -m pytest -q` → 76 passed; portable layer 54 passed/22 deselected; local layer 22 passed/54 deselected.
- Real audit: 22 DAT (66,880 bytes), 22 NUL terminators, 2,028 first-pass rows = 2,006 source records + 22 NUL pseudo-lines; valid numeric 2,005 (822/819/364); invalid numeric 1 (W8 line 2 `1.#QNAN0`, preserved and traceable).
- 15 contract checks pass, including per-line counts, uniqueness, W28 exclusion, monotonic cumulative distance, no fabricated XY/Z, and unchanged source SHA-256.
- v0.1 resistivity regression unchanged: 17,549/15,827/1,722 rows, overlap 0, five models 1,481 valid/241 NoData/XY mismatch 0, `baseline_passed=True`, `dataset_verified=False`.

### Current Boundaries

- v0.2a provides 1D `cumulative_s_m` only; no X/Y/Z, EPSG, origin, azimuth, or depth derivation is claimed.
- `WL/2(km)` is preserved verbatim with unconfirmed meaning; `derived_depth_m`/`derived_z_m` stay empty.
- Cleaning conflicts (80/2,005≈3.99% vs 3.59%; linear interpolation vs nearest-5-point IDW) are registered; no formal cleaning output.
- Paper per-line counts `823/818/364=2,005` conflict with file facts and remain an open source conflict.

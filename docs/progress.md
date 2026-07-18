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
- Microseismic, coalbed methane, and DSI-like modules are interfaces/documentation only.

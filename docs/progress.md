# MVP Progress Evidence

## 2026-07-18

### Implemented

- Python package scaffold under `src/geomodeling/` with Typer CLI.
- Configuration-driven paths, expected counts, model definitions, SuperMap result registrations, NoData value, metric tolerance, and output directories in `config/default.yaml`.
- Dataset registration and validation reports for standardized, training, and validation resistivity CSVs.
- SHA-256 registration, required field checks, finite numeric checks, positive RHO checks, duplicate XYZ statistics, ranges, null counts, and train/validation spatial-column overlap check.
- SuperMap prediction export import for five models with `SmUserID,Attribute,Geometry` parsing and row-order alignment to the 1,722-record validation set.
- `-9999` NoData normalization to null/`is_nodata=true` and common-valid metric recomputation.
- Baseline comparison against `插值精度对比_总体指标.csv` with configured tolerance.
- SuperMap result registry separating formal succeeded voxel dataset `RHO_KRIG_FINAL_20M_40` from failed/empty isosurface datasets `RHO_ISO_77_K40` and `RHO_ISO_HIGH_P95_K40`.
- Machine-readable JSON and human-readable Markdown exports for metrics, model metadata, and result inventory.

### Verification Evidence

- `pytest -q`: 18 passed.
- `python -m geomodeling.cli run-all -o outputs/mvp_verify`: completed successfully.
- CLI validation output:
  - `rho_standardized_v1`: passed, 17,549 rows.
  - `rho_training_v1`: passed, 15,827 rows.
  - `rho_validation_v1`: passed, 1,722 rows.
  - train/validation spatial-column overlap: 0.
- Prediction import output for all five models: 1,722 rows, 1,481 valid, 241 NoData, XY mismatch 0.
- Metric recomputation output:
  - `IDW 20m/25点`: MAE 3.475606, RMSE 5.787635.
  - `Kriging 20m/40点`: MAE 3.222594, RMSE 5.841043.
  - baseline comparison passed.
- SuperMap registration output: 3 registered results, 1 formal result.

### Current Boundaries

- The MVP does not automate iDesktopX controls.
- Vertical slices and native isosurface extraction remain unverified/failed as documented in known issues.
- RHO physical unit is still marked as pending source confirmation.
- Microseismic, coalbed methane, and DSI-like modules are interfaces/documentation only.

# GeoModelingPlatform MVP Architecture

## Purpose
The first version builds a reliable management and analysis layer for underground resistivity 3D property simulation. It connects standardized `X,Y,Z,RHO` data, train/validation splits, existing SuperMap prediction exports, quality metrics, model/task state, and SuperMap result registration into a traceable closed loop.

## Constraints
- Original materials under `../超图杯资料` are read-only.
- Derived data, cache, logs, reports, and registries are written only inside this project.
- `-9999` in prediction exports is NoData and must become null plus `is_nodata=true`.
- Empty or failed SuperMap outputs must not be marked as successful formal results.
- IDW and ordinary Kriging must not be renamed as DSI.
- Microseismic, coalbed methane, and DSI-like capabilities are interfaces only in this MVP.

## Chosen Stack
See `docs/decisions/0001-technology-stack.md`. The MVP uses Python 3.12, pandas/numpy, pydantic, Typer/Rich, PyYAML, pytest, JSON registries, and Markdown/HTML reports.

## Module Boundaries

### `geomodeling.config`
Loads project configuration, data paths, model definitions, SuperMap registration settings, thresholds, and output locations. Business logic must not hardcode paths, model names, thresholds, or SuperMap dataset names.

### `geomodeling.schemas`
Defines pydantic contracts for dataset registration, validation reports, model metadata, prediction imports, metrics, SuperMap result registration, issues, and result inventories.

### `geomodeling.io`
Reads CSV/JSON files, computes SHA-256, parses SuperMap prediction WKT points, and writes derived artifacts without modifying upstream files.

### `geomodeling.registry`
Stores dataset, model, result, issue, and inventory records as versioned JSON artifacts. Duplicate input hashes are detected and reported.

### `geomodeling.validation`
Implements the resistivity CSV contract: required fields, finite numeric parsing, row counts, positive RHO, duplicate XYZ, ranges, nulls, and train/validation spatial-column separation.

### `geomodeling.metrics`
Aligns validation truth with prediction exports, converts `-9999` to NoData, computes common-valid metrics, spatial-column summaries, depth-band summaries, and baseline comparisons.

### `geomodeling.supermap`
Registers SuperMap datasources/datasets, parameters, states, integrity checks, and error evidence. It records current known failures such as empty isosurface datasets without treating them as successful outputs.

### `geomodeling.reports`
Exports machine-readable JSON and human-readable Markdown/HTML summaries for datasets, model comparison, issues, and result inventories.

### `geomodeling.cli`
Provides the analysis entry for registering data, validating contracts, importing predictions, recomputing metrics, creating model metadata, registering SuperMap results, and exporting reports.

## Data Flow
```text
../超图杯资料 standardized CSVs
  -> hash + contract validation
  -> dataset registry artifacts
  -> train/validation separation checks
  -> prediction export import + NoData normalization
  -> common-valid metric recomputation
  -> baseline comparison and issue detection
  -> model metadata + SuperMap result registry
  -> Markdown/HTML/JSON reports
```

## Error Handling
- Validation failures produce structured issues with severity, scope, evidence, current handling, and whether formal results are blocked.
- Task success requires state, output existence, nonzero/expected records or objects, and readable content.
- External tool errors are stored as raw evidence text and mark the task failed.
- Warnings are allowed for known limitations such as coverage below 100%, metric disagreement between models, boundary-touching anomalies, and unverified vertical slices.

## Testing Strategy
- Contract tests use the real standardized, training, and validation CSVs.
- Metric regression tests compare recomputed five-model metrics with `插值精度对比_总体指标.csv` within a small floating tolerance.
- Import tests verify `-9999` conversion, common valid count 1,481, common NoData count 241, and zero XY mismatch.
- State tests verify empty/failed SuperMap results cannot be marked successful.
- Small fixtures test malformed CSVs, missing fields, non-finite values, duplicate XYZ, and invalid status transitions.

## SuperMap Boundary
The MVP does not automate iDesktopX controls. It records and checks SuperMap outputs through configuration and evidence. Current formal candidate `RHO_KRIG_FINAL_20M_40` can be registered with method, resolution, neighbor count, dimensions, value range, slice settings, threshold settings, and status. Failed datasets `RHO_ISO_77_K40` and `RHO_ISO_HIGH_P95_K40` are registered only as failed/empty evidence.

## Future Interfaces
Later modules should plug in through dataset types and model methods without changing resistivity semantics:
- microseismic: `survey_lines`, `survey_points`, `velocity_samples` contracts;
- coalbed methane: attribute statistics until CRS/elevation/depth datum are confirmed;
- DSI-like/GOCAD: external backends emitting unified XYZV/regular-grid nodes plus model metadata.

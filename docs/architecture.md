# GeoModelingPlatform Architecture

## Purpose

The project builds a reliable management and analysis layer for underground property 3D simulation. v0.1.0 connects standardized `X,Y,Z,RHO` data, train/validation splits, existing SuperMap prediction exports, quality metrics, model/task state, and SuperMap result registration into a traceable closed loop. Current `main` additionally contains the merged microseismic v0.2a data audit foundation: source inventory, DAT parsing, standard tables, 1D survey distance, contracts, issues, and reports.

## Constraints

- Original materials under `../超图杯资料` are read-only.
- Derived data, cache, logs, reports, and registries are written only inside this project (ignored `artifacts/`, `outputs/`, `logs/`).
- `-9999` in prediction exports is NoData and must become null plus `is_nodata=true`.
- Empty or failed SuperMap outputs must not be marked as successful formal results.
- IDW and ordinary Kriging must not be renamed as DSI.
- Coalbed methane and DSI-like capabilities are interfaces only; microseismic has an implemented audit layer but no 2D/3D geometry, cleaning, or interpolation.

## Chosen Stack

See `docs/decisions/0001-technology-stack.md`. The project uses Python 3.12, pandas/numpy, pydantic, Typer/Rich, PyYAML, pytest, JSON registries, and Markdown/HTML reports.

## Module Boundaries

### `geomodeling.config`
Loads project configuration, data paths, model definitions, SuperMap registration settings, thresholds, and output locations. Business logic must not hardcode paths, model names, thresholds, or SuperMap dataset names.

### `geomodeling.schemas`
Defines pydantic contracts for dataset registration, validation reports, model metadata, prediction imports, metrics, SuperMap result registration, issues, and result inventories.

### `geomodeling.io`
Reads CSV/JSON files, computes SHA-256, parses SuperMap prediction WKT points, and writes derived artifacts without modifying upstream files.

### `geomodeling.registry`
Stores dataset, model, result, issue, and inventory records as versioned JSON artifacts. Duplicate input hashes are detected and reported.

### `geomodeling.model_tasks`
Stores model tasks with unique `model_id`, method restrictions, input dataset/hash, parameters, config snapshots, status, role, and fingerprints. It supports idempotent config synchronization, explicit task creation, and default/comparison selection rationale.

### `geomodeling.audit`
Writes JSONL operation audit records with command, operator, UTC time, input hashes, safe parameters, SuperMap version, status, outputs, and error text. Sensitive parameter keys are redacted.

### `geomodeling.issues`
Builds the structured unresolved-issue list used by reports, including RHO unit, local CRS/EPSG, vertical slice, failed isosurface, and SuperMap dataset-level verification boundaries.

### `geomodeling.views`
Registers view configurations for full voxel entry, horizontal slices, threshold anomaly settings, unverified vertical slices, failed isosurfaces, and external open information without rendering UDBX content in Python.

### `geomodeling.validation`
Implements the resistivity CSV contract: required fields, finite numeric parsing, row counts, positive RHO, duplicate XYZ, ranges, nulls, and train/validation spatial-column separation.

### `geomodeling.metrics`
Aligns validation truth with prediction exports, converts `-9999` to NoData, computes common-valid metrics, spatial-column summaries, depth-band summaries, and baseline comparisons.

### `geomodeling.supermap`
Registers SuperMap datasources/datasets, parameters, states, integrity checks, and error evidence. It records current known failures such as empty isosurface datasets without treating them as successful outputs.

### `geomodeling.reports`
Exports machine-readable JSON and human-readable Markdown/HTML summaries for datasets, model comparison, issues, and result inventories.

### `geomodeling.cli`
Provides the analysis entry for registering data, validating contracts, importing predictions, recomputing metrics, creating model metadata, registering SuperMap results, and exporting reports. The microseismic command group is mounted as `geomodeling microseismic`.

### `geomodeling.microseismic` (implemented in v0.2a)

- `config`: typed loader for `config/microseismic.yaml` (formal lines/points, intervals, expected counts, excluded points, cleaning conflicts).
- `inventory`: DAT discovery, SHA-256 snapshots, unexpected/missing file detection.
- `parser`: ASCII whitespace parsing with explicit trailing NUL pseudo-line detection, MSVC `1.#QNAN0`-class token classification, raw-token preservation, and per-file manifest entries. Source files are never modified.
- `geometry`: builds survey lines/points with 1D `cumulative_s_m` from registered intervals; excluded points (W28) are conflict-only rows with null sequence/cumulative values.
- `contracts`: audit checks for file counts, per-line record layers, special-NaN traceability, NUL exclusion, uniqueness, W28 exclusion, monotonic cumulative distance, no fabricated XY/Z, and unchanged source SHA-256.
- `issues`: the 11 standard microseismic issues with severity, scope, evidence, dual sources, current handling, and downstream gate flags.
- `reports`: standard tables (`survey_lines.csv`, `survey_points.csv`, `velocity_samples.csv`), `source_manifest.json`, validation JSON, issue lists, data quality/data dictionary/audit summary Markdown.
- `service` + `cli`: orchestration (`build_audit`, `export_all`, `run_full_audit`) and the `inventory/parse/validate/export-reports/run-audit` command group; blockers return a non-zero exit code while still writing diagnostic reports.

### Future interfaces (not implemented)

- Coalbed methane: attribute statistics only until CRS/elevation/depth datum are confirmed.
- DSI-like/GOCAD: external backends emitting unified XYZV/regular-grid nodes plus model metadata; DSI results must not be re-interpolated with IDW/Kriging inside SuperMap.
- Microseismic 2D/3D reconstruction, formal cleaning, and interpolation remain gated by the confirmation items in `docs/data/microseismic.md`.

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

../超图杯资料 microseismic DATs (read-only)
  -> discovery + SHA-256 snapshot
  -> ASCII/NUL format probing and record parsing
  -> standard tables (lines / points / 2,006 velocity samples)
  -> 1D cumulative distance
  -> contract validation + issue list
  -> JSON/Markdown reports + audit log
```

## Error Handling

- Validation failures produce structured issues with severity, scope, evidence, current handling, and whether formal results are blocked.
- Task success requires state, output existence, nonzero/expected records or objects, and readable content.
- External tool errors are stored as raw evidence text and mark the task failed.
- Warnings are allowed for known limitations such as coverage below 100%, metric disagreement between models, boundary-touching anomalies, and unverified vertical slices.
- Microseismic audit validation passing does not clear downstream geometry, cleaning, or interpolation gates; those are driven by the registered issue flags.

## Testing Strategy

- Portable tests use tiny synthetic fixtures (in-code or `tests/fixtures/`) and run in GitHub Actions without real research data.
- Local real-data regression tests use the adjacent read-only standardized data and microseismic DATs, marked `local_data`; they skip clearly when reference data is unavailable.
- Contract tests use the real standardized, training, and validation CSVs locally.
- Metric regression tests compare recomputed five-model metrics with `插值精度对比_总体指标.csv` within a small floating tolerance.
- Import tests verify `-9999` conversion, common valid count 1,481, common NoData count 241, and zero XY mismatch.
- State tests verify empty/failed SuperMap results cannot be marked successful.
- Evidence tests verify declared/file/dataset/manual evidence boundaries and prevent fake `dataset_verified` claims.
- Microseismic tests verify NUL handling, special NaN tokens, count layers, W28 exclusion and null semantics, stable relative manifest paths, cumulative distance, no fabricated XY/Z, blocker exit codes, and unchanged source SHA-256.

## SuperMap Boundary

The project does not automate iDesktopX controls. It records and checks SuperMap outputs through configuration and evidence. Evidence is split into `declared`, `file_verified`, `dataset_verified`, and `manual_evidence` (see `docs/decisions/0002-supermap-evidence-levels.md`). Formal candidate `RHO_KRIG_FINAL_20M_40` is registered with method, resolution, neighbor count, dimensions, value range, slice settings, threshold settings, and status. Failed datasets `RHO_ISO_77_K40` and `RHO_ISO_HIGH_P95_K40` are registered only as failed/empty evidence. Because the current `dataset_api` is `none`, code may verify the UDBX file but must not claim internal dataset verification.

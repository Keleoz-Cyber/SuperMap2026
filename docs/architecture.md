# GeoModelingPlatform Architecture

## Purpose and status

The project builds a browser-based modeling platform for independent underground-property cases. The target workflow is upload, field mapping, validation, interpolation tuning, spatial validation, formal modeling, visualization, and evidence export. The approved product design is [product-blueprint.md](product-blueprint.md).

Current implementation is still the Python CLI foundation: v0.1.0 connects standardized `X,Y,Z,RHO` data, train/validation splits, existing SuperMap prediction exports, quality metrics, model/task state, and SuperMap result registration. The current code additionally contains the merged microseismic v0.2a audit foundation. FastAPI, the browser UI, generic upload, tuning execution, iServer publishing, microseismic geometry/3σ/interpolation, and gas modeling are target capabilities, not implemented capabilities. External microseismic and gas CSVs plus iDesktopX experiments are manual evidence, not delivered modules.

## Constraints

- Original materials under `../超图杯资料` are read-only.
- Derived data, cache, logs, reports, and registries are written only inside this project (ignored `artifacts/`, `outputs/`, `logs/`).
- `-9999` in prediction exports is NoData and must become null plus `is_nodata=true`.
- Empty or failed SuperMap outputs must not be marked as successful formal results.
- IDW and ordinary Kriging must not be renamed as DSI.
- Different research cases retain independent coordinate systems. They may share software and algorithms but must not be spatially overlaid without control points and a proven transformation.
- Coalbed methane and DSI-like capabilities are interfaces only; microseismic has an implemented audit layer but no implemented 2D/3D geometry, 3σ filtering, or interpolation.

## Current and target stack

See `docs/decisions/0001-technology-stack.md` for the delivered CLI baseline. It uses Python 3.12, pandas/numpy, pydantic, Typer/Rich, PyYAML, pytest, JSON registries, and Markdown/HTML reports.

The next stage keeps that core and adds:

- FastAPI for dataset, experiment, tuning, result, and publishing APIs;
- a TypeScript browser client for upload, tuning, comparison, and visualization;
- a replaceable interpolation-engine interface with Python IDW/Kriging as the first implementation;
- a SuperMap iServer adapter for runtime checks and service publishing;
- a SuperMap Web client path for final map/scene presentation.

## Target runtime architecture (not yet implemented)

```text
Browser UI
  -> FastAPI application service
       -> existing validation / metrics / registry / audit modules
       -> dataset adapters (CSV, XLSX, microseismic DAT)
       -> tuning engine (manual run + grid search)
       -> interpolation engines (Python first; iServer/GPA optional adapter)
       -> result exporters
       -> iServer publishing adapter
  -> published SuperMap map/data/3D services
```

The FastAPI layer owns job state and calls the modeling core. The browser does not implement interpolation formulas. iServer publishing is a separate stage: a successful local model is not marked as a successful published service until the service URL is reachable and its metadata is checked.

## Target module boundaries

- `datasets`: uploads, workbook selection, field mapping, units, coordinate declaration, preview, hash, and schema version.
- `experiments`: a stable experiment ID, input dataset fingerprint, algorithm, parameters, validation split, status, metrics, and artifacts.
- `interpolation`: common 2D/3D engine protocol; IDW and ordinary Kriging implementations; no SuperMap-specific UI dependency.
- `tuning`: manual candidate runs, grid search, cancellation, per-candidate errors, common-valid comparison, and recommendation rationale.
- `api`: FastAPI routes and task progress; delegates domain logic instead of duplicating it.
- `publishing`: iServer health/version/capability checks, publishing requests, service URL evidence, and retryable failure state.
- `web`: upload wizard, tuning laboratory, model leaderboard, result scene, and evidence export.

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

### `geomodeling.publishing` (implemented in v0.3)

- `client`: non-throwing iServer REST client (optional admin token via environment variables only); every call degrades gracefully when iServer is down.
- `probe`: runtime probing (services list, VOLUME dataset metadata comparison, realspace scenes/layers) and the six-state publish evidence chain (`model_succeeded` … `manual_visual_checked`); live probe failures never rewrite modeling state.
- `evidence`: browser-load report store (JSONL under ignored `outputs/`).
- `s3mb`: **targeted** S3M 2.0 voxel point-cloud tile parser (zlib header, float32 vertex/weight blocks, cross-tile coordinate deduplication with conflicting weights rejected) with fail-closed contract validation (header magic, scp version, file type, finite wDescript range vs registry, finite cells, sane count, envelope bbox). Only guaranteed for the local iDesktopX 2026 voxel cache; not a general S3MB parser.

### `geomodeling.api` (implemented in v0.3)

FastAPI layer: `/api/health`, `/api/iserver/status`, `/api/cases`, `/api/cases/resistivity` (leaderboard from config + metric artifacts), `/publish-status` (live evidence chain), `/points` (standardized CSV point cloud with SHA-256), `/voxel-cells` (S3M cache cells fetched via iServer REST, contract-validated, `?refresh=true` bypass), `/api/evidence/browser-load`. Serves `web/dist` when built; browser never holds iServer admin credentials.

### Future interfaces (not implemented)

- Coalbed methane: an independent experimental 3D case using Xi'an 1980 zone 20 candidate coordinates, DEM-derived surface elevations, and a vertical-borehole midpoint approximation. The current 58-point table is external evidence; volume rendering is parked because loading the generated voxel crashes iDesktopX.
- DSI-like/GOCAD: external backends emitting unified XYZV/regular-grid nodes plus model metadata; DSI results must not be re-interpolated with IDW/Kriging inside SuperMap.
- Microseismic local geometry and data rules are now design inputs recorded in `docs/data/microseismic.md`; code/config implementation and regression validation remain pending.

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

External derived microseismic/gas CSVs (read-only evidence)
  -> fingerprint + contract import (target)
  -> provenance and rule validation (target)
  -> experiment input without overwriting source/audit tables (target)
```

## Error Handling

- Validation failures produce structured issues with severity, scope, evidence, current handling, and whether formal results are blocked.
- Task success requires state, output existence, nonzero/expected records or objects, and readable content.
- External tool errors are stored as raw evidence text and mark the task failed.
- Warnings are allowed for known limitations such as coverage below 100%, metric disagreement between models, boundary-touching anomalies, and unverified vertical slices.
- Microseismic audit validation passing does not clear the current code's downstream gates. External rule confirmation and manual CSV generation are recorded separately until schema, config, implementation, and regression tests reproduce them.

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

The target iServer adapter does not weaken this boundary. Installation, process startup, license availability, REST reachability, publishing success, and browser rendering are separate evidence states. Local environment details, the missing bundled iClient SDK boundary, and official documentation order are in [supermap-integration.md](supermap-integration.md).

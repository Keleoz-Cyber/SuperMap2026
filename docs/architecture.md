# GeoModelingPlatform Architecture

## Purpose and status

The project builds a browser-based modeling platform for independent underground-property cases. The target workflow is upload, field mapping, validation, interpolation tuning, spatial validation, formal modeling, visualization, and evidence export. The approved product design is [product-blueprint.md](product-blueprint.md).

Current implementation is still the Python CLI foundation: v0.1.0 connects standardized `X,Y,Z,RHO` data, train/validation splits, existing SuperMap prediction exports, quality metrics, model/task state, and SuperMap result registration. The current code additionally contains the merged microseismic v0.2a audit foundation, the released v0.5 microseismic second-case modeling loop (a domain adapter derives local XYZ/Vx samples from the 22 formal DATs, applies the confirmed global 3σ filter and exact-XYZ arithmetic-mean aggregation behind a byte-pinned golden gate, and feeds the resulting 1,911 modeling nodes into the generic v0.4 platform; browser wizard and CLI share the same derivation kernel) and, on the v0.6 branch, the professional modeling layer: deterministic omnidirectional/directional variogram diagnostics with human-confirmed anisotropy, rotated sector search neighborhoods shared by IDW and ordinary Kriging, Kriging native estimation variance, out-of-fold residuals with an empirical error scale, fold-leakage inspection, explicit-threshold connected anomaly regions, compatibility-fingerprinted two-candidate comparison, and a hashed professional evidence export. Gas modeling, absolute georeferencing, cross-case overlay, and automated iServer publishing remain target capabilities, not implemented capabilities. External gas CSVs plus iDesktopX experiments are manual evidence, not delivered modules.

## Constraints

- Original materials under `../超图杯资料` are read-only.
- Derived data, cache, logs, reports, and registries are written only inside this project (ignored `artifacts/`, `outputs/`, `logs/`).
- `-9999` in prediction exports is NoData and must become null plus `is_nodata=true`.
- Empty or failed SuperMap outputs must not be marked as successful formal results.
- IDW and ordinary Kriging must not be renamed as DSI.
- Different research cases retain independent coordinate systems. They may share software and algorithms but must not be spatially overlaid without control points and a proven transformation.
- Coalbed methane and DSI-like capabilities are interfaces only; microseismic has an implemented audit layer (v0.2a) and, since v0.5, an implemented local-geometry/3σ/aggregation derivation and modeling loop. It still has no absolute CRS and no cross-case overlay.

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

### `geomodeling.microseismic` v0.5 derivation layer (implemented in v0.5)

- `derivation`: converts finite audit samples to confirmed local XYZ/Vx rows (`depth_m = wl_half_km × 1000` positive down, `z_local_m = -depth_m` positive up); non-finite records keep raw tokens in a separate invalid layer and never enter statistics; audit samples are never mutated.
- `filtering`: one global 3σ filter over depth and Vx with sample standard deviation (`ddof=1`) and two-pass sequential float64 summation — the exact arithmetic that reproduces the golden z-score bytes; rejected rows carry `depth_zscore/vx_zscore/filter_status/filter_reason`.
- `canonical`: byte-stable CSV serialization (UTF-8 BOM + CRLF, fixed column order) for the accepted/rejected layers; atomic write-temp-then-replace.
- `golden`: fail-closed golden gate comparing each run against the pinned contract (accepted/rejected counts, per-line accepted counts, rejection reasons, both canonical SHA-256s, conflict-group/row counts, modeling-node count); any failed check blocks the import.
- `aggregation`: exact-`(x,y,z)` float-equality grouping (no tolerance) with arithmetic-mean Vx; single-record groups keep the original value; provenance keeps `source_sample_ids/sample_count/min/max/std` (`ddof=1`, empty for single-sample groups); rule version `arithmetic_mean_exact_xyz` evolves independently of the derivation rule version. The 1,925 accepted rows are never modified; output is 1,911 unique modeling nodes (13 conflict groups, 27 member rows, 14 collapsed).
- `service`: `derive_from_directory` composes audit → local XYZ → 3σ → golden gate → aggregation, exports all layers (`source_records_2006.csv`, `invalid_records_1.csv`, `rejected_3sigma_80.csv`, `accepted_modeling_1925.csv`, `aggregated_nodes_1911.csv`, `modeling_provenance.parquet`, `derivation_report.json`), keeps `downstream_gates` blocked unless audit contract and golden gate both pass.
- `platform_adapter`: atomic case/dataset import (`source_kind="microseismic_dat_bundle"`); staging directory replaced into the deterministic dataset directory only after every gate passes; compensation on failure removes the DB row, formal directory, and staging directory independently (cleanup failures are logged only).
- `cli`: `geomodeling microseismic derive` (directory → all layers + gates) and `geomodeling microseismic import-case` (directory → platform case + mapped dataset); the v0.2a command group stays compatible.
- `api/routes/microseismic`: `POST /api/cases/{id}/microseismic-imports` (multipart, 22 DATs, 201), `GET /api/datasets/{id}/derivation`, `GET .../derivation/artifacts/{name}` (whitelist), `GET .../derivation/points?layer=accepted|rejected|aggregated&decimate=1`. The browser wizard consumes the same kernel; public payloads never leak absolute local paths.

### `geomodeling.publishing` (implemented in v0.3)

- `client`: non-throwing iServer REST client (optional admin token via environment variables only); every call degrades gracefully when iServer is down.
- `probe`: runtime probing (services list, VOLUME dataset metadata comparison, realspace scenes/layers) and the six-state publish evidence chain (`model_succeeded` … `manual_visual_checked`); live probe failures never rewrite modeling state.
- `evidence`: browser-load report store (JSONL under ignored `outputs/`).
- `s3mb`: **targeted** S3M 2.0 voxel point-cloud tile parser (zlib header, float32 vertex/weight blocks, cross-tile coordinate deduplication with conflicting weights rejected) with fail-closed contract validation (header magic, scp version, file type, finite wDescript range vs registry, finite cells, sane count, envelope bbox). Only guaranteed for the local iDesktopX 2026 voxel cache; not a general S3MB parser.

### `geomodeling.api` (implemented in v0.3)

FastAPI layer: `/api/health`, `/api/iserver/status`, `/api/cases`, `/api/cases/resistivity` (leaderboard from config + metric artifacts), `/publish-status` (live evidence chain), `/points` (standardized CSV point cloud with SHA-256), `/voxel-cells` (S3M cache cells fetched via iServer REST, contract-validated, `?refresh=true` bypass), `/api/evidence/browser-load`. Serves `web/dist` when built; browser never holds iServer admin credentials.

### `geomodeling.platform` (implemented in v0.4)

- `settings`/`db`/`tables`: `PlatformRuntime` owning the SQLite store (WAL, busy-timeout, `user_version` schema guard) under `GEOMODELING_DATA_DIR` (default `var/geomodeling`, gitignored); restart recovery marks inflight runs `interrupted + PROCESS_RESTARTED` without requeueing.
- `schemas`/`errors`: pydantic contracts for all v0.4 requests/records; `PlatformError` carries stable codes and sanitizes absolute paths from public payloads; every route error uses the `{"error": {code, message, details}}` envelope.
- `uploads`/`ingest`/`quality`: bounded streaming upload (50 MiB / 500k rows), CSV/XLSX inspection and standardization to parquet, and the quality gate (`passed|warnings|blocked`) with exact-set warning confirmation.
- `experiments`/`jobs`/`worker`: manual and bounded grid search (≤50 combinations, stable candidate fingerprints), persisted jobs, and a single-thread `JobWorker` with cooperative cancellation and explicit retry.
- `results`/`exports`/`publications`: idempotent grid materialization (atomic tmp-dir replace), decimated preview (≤50k cells), Z/X/Y orthogonal slices with real coordinates, lineage ZIP exports, and publication records that resolve to `manual_required` without claiming iServer success.
- `legacy_adapter`/`presets`: read-only merge of the immutable v0.3.1 resistivity card (`source_kind="builtin_legacy"`, never writes SQLite) and declarative case presets (`config/presets/`, validated, no absolute paths, no auto-import).

### `geomodeling.modeling` (implemented in v0.4)

- `contracts`/`grid`/`splits`/`metrics`: interpolator protocol, default/user rule grids (cell-count guard), spatial-column k-fold/holdout splits, and common-valid-mask metrics (coverage reported per candidate, never traded for rank).
- `distance`: the experimental `z_scale` parameter — every distance used by neighborhood search and variogram fitting is computed on `(x, y, z × z_scale)` with `0 < z_scale ≤ 20` (presets 0.5/1/2, default 1). It only affects distance/neighborhood/variogram fitting, never rewrites the physical coordinates of results, and is not a confirmed geological anisotropy conclusion.
- `idw`/`kriging`/`variogram`: 2D/3D adapters; ordinary Kriging with per-fold auto variogram fitting (no validation-row leakage) or validated manual nugget/sill/range; technical gate in `docs/evidence/v0.4/kriging-technical-gate.md`.
- `runner`: fold-isolated candidate evaluation with progress persistence, per-candidate failure evidence, and cancellation checks between candidates.
- `slices`: orthogonal X/Y/Z slice extraction over persisted grids (NoData preserved).

### `geomodeling.api.routes` + `web/` (implemented in v0.4)

v0.4 routers (`cases`, `datasets`, `experiments`, `runs`, `results`) registered after the legacy exact routes so `/api/cases/resistivity` can never be swallowed by `/api/cases/{case_id}`; lifespan owns one runtime + one worker. Vue views: case list + upload wizard (`CaseCreateView`, `DatasetWizardView`), tuning lab (`ExperimentView` with parameter editor, persistent progress, honest leaderboard), and result workbench (`ResultWorkbenchView` with ECharts 2D heatmap, Cesium 3D point field using the proven `removeAll()`/rebuild visibility strategy, three-direction slice panel, formal selection, export/publication panels).

### `geomodeling.modeling` professional layer (implemented in v0.6)

- `professional_contracts`: the typed algorithm capability matrix (`supported` / `not_applicable` — "not applicable" is a capability state, never an empty array, zero, or failure) and the public professional DTO contracts; legacy candidates without professional artifacts report `LEGACY_RESULT_NOT_COMPUTED` and are never back-computed on read.
- `pair_sampling`: deterministic point-pair sampling for empirical semivariograms — full pairs up to the 50,000 cap, stratified deterministic sampling beyond it, seed derived from the data SHA-256 plus the diagnosis configuration (never process time), with total/candidate/actual pair counts, sampling rate, and seed origin disclosed in DTOs and artifacts.
- `directional_variogram`: omnidirectional and directional empirical semivariograms (γ(h) = Σ[Z(x_i)−Z(x_j)]² / 2N(h)); azimuth `[0°, 180°)` from +X toward +Y, dip `[-90°, 90°]` toward +Z (2D rejects dip), directions have no sign; bins below `min_pairs_per_bin` are shown but excluded from fitting, and insufficient effective bins fail the diagnosis instead of silently falling back.
- `variogram` fitting evidence: spherical/exponential/Gaussian models fit by pair-count-weighted bounded least squares, persisting `weighted_sse`, convergence, bounds, and `parameter_origin` (`automatic_candidate` per-fold, `final_full_data_fit` at materialization, `manual_confirmed` with `user_prior` fixed parameters, `legacy_auto_fold_fit` for v0.5 candidates); per-fold parameters serve validation metrics only, full-data fits serve final grids only.
- `anisotropy`: candidate principal directions generated from directional range/structure differences as diagnostic advice requiring explicit human confirmation; confirmations are immutable snapshots (azimuth, dip, roll, scale ratios, evidence references, note) and any parameter change creates a new snapshot; the confirmed Kriging transform is `x′ = S Rᵀ x` with legacy `z_scale` normalized into the scale matrix (never stacked), identity configuration exactly reproducing isotropic distance.
- `neighborhood`: rotated ellipse (2D) / ellipsoid (3D) search with sector caps (`sector_count` × `max_per_sector`), stable distance ordering tie-broken by `source_row`, shared selector for IDW and ordinary Kriging; IDW weights still use `(x, y, z × z_scale)` distance — rotation only shapes the candidate set, never an "IDW variogram anisotropy"; insufficient neighbors return NoData with reason, never silent radius growth or global fallback.
- `kriging`: ordinary Kriging weights plus the native estimation variance `σ² = λᵀγ₀ + μ`; float-tolerance micro-negative clamping counted in diagnostics, significant negative/non-finite values return NoData with reason, and least-squares degradation is flagged in the variance artifact.
- `fold_artifacts`: persisted fold assignments, out-of-fold predictions, and residuals with stable row identity; spatial fold-leakage checks are fail-closed (a failed check fails the whole run), and no in-fold fitted value may enter empirical error analysis.
- `uncertainty`: the empirical error scale for all algorithms — distance-weighted local RMSE over out-of-fold residuals inside the same professional transform and an explicit error neighborhood, with local residual count and coverage; it is not a standard error and is never filled with global RMSE constants.
- `anomalies`: explicit-threshold masks (`direction = high|low`, optional empirical-error and Kriging-std gates, minimum support nodes) with fixed 4-connectivity (2D) / 6-connectivity (3D) components on regular grids only; area/volume support is a Voronoi "grid support estimate", never a reserve; previews are free but only an explicit save creates the immutable extraction.
- `comparison`: two-candidate compatibility fingerprints (same dataset version, fold-plan fingerprint, target row identity, common-valid mask definition, and units); only `compatible` pairs show metric/residual/field deltas, field differences require identical grid definitions over jointly valid nodes.
- `professional_diagnosis`: diagnosis orchestration behind `analysis_jobs` persisted jobs (cancel/retry/restart-`interrupted`, one inflight job per resource via a partial unique index).

### `geomodeling.platform` v5 + `api/routes/professional` + `web/` (implemented in v0.6)

- SQLite migrates transactionally v4 → v5 adding five tables — `professional_diagnostics`, `professional_confirmations`, `professional_result_artifacts`, `anomaly_extractions`, `analysis_jobs` — with a partial unique inflight-job index; databases newer than the code still refuse to start. Artifact directories are written to a sibling temp directory, read back, hashed (SHA-256), and atomically replaced.
- `api/routes/professional`: `POST /api/datasets/{id}/professional-diagnostics` (202, idempotent 200), `GET /api/professional-diagnostics/{id}(/variogram)`, `POST .../confirm` (201), `GET/POST /api/analysis-jobs/{id}(/cancel|/retry)`, `GET /api/results/{id}/professional(/folds|/residuals|/uncertainty/{kind})`, `POST /api/results/{id}/anomaly-extractions` (202), `GET /api/anomaly-extractions/{id}`, `POST /api/professional-comparisons` (201), `GET /api/professional-comparisons/{fingerprint}`, and whitelist-only `GET /api/professional-artifacts/{kind}:{subject}:{logical}/download`; every chain verifies case → dataset → experiment → run → result ownership and returns the unified error envelope (409 for cross-version evidence, missing/tampered artifacts, or incompatible comparisons).
- `geomodeling professional` CLI (`diagnose/confirm/inspect-result/extract-anomalies/compare`) shares the service layer with the API; `--data-dir` is required and JSON output uses logical identities and relative artifact names without absolute paths.
- Web professional views: `ProfessionalDiagnosisView` (variogram curves with per-bin pair support, fit evidence, anisotropy candidates marked as diagnostic advice, explicit confirmation) and `ProfessionalAnalysisView` (the unified workbench: structure diagnosis, parameter snapshot with origins, per-fold inspection, residuals/empirical error scale/Kriging std with separate color scales, spatial results, anomaly regions, evidence and export); view state stores only the selected candidate ID and display options, never recomputing professional results. Evidence ZIP exports add a `professional/` directory limited to succeeded, registered, hash-matching artifacts — a declared-but-missing or hash-mismatched artifact fails the whole export with 409 (fail-closed), while IDW legitimately omits Kriging variance metadata as `not_applicable`.

### Demo hardening (implemented in v0.4.1)

- `demo_assets` + `api/routes/demo`: the single authoritative public demo CSV (`demo/platform_demo_3d.csv`) with a frozen SHA-256 contract (fail-closed on missing/modified asset) and a sanitized download endpoint.
- `demo_check` + `cli demo-check`: preflight orchestration with injectable probes; blockers (imports/config/frontend build/demo asset/runtime dir/SQLite/port identity) fail with exit 1, iServer/S3M/credential absence stays warning-only; a verified current platform instance on the target port is reported reusable (exact health + OpenAPI title match).
- `scripts/start_demo.ps1`: foreground single-process launcher; no installs, deletions, process kills, or stored secrets; check-only and no-browser switches.
- `PageNavigation.vue`: bounded named-route navigation (`home`/`experiment-detail`/`experiment-create`) on every main page including load-error states; never `history.back()`, never cancels runs.
- Browser test layers: Mock API Playwright (page contracts, navigation recovery) plus Live E2E (real FastAPI + isolated SQLite + real worker on port 5201, unique `GEOMODELING_DATA_DIR`, failure artifacts uploaded as CI `browser-live-evidence`).

### Future interfaces (not implemented)

- Coalbed methane: an independent experimental 3D case using Xi'an 1980 zone 20 candidate coordinates, DEM-derived surface elevations, and a vertical-borehole midpoint approximation. The current 58-point table is external evidence; volume rendering is parked because loading the generated voxel crashes iDesktopX.
- DSI-like/GOCAD: external backends emitting unified XYZV/regular-grid nodes plus model metadata; DSI results must not be re-interpolated with IDW/Kriging inside SuperMap.
- Microseismic absolute georeferencing (needs common control points and azimuth evidence) and automated iServer publishing (`manual_required` stays). The local-geometry/3σ/aggregation derivation itself is implemented since v0.5; see the v0.5 derivation layer above.

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

Microseismic v0.5 derivation (browser wizard and CLI share this kernel)
  -> 2,005 finite samples -> confirmed local XYZ/Vx (rule version pinned)
  -> one global 3σ filter (ddof=1): 80 rejected / 1,925 accepted
  -> exact-XYZ arithmetic-mean aggregation: 13 conflict groups -> 1,911 modeling nodes
  -> golden gate (canonical SHA-256 + counts, fail-closed)
  -> atomic platform dataset import (compensation on failure)
  -> generic tuning / validation / result / export pipeline
  -> export ZIP adds domain_evidence/ (manifest + report + five layered CSVs, all hashed)

Professional modeling (v0.6; browser, API, and CLI share the same service layer)
  -> quality-gated dataset -> professional diagnosis job (analysis_jobs)
  -> deterministic point pairs -> omni/directional empirical variograms
  -> weighted bounded least-squares fit evidence + anisotropy candidates
  -> immutable human confirmation snapshot (new snapshot for any change)
  -> professional candidates (IDW / ordinary Kriging, rotated sector neighborhood)
  -> fold artifacts (assignments / out-of-fold predictions / residuals, leakage fail-closed)
  -> Kriging native variance + empirical error scale (two distinct uncertainty layers)
  -> explicit-threshold connected anomaly regions (immutable on save)
  -> compatibility-fingerprinted two-candidate comparison
  -> evidence ZIP gains professional/ (registered + hash-verified only, 409 fail-closed)

External derived microseismic/gas CSVs (read-only evidence)
  -> microseismic pair is now the golden regression source regenerated in-repo (v0.5)
  -> gas table remains external evidence only
  -> fingerprint + contract import (target)
  -> provenance and rule validation (target)
  -> experiment input without overwriting source/audit tables (target)
```

## Error Handling

- Validation failures produce structured issues with severity, scope, evidence, current handling, and whether formal results are blocked.
- Task success requires state, output existence, nonzero/expected records or objects, and readable content.
- External tool errors are stored as raw evidence text and mark the task failed.
- Warnings are allowed for known limitations such as coverage below 100%, metric disagreement between models, boundary-touching anomalies, and unverified vertical slices.
- Since v0.5 the microseismic downstream gates are driven by the derivation run itself: audit contract and golden gate both passing clears `geometry/cleaning/interpolation_blocked`; any failure keeps them blocked, fails the import, and still writes diagnostic layers.

## Testing Strategy

- Portable tests use tiny synthetic fixtures (in-code or `tests/fixtures/`) and run in GitHub Actions without real research data.
- Local real-data regression tests use the adjacent read-only standardized data and microseismic DATs, marked `local_data`; they skip clearly when reference data is unavailable.
- Contract tests use the real standardized, training, and validation CSVs locally.
- Metric regression tests compare recomputed five-model metrics with `插值精度对比_总体指标.csv` within a small floating tolerance.
- Import tests verify `-9999` conversion, common valid count 1,481, common NoData count 241, and zero XY mismatch.
- State tests verify empty/failed SuperMap results cannot be marked successful.
- Evidence tests verify declared/file/dataset/manual evidence boundaries and prevent fake `dataset_verified` claims.
- Microseismic tests verify NUL handling, special NaN tokens, count layers, W28 exclusion and null semantics, stable relative manifest paths, cumulative distance, no fabricated XY/Z, blocker exit codes, and unchanged source SHA-256.
- Microseismic v0.5 tests verify the local XYZ derivation (coordinates/depth sign/units/rule version), the exact 3σ statistics (ddof=1, two-pass summation, anchor mean/std), canonical byte stability, golden-gate fail-closed behavior, exact-XYZ aggregation with provenance, atomic import compensation, the derivation API routes, and a `local_data` end-to-end regression against the real 22 DATs (2,006/2,005/80/1,925/1,911 plus both golden SHA-256s).
- Professional v0.6 tests verify the semivariogram math on hand-computed samples, deterministic sampling byte-stability, model fitting bounds and convergence evidence, 2D/3D rotation matrices and isotropy equivalence, sector neighborhoods with stable tie-breaks, the Kriging variance reference system with negative-clamp/failure semantics, the empirical error scale, 4/6-connectivity with Voronoi support estimates, synthetic anisotropy structures (candidates within tolerance, never auto-adopted), SQLite v4 → v5 migration, diagnosis/artifact/extraction state machines with restart/cancel/retry, ownership chains with path sanitization, capability applicability, comparison fingerprints, export fail-closed behavior, legacy read-only compatibility, and the version/documentation release contract (`tests/test_version_consistency.py`, `tests/test_v06_docs.py`, banned-claim doc scan).

## SuperMap Boundary

The project does not automate iDesktopX controls. It records and checks SuperMap outputs through configuration and evidence. Evidence is split into `declared`, `file_verified`, `dataset_verified`, and `manual_evidence` (see `docs/decisions/0002-supermap-evidence-levels.md`). Formal candidate `RHO_KRIG_FINAL_20M_40` is registered with method, resolution, neighbor count, dimensions, value range, slice settings, threshold settings, and status. Failed datasets `RHO_ISO_77_K40` and `RHO_ISO_HIGH_P95_K40` are registered only as failed/empty evidence. Because the current `dataset_api` is `none`, code may verify the UDBX file but must not claim internal dataset verification.

The target iServer adapter does not weaken this boundary. Installation, process startup, license availability, REST reachability, publishing success, and browser rendering are separate evidence states. Local environment details, the missing bundled iClient SDK boundary, and official documentation order are in [supermap-integration.md](supermap-integration.md).

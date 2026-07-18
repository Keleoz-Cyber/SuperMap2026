# ADR 0002: SuperMap Evidence Levels

## Status
Accepted

## Context
The first MVP registered SuperMap outputs mostly from YAML configuration. That is useful for traceability, but it must not be described as programmatic verification of UDBX internals. The project also has manual iDesktopX evidence for the full voxel, horizontal slices, and threshold filtering, while native isosurface extraction failed and left empty datasets.

## Decision
Use explicit SuperMap evidence levels:

- `declared`: value comes only from configuration or manual registration.
- `file_verified`: code verified that the configured UDBX path exists, is a file, and recorded file size, modification time, and optionally SHA-256.
- `dataset_verified`: a supported SuperMap API/SDK has read the dataset and confirmed existence, type, and key properties. This is not allowed unless such an adapter is real and successful.
- `manual_evidence`: human iDesktopX verification is recorded as evidence text or an index, but it does not upgrade the programmatic evidence level.

The current `dataset_api` is `none`, so all configured SuperMap results may reach `file_verified` when `../Project/expore1.udbx` exists, but none may claim `dataset_verified`.

## Consequences
- `register-supermap-results` reports configuration registration counts and evidence levels separately.
- `verify-supermap` emits a machine-readable verification report.
- Failed isosurface datasets remain `failed/failed_empty/object_count=0` even when the UDBX file itself exists.
- Reports must not convert declared or manual evidence into programmatic dataset verification.

# ADR 0003: Browser Platform and iServer Integration

## Status

Accepted for the next development stage on 2026-07-22.

## Context

The released CLI baseline is reliable but is not the final contest interface. The target is a judge-facing browser application that uploads property data, validates it, tunes interpolation, compares models, publishes GIS results, and presents two- and three-dimensional evidence. The current iServer/iClient3D runtime and publishing path still carry more delivery risk than the internal CLI modules.

## Decision

- Preserve the existing Python CLI and domain modules as the reproducible core.
- Add FastAPI as the application and task API; the browser never implements interpolation formulas.
- Add a TypeScript browser application. The concrete UI framework may be selected after an iClient3D compatibility spike; framework choice must not change the API or evidence contracts.
- Use iServer as the publishing and GIS service boundary, not as the only place where interpolation can run.
- Use iClient3D for Cesium for the formal three-dimensional SuperMap path after SDK acquisition and a minimal runtime proof.
- Deliver a thin vertical slice with the existing resistivity result before implementing generic upload and the complete tuning engine.
- Keep resistivity, microseismic, and gas as independent cases. Gas is temporarily parked because its current volume dataset crashes iDesktopX during scene loading.

## Consequences

- A polished frontend shell without a real iServer service is not an accepted vertical slice.
- A successful local model is not a successful publication until the service metadata and browser load are verified.
- iServer credentials and management tokens remain server-side.
- The first release may degrade gracefully to local result metadata when iServer is unavailable.
- Generic upload, IDW/Kriging execution, grid search, and additional cases follow the first published-result slice.

## Validation

This decision is validated when one existing resistivity result can be inspected through FastAPI, published or registered through the iServer adapter, loaded in the browser, and accompanied by reproducible status and evidence without breaking the current 80-test Python baseline.

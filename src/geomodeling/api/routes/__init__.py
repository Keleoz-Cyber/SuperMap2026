"""v0.4 API route modules (mounted by the app factory in Task 10).

v0.5 adds the ``microseismic`` router (multipart DAT import + derivation
evidence); it is included with the other generic routers after the legacy
exact routes so it can never shadow ``/api/cases/resistivity``.

v0.6 adds the ``professional`` router (professional diagnostics, immutable
confirmations, persistent analysis jobs, professional result evidence,
anomaly extractions, two-candidate comparisons and allowlisted artifact
downloads); it is registered after the microseismic router and before the
frontend static mount.
"""

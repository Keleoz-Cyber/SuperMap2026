"""SuperMap iServer publishing adapter: runtime probe and publish evidence.

This package owns the boundary between the platform and iServer. Modeling
state never depends on iServer availability; publishing failures are
recorded as retryable evidence instead of rewriting model state.
"""

from .cache_contract import CacheContract, contract_from_config, formal_result
from .cache_manifest import (
    CacheManifest,
    compute_manifest_digest,
    load_manifest,
    verify_manifest_digest,
    verify_tile_set,
)
from .client import IServerClient
from .evidence import latest_browser_load, latest_valid_browser_load, record_browser_load
from .probe import (
    build_publish_evidence_chain,
    probe_iserver,
    verify_data_service,
    verify_realspace_service,
)
from .s3mb import (
    S3MBContractError,
    dedupe_cells,
    parse_s3mb,
    parse_s3mb_bytes,
    validate_cache_scp,
    validate_cells,
)
from .schemas import (
    BrowserLoadReport,
    EvidenceChain,
    EvidenceSource,
    EvidenceState,
    EvidenceStateName,
    IServerStatus,
    RenderKind,
    ServiceCheck,
)

__all__ = [
    "IServerClient",
    "latest_browser_load",
    "latest_valid_browser_load",
    "record_browser_load",
    "build_publish_evidence_chain",
    "probe_iserver",
    "verify_data_service",
    "verify_realspace_service",
    "S3MBContractError",
    "dedupe_cells",
    "parse_s3mb",
    "parse_s3mb_bytes",
    "validate_cache_scp",
    "validate_cells",
    "CacheContract",
    "contract_from_config",
    "formal_result",
    "CacheManifest",
    "compute_manifest_digest",
    "load_manifest",
    "verify_manifest_digest",
    "verify_tile_set",
    "BrowserLoadReport",
    "EvidenceChain",
    "EvidenceSource",
    "EvidenceState",
    "EvidenceStateName",
    "IServerStatus",
    "RenderKind",
    "ServiceCheck",
]

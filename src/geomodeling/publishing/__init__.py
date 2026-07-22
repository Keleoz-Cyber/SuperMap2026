"""SuperMap iServer publishing adapter: runtime probe and publish evidence.

This package owns the boundary between the platform and iServer. Modeling
state never depends on iServer availability; publishing failures are
recorded as retryable evidence instead of rewriting model state.
"""

from .client import IServerClient
from .evidence import latest_browser_load, record_browser_load
from .probe import (
    build_publish_evidence_chain,
    probe_iserver,
    verify_data_service,
    verify_realspace_service,
)
from .schemas import (
    BrowserLoadReport,
    EvidenceChain,
    EvidenceSource,
    EvidenceState,
    EvidenceStateName,
    IServerStatus,
    ServiceCheck,
)

__all__ = [
    "IServerClient",
    "latest_browser_load",
    "record_browser_load",
    "build_publish_evidence_chain",
    "probe_iserver",
    "verify_data_service",
    "verify_realspace_service",
    "BrowserLoadReport",
    "EvidenceChain",
    "EvidenceSource",
    "EvidenceState",
    "EvidenceStateName",
    "IServerStatus",
    "ServiceCheck",
]

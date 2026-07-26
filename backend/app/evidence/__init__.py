"""Phase 8 evidence package."""

from backend.app.evidence.aggregator import collect_evidence_refs, extract_anomaly_signals
from backend.app.evidence.verification import EvidenceVerificationResult, verify_evidence

__all__ = [
    "EvidenceVerificationResult",
    "collect_evidence_refs",
    "extract_anomaly_signals",
    "verify_evidence",
]

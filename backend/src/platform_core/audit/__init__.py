"""
Audit log - append-only, hash-chained (ADR-016).

    hashing.py       canonical hashing for the chain
    writer.py        append_audit_entry, and the AuditConsumer
    verification.py  chain verification and the nightly job entry point

Immutability is enforced three ways: no UPDATE or DELETE grant for the
application role, a database trigger that refuses both from anyone, and the hash
chain that makes any alteration detectable. The first two prevent; the third
detects what prevention could not.
"""

from platform_core.audit.hashing import compute_entry_hash
from platform_core.audit.verification import (
    VerificationResult,
    verify_all_chains,
    verify_chain,
)
from platform_core.audit.writer import AuditConsumer, append_audit_entry

__all__ = [
    "AuditConsumer",
    "VerificationResult",
    "append_audit_entry",
    "compute_entry_hash",
    "verify_all_chains",
    "verify_chain",
]

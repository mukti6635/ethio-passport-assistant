"""Backend-enforced approval service for protected actions.

An LLM prompt is not a security boundary. Before a protected action
(submit, payment, OTP, CAPTCHA, appointment, final legal submission)
executes, the backend must verify a valid, approved, unexpired, unconsumed
approval bound to the correct user and job.

Design (adapted from OpenMuse's prepare/approve pattern):
- The agent/worker PREPARES an action (describes it, hashes params) but
  never executes it directly.
- `prepare()` returns an approval request in `pending` state.
- The user approves/rejects via an authenticated endpoint.
- `consume()` atomically marks the approval used and returns the
  authorized action — exactly once. Concurrent consumes are safe.
- Expiry and rejection prevent execution.

Storage: in-memory dict, matching the existing `_JOBS` pattern. A
Supabase migration (`004_approvals.sql`) defines the durable schema.
Do not claim multi-worker safety: like `_JOBS`, this is single-process.
"""

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


TERMINAL_APPROVAL_STATES = {
    ApprovalState.APPROVED,
    ApprovalState.REJECTED,
    ApprovalState.EXPIRED,
    ApprovalState.CANCELLED,
}


class ExecutionState(str, Enum):
    """Lifecycle of the authorized browser action itself.

    Separates 'the user said yes' (APPROVED) from 'the browser did it'
    (EXECUTING -> SUCCEEDED/FAILED). UNKNOWN means the process crashed or
    lost contact after dispatch but before verification — never blindly
    retried; requires operator reconciliation because the action may
    already have taken effect.
    """

    NOT_STARTED = "not_started"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"  # dispatched but outcome unverified; needs review

# Default approval lifetime: 30 minutes.
DEFAULT_APPROVAL_TTL_S = 30 * 60


def _canonical_params(params: Dict[str, Any]) -> str:
    """Canonical JSON for idempotency hashing. Never logs values."""
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def idempotency_key(action_type: str, params: Dict[str, Any]) -> str:
    """Deterministic key for the exact prepared action + parameters."""
    digest = hashlib.sha256(
        f"{action_type}:{_canonical_params(params)}".encode()
    ).hexdigest()
    return digest[:32]


@dataclass
class Approval:
    """One approval request. Never holds secrets, OTPs, or document contents."""

    approval_id: str
    job_id: str
    session_id: str  # owner; verified against auth on every access
    action_type: str  # e.g. "submit", "payment", "otp", "captcha", "appointment"
    action_label: str  # human-readable, e.g. "Submit passport application"
    consequence: str  # what happens if approved, in plain words
    # Idempotency: same action+params for the same job returns the same request.
    params_hash: str
    # Non-sensitive parameter summary for display (never secrets).
    params_summary: Dict[str, str] = field(default_factory=dict)
    state: ApprovalState = ApprovalState.PENDING
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(
        default_factory=lambda: time.time() + DEFAULT_APPROVAL_TTL_S
    )
    decided_at: Optional[float] = None
    decided_by: Optional[str] = None  # session_id of decider
    decision_reason: Optional[str] = None
    consumed: bool = False  # set atomically when the action executes
    consumed_at: Optional[float] = None
    # Execution lifecycle (crash-recovery). See ExecutionState.
    execution_state: ExecutionState = ExecutionState.NOT_STARTED
    execution_id: Optional[str] = None  # unique per dispatch attempt
    execution_started_at: Optional[float] = None
    execution_ended_at: Optional[float] = None
    execution_evidence: Optional[str] = None  # secret-safe result summary


class ApprovalService:
    """Thread-safe in-memory approval store with atomic consume.

    All methods verify ownership via session_id. The caller (gateway)
    verifies authentication before delegating here.
    """

    def __init__(self, ttl_s: float = DEFAULT_APPROVAL_TTL_S):
        self._lock = threading.Lock()
        self._approvals: Dict[str, Approval] = {}
        # (job_id, params_hash) -> approval_id for idempotent prepare
        self._by_idempotency: Dict[str, str] = {}
        self._ttl_s = ttl_s

    def _expire_locked(self, approval: Approval, now: float) -> None:
        if (
            approval.state == ApprovalState.PENDING
            and now >= approval.expires_at
        ):
            approval.state = ApprovalState.EXPIRED

    def prepare(
        self,
        job_id: str,
        session_id: str,
        action_type: str,
        action_label: str,
        consequence: str,
        params: Dict[str, Any],
        params_summary: Optional[Dict[str, str]] = None,
        ttl_s: Optional[float] = None,
    ) -> Approval:
        """Prepare a protected action. Idempotent: same job + action + params
        returns the existing pending approval instead of creating a duplicate.
        """
        key = idempotency_key(action_type, params)
        lookup = f"{job_id}:{key}"
        now = time.time()
        with self._lock:
            existing_id = self._by_idempotency.get(lookup)
            if existing_id:
                existing = self._approvals.get(existing_id)
                if existing:
                    self._expire_locked(existing, now)
                    if existing.state == ApprovalState.PENDING:
                        return existing
                    # Terminal: fall through and create a fresh request
            approval = Approval(
                approval_id=secrets.token_urlsafe(24),
                job_id=job_id,
                session_id=session_id,
                action_type=action_type,
                action_label=action_label,
                consequence=consequence,
                params_hash=key,
                params_summary=dict(params_summary or {}),
                expires_at=now + (ttl_s if ttl_s is not None else self._ttl_s),
            )
            self._approvals[approval.approval_id] = approval
            self._by_idempotency[lookup] = approval.approval_id
            return approval

    def get(self, approval_id: str, session_id: str) -> Optional[Approval]:
        """Fetch by id, enforcing ownership. Returns None if not found,
        not owned, or (lazily) expired."""
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None or approval.session_id != session_id:
                return None
            self._expire_locked(approval, time.time())
            return approval

    def list_pending(self, session_id: str) -> List[Approval]:
        """All pending, unexpired approvals owned by this session."""
        now = time.time()
        with self._lock:
            out = []
            for approval in self._approvals.values():
                if approval.session_id != session_id:
                    continue
                self._expire_locked(approval, now)
                if approval.state == ApprovalState.PENDING:
                    out.append(approval)
            return sorted(out, key=lambda a: a.created_at)

    def decide(
        self,
        approval_id: str,
        session_id: str,
        approve: bool,
        reason: Optional[str] = None,
    ) -> Optional[Approval]:
        """Approve or reject. Returns the approval, or None if not found,
        not owned, or already decided/expired. Safe against duplicate
        decisions: only PENDING approvals transition."""
        now = time.time()
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None or approval.session_id != session_id:
                return None
            self._expire_locked(approval, now)
            if approval.state != ApprovalState.PENDING:
                return None
            approval.state = (
                ApprovalState.APPROVED if approve else ApprovalState.REJECTED
            )
            approval.decided_at = now
            approval.decided_by = session_id
            if reason:
                approval.decision_reason = reason[:500]
            return approval

    def cancel(self, approval_id: str, session_id: str) -> Optional[Approval]:
        """Cancel a pending approval (e.g. job cancelled)."""
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None or approval.session_id != session_id:
                return None
            if approval.state != ApprovalState.PENDING:
                return None
            approval.state = ApprovalState.CANCELLED
            approval.decided_at = time.time()
            approval.decided_by = session_id
            return approval

    def consume(
        self,
        approval_id: str,
        session_id: str,
        job_id: str,
        action_type: str,
        params: Dict[str, Any],
    ) -> Optional[Approval]:
        """Atomic execution gate. Returns the approval iff ALL hold:
        - exists and owned by session_id
        - bound to job_id
        - action_type and params hash match the prepared action
        - state is APPROVED (not expired/rejected/cancelled)
        - not already consumed
        On success marks consumed exactly once. Concurrent callers: only
        one wins; the others get None.
        """
        key = idempotency_key(action_type, params)
        now = time.time()
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None:
                return None
            if approval.session_id != session_id:
                return None
            if approval.job_id != job_id:
                return None
            self._expire_locked(approval, now)
            if approval.state != ApprovalState.APPROVED:
                return None
            if now >= approval.expires_at:
                return None
            if approval.params_hash != key:
                return None
            if approval.consumed:
                return None
            approval.consumed = True
            approval.consumed_at = now
            return approval

    def claim_for_execution(
        self,
        approval_id: str,
        session_id: str,
        job_id: str,
        action_type: str,
        params: Dict[str, Any],
    ) -> Optional[Approval]:
        """Atomic execution gate, split into claim + result.

        Claims the approved approval for dispatch: APPROVED -> EXECUTING.
        Exactly one caller wins; the claim carries a unique execution_id.
        Unlike consume(), this does NOT mark the action complete — the
        caller must call record_execution_result() after the browser acts.
        """
        key = idempotency_key(action_type, params)
        now = time.time()
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None:
                return None
            if approval.session_id != session_id:
                return None
            if approval.job_id != job_id:
                return None
            self._expire_locked(approval, now)
            if approval.state != ApprovalState.APPROVED:
                return None
            # Expiry bounds the whole lifecycle: an approved-but-unclaimed
            # approval past its expiry must not execute.
            if now >= approval.expires_at:
                return None
            if approval.params_hash != key:
                return None
            if approval.consumed:
                return None
            if approval.execution_state != ExecutionState.NOT_STARTED:
                return None
            approval.consumed = True
            approval.consumed_at = now
            approval.execution_state = ExecutionState.EXECUTING
            approval.execution_id = secrets.token_urlsafe(16)
            approval.execution_started_at = now
            return approval

    def record_execution_result(
        self,
        approval_id: str,
        session_id: str,
        execution_id: str,
        succeeded: bool,
        evidence: Optional[str] = None,
    ) -> Optional[Approval]:
        """Record the browser-verified outcome of a claimed execution.

        Only the holder of the execution_id may record; EXECUTING ->
        SUCCEEDED/FAILED. Returns None if the claim is unknown, already
        recorded, or the execution_id does not match.
        """
        now = time.time()
        with self._lock:
            approval = self._approvals.get(approval_id)
            if approval is None or approval.session_id != session_id:
                return None
            if approval.execution_state != ExecutionState.EXECUTING:
                return None
            if approval.execution_id != execution_id:
                return None
            approval.execution_state = (
                ExecutionState.SUCCEEDED if succeeded else ExecutionState.FAILED
            )
            approval.execution_ended_at = now
            if evidence:
                approval.execution_evidence = evidence[:500]
            return approval

    def reconcile_abandoned(self, max_age_s: float = 300) -> List[Approval]:
        """Crash recovery: find EXECUTING claims older than max_age_s and
        mark them UNKNOWN. These must NEVER be blindly retried — the
        browser action may already have taken effect. Returns the list
        for operator review."""
        now = time.time()
        abandoned = []
        with self._lock:
            for approval in self._approvals.values():
                if (
                    approval.execution_state == ExecutionState.EXECUTING
                    and approval.execution_started_at is not None
                    and now - approval.execution_started_at > max_age_s
                ):
                    approval.execution_state = ExecutionState.UNKNOWN
                    approval.execution_ended_at = now
                    abandoned.append(approval)
        return abandoned

    def cancel_for_job(self, job_id: str, session_id: str) -> int:
        """Cancel all pending approvals for a job (e.g. on job cancel).
        Returns the number cancelled."""
        count = 0
        with self._lock:
            for approval in self._approvals.values():
                if (
                    approval.job_id == job_id
                    and approval.session_id == session_id
                    and approval.state == ApprovalState.PENDING
                ):
                    approval.state = ApprovalState.CANCELLED
                    approval.decided_at = time.time()
                    approval.decided_by = session_id
                    count += 1
        return count


# Module-level singleton, mirroring the existing _JOBS pattern.
# Single-process only; a multi-worker deployment needs the Supabase
# table defined in 004_approvals.sql instead.
APPROVALS = ApprovalService()

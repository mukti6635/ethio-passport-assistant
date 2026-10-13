"""Durable persistence layer for approvals and jobs.

Replaces process-local state for multi-worker correctness. The gateway
uses the in-memory stores by default (single process); durable modes:

- ETHIO_TASK_STORE=pg + ETHIO_PG_DSN: direct PostgreSQL stores
  (PgApprovalStore here, PgTaskStore in task_store.py) — used for
  local development and the local-PostgreSQL test suites.
- ETHIO_USE_SUPABASE=1 with SUPABASE_URL and SUPABASE_SERVICE_KEY:
  Supabase-backed stores via PostgREST/RPC.

The service-role key is server-side only. It is NEVER sent to Flutter,
logged, or embedded in client-visible configuration.

Verification status: the SQL contract (migrations 001+003+004, plus
005's job RPCs) and both PG stores are verified against a real local
PostgreSQL in api/test_postgres.py and api/test_task_store_pg.py.
Migration 004/005 have NOT been applied to the live Supabase project,
and the Supabase stores are exercised through a fake transport plus the
shared SQL contract — live Supabase verification remains outstanding.
"""

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from approvals import (
    DEFAULT_APPROVAL_TTL_S,
    Approval,
    ApprovalService,
    ApprovalState,
    ExecutionState,
    idempotency_key,
)


class ApprovalStore(ABC):
    """Durable approval persistence. Mirrors ApprovalService semantics.

    The public contract is the gateway's calling convention —
    prepare(job_id=..., session_id=..., action_type=..., params=...)
    — identical to ApprovalService.prepare, so the gateway and the
    WorkerLoop can use any store interchangeably. _persist() is the
    store-internal row insert.
    """

    durable = False

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
        import secrets as _secrets

        now = time.time()
        approval = Approval(
            approval_id=_secrets.token_urlsafe(24),
            job_id=job_id,
            session_id=session_id,
            action_type=action_type,
            action_label=action_label,
            consequence=consequence,
            params_hash=idempotency_key(action_type, params),
            params_summary=dict(params_summary or {}),
            state=ApprovalState.PENDING,
            created_at=now,
            expires_at=now + (
                ttl_s if ttl_s is not None else DEFAULT_APPROVAL_TTL_S
            ),
        )
        return self._persist(approval)

    @abstractmethod
    def _persist(self, approval: Approval) -> Approval:
        ...

    @abstractmethod
    def get(self, approval_id: str, session_id: str) -> Optional[Approval]:
        ...

    @abstractmethod
    def list_pending(self, session_id: str) -> List[Approval]:
        ...

    @abstractmethod
    def decide(
        self, approval_id: str, session_id: str, approve: bool,
        reason: Optional[str] = None,
    ) -> Optional[Approval]:
        ...

    @abstractmethod
    def claim_for_execution(
        self, approval_id: str, session_id: str, job_id: str,
        action_type: str, params: Dict[str, Any],
    ) -> Optional[Approval]:
        ...

    @abstractmethod
    def record_execution_result(
        self, approval_id: str, session_id: str, execution_id: str,
        succeeded: bool, evidence: Optional[str] = None,
    ) -> Optional[Approval]:
        ...

    @abstractmethod
    def reconcile_abandoned(self, max_age_s: float = 300) -> List[Approval]:
        ...

    @abstractmethod
    def cancel_for_job(self, job_id: str, session_id: str) -> int:
        ...


def _approval_to_row(a: Approval, owner_id: str) -> Dict[str, Any]:
    """Serialize for Supabase. Never includes raw params or secrets."""
    return {
        "approval_id": a.approval_id,
        "job_id": a.job_id,
        "owner_id": owner_id,
        "session_id": a.session_id,
        "action_type": a.action_type,
        "action_label": a.action_label,
        "consequence": a.consequence,
        "params_hash": a.params_hash,
        "params_summary": a.params_summary,
        "state": a.state.value,
        "created_at": _ts(a.created_at),
        "expires_at": _ts(a.expires_at),
        "decided_at": _ts(a.decided_at) if a.decided_at else None,
        "decided_by": a.decided_by,
        "decision_reason": a.decision_reason,
        "consumed": a.consumed,
        "consumed_at": _ts(a.consumed_at) if a.consumed_at else None,
        "execution_state": a.execution_state.value,
        "execution_id": a.execution_id,
        "execution_started_at": (
            _ts(a.execution_started_at) if a.execution_started_at else None
        ),
        "execution_ended_at": (
            _ts(a.execution_ended_at) if a.execution_ended_at else None
        ),
        "execution_evidence": a.execution_evidence,
    }


def _ts(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _row_to_approval(row: Dict[str, Any]) -> Approval:
    def _epoch(v: Any) -> Optional[float]:
        if not v:
            return None
        from datetime import datetime
        if isinstance(v, datetime):
            return v.timestamp()
        return datetime.fromisoformat(v).timestamp()

    return Approval(
        approval_id=row["approval_id"],
        job_id=row["job_id"],
        session_id=row["session_id"],
        action_type=row["action_type"],
        action_label=row["action_label"],
        consequence=row["consequence"],
        params_hash=row["params_hash"],
        params_summary=dict(row.get("params_summary") or {}),
        state=ApprovalState(row["state"]),
        created_at=_epoch(row["created_at"]) or time.time(),
        expires_at=_epoch(row["expires_at"]) or time.time(),
        decided_at=_epoch(row.get("decided_at")),
        decided_by=row.get("decided_by"),
        decision_reason=row.get("decision_reason"),
        consumed=bool(row.get("consumed")),
        consumed_at=_epoch(row.get("consumed_at")),
        execution_state=ExecutionState(
            row.get("execution_state") or "not_started"
        ),
        execution_id=row.get("execution_id"),
        execution_started_at=_epoch(row.get("execution_started_at")),
        execution_ended_at=_epoch(row.get("execution_ended_at")),
        execution_evidence=row.get("execution_evidence"),
    )


class SupabaseApprovalStore(ApprovalStore):
    durable = True

    """Supabase-backed approval store via the REST API.

    Uses the service-role key (server-side only, bypasses RLS for the
    trusted worker). All queries filter by session_id for ownership.

    Atomic claim uses a two-step pattern inside a transaction via the
    `rpc` endpoint or sequential REST calls with row locking. The
    UNIQUE(job_id, params_hash) constraint enforces idempotent prepare.
    """

    def __init__(self, url: str, service_key: str, transport: Any = None):
        self._url = url.rstrip("/")
        self._key = service_key
        # transport: object with .get/.post/.patch like requests; injectable
        # for tests. Defaults to a lazy import of `requests`.
        self._transport = transport

    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _t(self) -> Any:
        if self._transport is not None:
            return self._transport
        import requests

        return requests

    def _table(self) -> str:
        return f"{self._url}/rest/v1/approvals"

    # -- internal helpers ------------------------------------------------

    def _fetch_one(
        self, approval_id: str, session_id: str
    ) -> Optional[Dict[str, Any]]:
        t = self._t()
        r = t.get(
            self._table(),
            headers=self._headers(),
            params={
                "approval_id": f"eq.{approval_id}",
                "session_id": f"eq.{session_id}",
                "select": "*",
            },
        )
        rows = r.json() if r.status_code == 200 else []
        return rows[0] if rows else None

    def _update(
        self, approval_id: str, patch: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        t = self._t()
        r = t.patch(
            self._table(),
            headers=self._headers(),
            params={"approval_id": f"eq.{approval_id}"},
            json=patch,
        )
        rows = r.json() if r.status_code == 200 else []
        return rows[0] if rows else None

    # -- ApprovalStore implementation ------------------------------------

    def _persist(self, approval: Approval) -> Approval:
        # owner_id: in production this comes from the authenticated JWT's
        # sub claim. The gateway passes it; here we use session_id as the
        # owner key for the local contract.
        t = self._t()
        row = _approval_to_row(approval, owner_id=approval.session_id)
        r = t.post(self._table(), headers=self._headers(), json=row)
        if r.status_code == 409:
            # Unique violation on (job_id, params_hash): return existing.
            existing = t.get(
                self._table(),
                headers=self._headers(),
                params={
                    "job_id": f"eq.{approval.job_id}",
                    "params_hash": f"eq.{approval.params_hash}",
                    "state": "eq.pending",
                    "select": "*",
                },
            )
            rows = existing.json() if existing.status_code == 200 else []
            if rows:
                return _row_to_approval(rows[0])
        r.raise_for_status()
        return _row_to_approval(r.json()[0])

    def get(self, approval_id: str, session_id: str) -> Optional[Approval]:
        row = self._fetch_one(approval_id, session_id)
        if row is None:
            return None
        approval = _row_to_approval(row)
        # Lazy expiry, mirroring the in-memory service.
        if (
            approval.state == ApprovalState.PENDING
            and time.time() >= approval.expires_at
        ):
            updated = self._update(
                approval_id, {"state": ApprovalState.EXPIRED.value}
            )
            if updated:
                approval = _row_to_approval(updated)
        return approval

    def list_pending(self, session_id: str) -> List[Approval]:
        t = self._t()
        r = t.get(
            self._table(),
            headers=self._headers(),
            params={
                "session_id": f"eq.{session_id}",
                "state": "eq.pending",
                "select": "*",
                "order": "created_at.asc",
            },
        )
        r.raise_for_status()
        out = []
        for row in r.json():
            a = _row_to_approval(row)
            if time.time() < a.expires_at:
                out.append(a)
        return out

    def decide(
        self, approval_id: str, session_id: str, approve: bool,
        reason: Optional[str] = None,
    ) -> Optional[Approval]:
        row = self._fetch_one(approval_id, session_id)
        if row is None:
            return None
        a = _row_to_approval(row)
        if a.state != ApprovalState.PENDING or time.time() >= a.expires_at:
            return None
        patch = {
            "state": (
                ApprovalState.APPROVED.value
                if approve else ApprovalState.REJECTED.value
            ),
            "decided_at": _ts(time.time()),
            "decided_by": session_id,
        }
        if reason:
            patch["decision_reason"] = reason[:500]
        updated = self._update(approval_id, patch)
        return _row_to_approval(updated) if updated else None

    def _rpc(self, fn_name: str, body: Dict[str, Any]) -> Any:
        """Call a Postgres function via PostgREST RPC.

        Returns the parsed JSON (list of rows for setof functions).
        Raises RuntimeError on HTTP errors so a missing function
        (migration not applied) fails loudly instead of falling back.
        """
        t = self._t()
        r = t.post(
            f"{self._url}/rest/v1/rpc/{fn_name}",
            headers=self._headers(),
            json=body,
        )
        if r.status_code >= 400:
            raise RuntimeError(
                f"RPC {fn_name} failed: HTTP {r.status_code}. "
                "Apply migration 004 (atomic approval functions) "
                "before enabling durable storage."
            )
        return r.json()

    def claim_for_execution(
        self, approval_id: str, session_id: str, job_id: str,
        action_type: str, params: Dict[str, Any],
    ) -> Optional[Approval]:
        """Atomic claim via the database-side RPC (migration 004).

        claim_approval_for_execution locks the row (SELECT ... FOR
        UPDATE), validates owner/job/state/expiry/params hash, and
        flips execution_state to 'executing' in one transaction.
        Exactly one concurrent caller wins. Verified against real
        PostgreSQL in api/test_postgres.py (10-way race, 1 winner).
        """
        import secrets as _secrets

        execution_id = _secrets.token_urlsafe(16)
        rows = self._rpc(
            "claim_approval_for_execution",
            {
                "p_approval_id": approval_id,
                "p_session_id": session_id,
                "p_job_id": job_id,
                "p_params_hash": idempotency_key(action_type, params),
                "p_execution_id": execution_id,
            },
        )
        if not rows:
            return None
        claimed = _row_to_approval(rows[0])
        if claimed.execution_id != execution_id:
            return None
        return claimed

    def record_execution_result(
        self, approval_id: str, session_id: str, execution_id: str,
        succeeded: bool, evidence: Optional[str] = None,
    ) -> Optional[Approval]:
        """Record the verified outcome via the RPC: only the holder of
        execution_id, only from the 'executing' state."""
        rows = self._rpc(
            "record_approval_execution_result",
            {
                "p_approval_id": approval_id,
                "p_session_id": session_id,
                "p_execution_id": execution_id,
                "p_succeeded": succeeded,
                "p_evidence": (evidence or "")[:500],
            },
        )
        if not rows:
            return None
        return _row_to_approval(rows[0])

    def reconcile_abandoned(self, max_age_s: float = 300) -> List[Approval]:
        """Mark stale 'executing' claims UNKNOWN via the RPC (never
        blind-retry). Returns the reconciled rows."""
        rows = self._rpc(
            "reconcile_abandoned_approvals",
            {"p_max_age_seconds": int(max_age_s)},
        )
        return [_row_to_approval(r) for r in rows]

    def cancel_for_job(self, job_id: str, session_id: str) -> int:
        """Cancel all PENDING approvals for a job (mirrors the in-memory
        service). Uses a state-guarded PATCH so a decided approval can
        never be rewritten."""
        t = self._t()
        r = t.patch(
            self._table(),
            headers=self._headers(),
            params={
                "job_id": f"eq.{job_id}",
                "session_id": f"eq.{session_id}",
                "state": "eq.pending",
            },
            json={
                "state": ApprovalState.CANCELLED.value,
                "decided_at": _ts(time.time()),
                "decided_by": session_id,
            },
        )
        if r.status_code >= 400:
            raise RuntimeError(
                f"cancel_for_job failed: HTTP {r.status_code}"
            )
        return len(r.json())


class PgApprovalStore(ApprovalStore):
    durable = True

    """Direct-PostgreSQL approval store (local development / tests).

    Same semantics as SupabaseApprovalStore, but talks SQL to a local
    Postgres (e.g. pgserver) with psycopg2 — no Supabase credentials
    needed. Atomic operations call the migration 004 functions
    directly. Requires migrations 001 + 004 applied.
    """

    def __init__(self, dsn: str):
        self._dsn = dsn

    def _connect(self):
        import psycopg2

        conn = psycopg2.connect(self._dsn)
        conn.autocommit = True
        return conn

    def _query(self, sql: str, params: tuple, fetch: bool = True):
        import psycopg2.extras

        conn = self._connect()
        try:
            with conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute(sql, params)
                if fetch:
                    return [dict(r) for r in cur.fetchall()]
                return cur.rowcount
        finally:
            conn.close()

    # -- ApprovalStore implementation ------------------------------------

    def _persist(self, approval: Approval) -> Approval:
        import psycopg2.extras

        row = _approval_to_row(approval, owner_id=approval.session_id)
        cols = ", ".join(row.keys())
        placeholders = ", ".join(["%s"] * len(row))
        values = tuple(
            psycopg2.extras.Json(v) if isinstance(v, (dict, list)) else v
            for v in row.values()
        )
        rows = self._query(
            f"insert into public.approvals ({cols}) values ({placeholders}) "
            "on conflict (job_id, params_hash) do nothing returning *",
            values,
        )
        if rows:
            return _row_to_approval(rows[0])
        existing = self._query(
            "select * from public.approvals where job_id = %s "
            "and params_hash = %s and state = 'pending'",
            (approval.job_id, approval.params_hash),
        )
        if existing:
            return _row_to_approval(existing[0])
        # The (job_id, params_hash) row exists but is no longer
        # pending: the durable schema keeps one row per job+action, so
        # re-preparing a decided action is refused loudly rather than
        # resurrecting or duplicating it.
        raise RuntimeError(
            "an approval for this job and action already exists and "
            "is no longer pending; durable storage does not re-prepare "
            "decided actions"
        )

    def get(self, approval_id: str, session_id: str) -> Optional[Approval]:
        rows = self._query(
            "select * from public.approvals "
            "where approval_id = %s and session_id = %s",
            (approval_id, session_id),
        )
        if not rows:
            return None
        approval = _row_to_approval(rows[0])
        if (
            approval.state == ApprovalState.PENDING
            and time.time() >= approval.expires_at
        ):
            self._query(
                "update public.approvals set state = 'expired' "
                "where approval_id = %s and state = 'pending'",
                (approval_id,),
                fetch=False,
            )
            approval.state = ApprovalState.EXPIRED
        return approval

    def list_pending(self, session_id: str) -> List[Approval]:
        rows = self._query(
            "select * from public.approvals where session_id = %s "
            "and state = 'pending' order by created_at asc",
            (session_id,),
        )
        out = []
        for row in rows:
            a = _row_to_approval(row)
            if time.time() < a.expires_at:
                out.append(a)
        return out

    def decide(
        self, approval_id: str, session_id: str, approve: bool,
        reason: Optional[str] = None,
    ) -> Optional[Approval]:
        current = self.get(approval_id, session_id)
        if current is None:
            return None
        if current.state != ApprovalState.PENDING or time.time() >= current.expires_at:
            return None
        rows = self._query(
            "update public.approvals set state = %s, decided_at = %s, "
            "decided_by = %s, decision_reason = %s "
            "where approval_id = %s and session_id = %s and state = 'pending' "
            "returning *",
            (
                ApprovalState.APPROVED.value if approve
                else ApprovalState.REJECTED.value,
                _ts(time.time()),
                session_id,
                reason[:500] if reason else None,
                approval_id,
                session_id,
            ),
        )
        return _row_to_approval(rows[0]) if rows else None

    def _sql_rpc(self, fn_name: str, params: tuple) -> List[Dict[str, Any]]:
        placeholders = ", ".join(["%s"] * len(params))
        rows = self._query(f"select * from {fn_name}({placeholders})", params)
        # A PL/pgSQL function returning a NULL composite surfaces via
        # SELECT * as one all-NULL row, not zero rows. Drop those so
        # "no row" means the same thing as over PostgREST.
        return [r for r in rows if r.get("approval_id") is not None]

    def claim_for_execution(
        self, approval_id: str, session_id: str, job_id: str,
        action_type: str, params: Dict[str, Any],
    ) -> Optional[Approval]:
        import secrets as _secrets

        execution_id = _secrets.token_urlsafe(16)
        rows = self._sql_rpc(
            "claim_approval_for_execution",
            (
                approval_id,
                session_id,
                job_id,
                idempotency_key(action_type, params),
                execution_id,
            ),
        )
        if not rows:
            return None
        claimed = _row_to_approval(rows[0])
        if claimed.execution_id != execution_id:
            return None
        return claimed

    def record_execution_result(
        self, approval_id: str, session_id: str, execution_id: str,
        succeeded: bool, evidence: Optional[str] = None,
    ) -> Optional[Approval]:
        rows = self._sql_rpc(
            "record_approval_execution_result",
            (
                approval_id,
                session_id,
                execution_id,
                succeeded,
                (evidence or "")[:500],
            ),
        )
        return _row_to_approval(rows[0]) if rows else None

    def reconcile_abandoned(self, max_age_s: float = 300) -> List[Approval]:
        rows = self._sql_rpc(
            "reconcile_abandoned_approvals", (int(max_age_s),)
        )
        return [_row_to_approval(r) for r in rows]

    def cancel_for_job(self, job_id: str, session_id: str) -> int:
        return self._query(
            "update public.approvals set state = 'cancelled', "
            "decided_at = now(), decided_by = %s "
            "where job_id = %s and session_id = %s and state = 'pending'",
            (session_id, job_id, session_id),
            fetch=False,
        )


def build_approval_store() -> Any:
    """Factory: durable store when configured, else the shared
    in-memory ApprovalService singleton.

    Selection, in order:
    - ETHIO_TASK_STORE=pg (or ETHIO_APPROVAL_STORE=pg): PgApprovalStore
      against ETHIO_PG_DSN — local Postgres, no Supabase credentials.
    - ETHIO_TASK_STORE=supabase or ETHIO_USE_SUPABASE=1:
      SupabaseApprovalStore; requires SUPABASE_URL +
      SUPABASE_SERVICE_KEY. (The task-store switch implies the
      approval switch: durable jobs with in-memory approvals would
      silently split the durability the operator asked for — the
      Phase 12 live smoke caught exactly that split.)
    Fail-fast: a requested durable mode with missing configuration
    raises — the gateway must never silently claim durable storage
    while actually using memory.
    """
    if os.environ.get("ETHIO_APPROVAL_STORE") == "pg" or (
        os.environ.get("ETHIO_TASK_STORE") == "pg"
        and os.environ.get("ETHIO_APPROVAL_STORE", "") == ""
    ):
        dsn = os.environ.get("ETHIO_PG_DSN", "")
        if not dsn:
            raise RuntimeError(
                "PG approval storage requested but ETHIO_PG_DSN is missing"
            )
        return PgApprovalStore(dsn)
    if os.environ.get("ETHIO_USE_SUPABASE") == "1" or (
        os.environ.get("ETHIO_TASK_STORE") == "supabase"
        and os.environ.get("ETHIO_APPROVAL_STORE", "") == ""
    ):
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            raise RuntimeError(
                "Supabase approval storage requested (ETHIO_TASK_STORE="
                "supabase or ETHIO_USE_SUPABASE=1) but SUPABASE_URL or "
                "SUPABASE_SERVICE_KEY is missing"
            )
        return SupabaseApprovalStore(url, key)
    from approvals import APPROVALS

    return APPROVALS

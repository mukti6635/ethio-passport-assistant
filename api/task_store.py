"""Durable task (agent job) persistence — Phase 5.

The gateway keeps live job objects (with browser handles) in memory;
this layer mirrors their durable state to a store so tasks, pending
approvals, and verified outcomes survive an API restart.

Stores:
- MemoryTaskStore (default): process-local dict. Local development
  only — a restart loses everything, by design and documented as such.
- PgTaskStore: direct PostgreSQL via psycopg2, calling the migration
  005 RPCs. For local development/testing against a real Postgres
  (e.g. pgserver) without any Supabase credentials.
- SupabaseTaskStore: the same RPCs via PostgREST with the service-role
  key (server-side only, never shipped to clients).

Safety rules enforced here and in SQL (migration 005):
- State changes go through a compare-and-swap transition whose map
  mirrors the gateway's VALID_TRANSITIONS.
- 'succeeded' requires a non-empty verified final_result.
- One active job per (owner, session): the database raises
  unique_violation; stores surface it as DuplicateActiveJob.
- Stale 'queued'/'running' jobs reconcile to 'failed' (interrupted) —
  never to success, never auto-retried. Human-paced waiting states
  are not reconciled.
- Durable modes fail fast: missing DSN/credentials raise, and durable
  storage refuses to run with the dev-key auth mode (a shared key is
  not per-user authentication).

Records are plain dicts with epoch-float timestamps:
  job_id, owner_key, session_id, goal, inputs, state, log, checkpoint,
  final_result, error, evidence, runner, created_at, started_at,
  ended_at
"""

import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

ACTIVE_STATES = {
    "queued", "running", "paused", "awaiting_human",
    "waiting_approval", "waiting_input",
}
TERMINAL_STATES = {"succeeded", "completed", "failed", "cancelled", "timed_out"}

# Mirror of the gateway's VALID_TRANSITIONS and of the CASE map in
# migration 005's transition_agent_job. The SQL is the final arbiter
# for durable stores; this map serves the memory store and fast-fail
# validation.
TRANSITIONS: Dict[str, set] = {
    "queued": {"running", "cancelled", "failed"},
    "running": {
        "paused", "awaiting_human", "waiting_approval", "waiting_input",
        "succeeded", "completed", "failed", "cancelled", "timed_out",
    },
    "paused": {"running", "cancelled", "failed"},
    "awaiting_human": {"running", "cancelled", "failed"},
    "waiting_approval": {"running", "cancelled", "failed"},
    "waiting_input": {"running", "cancelled", "failed"},
}


class TaskStoreError(Exception):
    pass


class DuplicateActiveJob(TaskStoreError):
    """An active job already exists for this (owner, session)."""


class InvalidTransition(TaskStoreError):
    """The requested state transition is not in the allowed map."""


def _validate_transition(from_state: str, to_state: str, patch: Dict[str, Any]) -> None:
    if to_state not in TRANSITIONS.get(from_state, set()):
        raise InvalidTransition(f"invalid state transition: {from_state} -> {to_state}")
    if to_state in ("succeeded", "completed") and not str(
        patch.get("final_result") or ""
    ).strip():
        raise InvalidTransition(
            "refusing to mark a job succeeded without a verified final_result"
        )


def _norm_job_id(job_id: str) -> str:
    """Gateway job ids are uuid hex (no dashes); DB rows come back
    dashed. Normalize to the gateway's hex form."""
    return job_id.replace("-", "")


def _uuid_str(value: str) -> str:
    return str(uuid.UUID(value))


class TaskStore(ABC):
    durable = False

    @abstractmethod
    def create(self, record: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    def get(self, job_id: str, owner_key: str) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def list_for_owner(self, owner_key: str) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    def list_active(self) -> List[Dict[str, Any]]:
        """All non-terminal records across owners (startup restore)."""

    @abstractmethod
    def transition(
        self, job_id: str, owner_key: str, from_state: str, to_state: str,
        patch: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """CAS transition. Returns the updated record, or None when the
        row is not in from_state / not owned. Raises InvalidTransition
        for transitions outside the allowed map."""

    @abstractmethod
    def update_snapshot(self, record: Dict[str, Any]) -> None:
        """Sync mutable fields (log, checkpoint, error, evidence,
        timestamps) for a row whose state is unchanged. Never changes
        state and never resurrects a terminal row."""

    @abstractmethod
    def reconcile_stale(self, stale_seconds: float) -> List[Dict[str, Any]]:
        """Fail stale queued/running jobs (interrupted). Returns them."""


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------


class MemoryTaskStore(TaskStore):
    durable = False

    def __init__(self) -> None:
        self._rows: Dict[str, Dict[str, Any]] = {}

    def _key(self, job_id: str, owner_key: str) -> str:
        return f"{owner_key}:{_norm_job_id(job_id)}"

    def create(self, record: Dict[str, Any]) -> Dict[str, Any]:
        for row in self._rows.values():
            if (
                row["owner_key"] == record["owner_key"]
                and row["session_id"] == record["session_id"]
                and row["state"] in ACTIVE_STATES
            ):
                raise DuplicateActiveJob(
                    f"session already has active job {row['job_id']}"
                )
        row = dict(record)
        self._rows[self._key(row["job_id"], row["owner_key"])] = row
        return dict(row)

    def get(self, job_id: str, owner_key: str) -> Optional[Dict[str, Any]]:
        row = self._rows.get(self._key(job_id, owner_key))
        return dict(row) if row else None

    def list_for_owner(self, owner_key: str) -> List[Dict[str, Any]]:
        return [
            dict(r) for r in self._rows.values() if r["owner_key"] == owner_key
        ]

    def list_active(self) -> List[Dict[str, Any]]:
        return [
            dict(r) for r in self._rows.values() if r["state"] in ACTIVE_STATES
        ]

    def transition(self, job_id, owner_key, from_state, to_state, patch=None):
        patch = dict(patch or {})
        _validate_transition(from_state, to_state, patch)
        row = self._rows.get(self._key(job_id, owner_key))
        if row is None or row["state"] != from_state:
            return None
        row["state"] = to_state
        for key in ("checkpoint", "final_result", "error", "evidence"):
            if key in patch:
                row[key] = patch[key]
        if patch.get("log_entry"):
            row["log"] = list(row["log"]) + [patch["log_entry"]]
        if to_state == "running" and row.get("started_at") is None:
            row["started_at"] = time.time()
        if to_state in TERMINAL_STATES:
            row["ended_at"] = time.time()
        return dict(row)

    def update_snapshot(self, record: Dict[str, Any]) -> None:
        row = self._rows.get(self._key(record["job_id"], record["owner_key"]))
        if row is None or row["state"] != record["state"]:
            return
        for key in (
            "log", "checkpoint", "final_result", "error", "evidence",
            "started_at", "ended_at",
        ):
            row[key] = record.get(key)

    def reconcile_stale(self, stale_seconds: float) -> List[Dict[str, Any]]:
        return []  # nothing survives a restart in memory mode anyway


# ---------------------------------------------------------------------------
# Shared row conversion for database stores
# ---------------------------------------------------------------------------


def _epoch(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        from datetime import datetime

        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    # datetime from psycopg2
    return value.timestamp()


def _row_to_record(row: Dict[str, Any], owner_key: str) -> Dict[str, Any]:
    inputs = row.get("inputs") or {}
    if isinstance(inputs, str):
        inputs = json.loads(inputs)
    log = row.get("log") or []
    if isinstance(log, str):
        log = json.loads(log)
    return {
        "job_id": _norm_job_id(str(row["id"])),
        "owner_key": owner_key,
        "session_id": row.get("session_id") or owner_key,
        "goal": row.get("goal") or "",
        "inputs": dict(inputs),
        "state": row.get("state") or "queued",
        "log": list(log),
        "checkpoint": row.get("checkpoint"),
        "final_result": row.get("final_result"),
        "error": row.get("error"),
        "evidence": row.get("evidence"),
        "runner": row.get("runner") or "agent",
        "created_at": _epoch(row.get("created_at")) or time.time(),
        "started_at": _epoch(row.get("started_at")),
        "ended_at": _epoch(row.get("ended_at")),
    }


# ---------------------------------------------------------------------------
# Direct PostgreSQL store (local development / tests)
# ---------------------------------------------------------------------------


class PgTaskStore(TaskStore):
    durable = True

    def __init__(self, dsn: str):
        self._dsn = dsn

    def _connect(self):
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(self._dsn)
        conn.autocommit = True
        return conn

    def _call(self, sql: str, params: tuple) -> List[Dict[str, Any]]:
        import psycopg2
        import psycopg2.extras

        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def create(self, record: Dict[str, Any]) -> Dict[str, Any]:
        import psycopg2

        try:
            rows = self._call(
                "select * from create_agent_job(%s::uuid, %s::uuid, %s, %s, %s::jsonb, %s)",
                (
                    _uuid_str(record["job_id"]),
                    _uuid_str(record["owner_key"]),
                    record["session_id"],
                    record["goal"],
                    json.dumps(record.get("inputs") or {}),
                    record.get("runner") or "agent",
                ),
            )
        except psycopg2.errors.UniqueViolation:
            raise DuplicateActiveJob(
                "an active job already exists for this session"
            )
        return _row_to_record(rows[0], record["owner_key"])

    def get(self, job_id: str, owner_key: str) -> Optional[Dict[str, Any]]:
        rows = self._call(
            "select * from get_agent_job(%s::uuid, %s::uuid)",
            (_uuid_str(job_id), _uuid_str(owner_key)),
        )
        # A NULL composite return surfaces as one all-NULL row.
        rows = [r for r in rows if r.get("id") is not None]
        return _row_to_record(rows[0], owner_key) if rows else None

    def list_for_owner(self, owner_key: str) -> List[Dict[str, Any]]:
        rows = self._call(
            "select * from list_agent_jobs(%s::uuid)",
            (_uuid_str(owner_key),),
        )
        return [_row_to_record(r, owner_key) for r in rows]

    def list_active(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            import psycopg2.extras

            with conn.cursor(
                cursor_factory=psycopg2.extras.RealDictCursor
            ) as cur:
                cur.execute(
                    "select * from public.agent_jobs "
                    "where state = any(%s) order by created_at asc",
                    (sorted(ACTIVE_STATES),),
                )
                rows = [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
        return [_row_to_record(r, str(r["owner_id"])) for r in rows]

    def transition(self, job_id, owner_key, from_state, to_state, patch=None):
        import psycopg2

        patch = dict(patch or {})
        _validate_transition(from_state, to_state, patch)
        sql_patch = {
            k: patch[k]
            for k in ("checkpoint", "final_result", "error", "evidence", "log_entry")
            if k in patch
        }
        try:
            rows = self._call(
                "select * from transition_agent_job(%s::uuid, %s::uuid, %s, %s, %s::jsonb)",
                (
                    _uuid_str(job_id),
                    _uuid_str(owner_key),
                    from_state,
                    to_state,
                    json.dumps(sql_patch),
                ),
            )
        except psycopg2.errors.CheckViolation as e:
            raise InvalidTransition(str(e).strip())
        # A lost CAS returns a NULL composite = one all-NULL row.
        rows = [r for r in rows if r.get("id") is not None]
        return _row_to_record(rows[0], owner_key) if rows else None

    def update_snapshot(self, record: Dict[str, Any]) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update public.agent_jobs
                    set log = %s::jsonb, checkpoint = %s,
                        final_result = %s, error = %s, evidence = %s::jsonb,
                        started_at = to_timestamp(%s),
                        ended_at = to_timestamp(%s)
                    where id = %s::uuid and owner_id = %s::uuid
                      and state = %s
                    """,
                    (
                        json.dumps(record.get("log") or []),
                        record.get("checkpoint"),
                        record.get("final_result"),
                        record.get("error"),
                        json.dumps(record.get("evidence"))
                        if record.get("evidence") is not None else None,
                        record.get("started_at"),
                        record.get("ended_at"),
                        _uuid_str(record["job_id"]),
                        _uuid_str(record["owner_key"]),
                        record["state"],
                    ),
                )
        finally:
            conn.close()

    def reconcile_stale(self, stale_seconds: float) -> List[Dict[str, Any]]:
        rows = self._call(
            "select * from reconcile_stale_agent_jobs(%s)",
            (int(stale_seconds),),
        )
        return [
            _row_to_record(r, str(r["owner_id"])) for r in rows
        ]


# ---------------------------------------------------------------------------
# Supabase store (PostgREST RPC; service-role key, server-side only)
# ---------------------------------------------------------------------------


def _supabase_client(base_url: str, timeout: float = 15.0):
    """httpx client for Supabase endpoints.

    Honors an egress proxy (HTTPS_PROXY/https_proxy) and a custom CA
    bundle (SSL_CERT_FILE) from the environment. Plain
    ``trust_env=False`` silently ignores both, which makes the store
    unreachable from any network that requires a proxy (this sandbox
    included — its no_proxy is also malformed for httpx's parser, so
    the proxy is wired explicitly rather than via trust_env).
    Loopback targets are never proxied, keeping local PostgREST
    stubs in tests direct.
    """
    import httpx
    from urllib.parse import urlparse

    host = urlparse(base_url).hostname or ""
    proxy = None
    if host not in ("localhost", "127.0.0.1", "::1"):
        proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or None
        )
    verify = os.environ.get("SSL_CERT_FILE") or True
    return httpx.Client(
        trust_env=False, proxy=proxy, verify=verify, timeout=timeout
    )


class SupabaseTaskStore(TaskStore):
    durable = True

    def __init__(self, url: str, service_key: str):
        self._url = url.rstrip("/")
        self._key = service_key

    def _headers(self) -> Dict[str, str]:
        return {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

    def _rpc(self, fn_name: str, body: Dict[str, Any]) -> List[Dict[str, Any]]:
        import httpx

        with _supabase_client(self._url) as client:
            r = client.post(
                f"{self._url}/rest/v1/rpc/{fn_name}",
                headers=self._headers(),
                json=body,
            )
        if r.status_code >= 400:
            code = ""
            try:
                code = str(r.json().get("code") or "")
            except Exception:
                pass
            if code == "23505":
                raise DuplicateActiveJob(
                    "an active job already exists for this session"
                )
            if code == "23514":
                raise InvalidTransition(f"RPC {fn_name}: transition rejected")
            raise RuntimeError(
                f"RPC {fn_name} failed: HTTP {r.status_code}. Apply "
                "migrations 003 + 005 before enabling durable storage."
            )
        data = r.json()
        return data if isinstance(data, list) else [data]

    def create(self, record: Dict[str, Any]) -> Dict[str, Any]:
        rows = self._rpc(
            "create_agent_job",
            {
                "p_id": _uuid_str(record["job_id"]),
                "p_owner_id": _uuid_str(record["owner_key"]),
                "p_session_id": record["session_id"],
                "p_goal": record["goal"],
                "p_inputs": record.get("inputs") or {},
                "p_runner": record.get("runner") or "agent",
            },
        )
        return _row_to_record(rows[0], record["owner_key"])

    def get(self, job_id: str, owner_key: str) -> Optional[Dict[str, Any]]:
        rows = self._rpc(
            "get_agent_job",
            {"p_id": _uuid_str(job_id), "p_owner_id": _uuid_str(owner_key)},
        )
        rows = [r for r in rows if r]
        return _row_to_record(rows[0], owner_key) if rows else None

    def list_for_owner(self, owner_key: str) -> List[Dict[str, Any]]:
        rows = self._rpc("list_agent_jobs", {"p_owner_id": _uuid_str(owner_key)})
        return [_row_to_record(r, owner_key) for r in rows if r]

    def list_active(self) -> List[Dict[str, Any]]:
        import httpx

        states = ",".join(sorted(ACTIVE_STATES))
        with _supabase_client(self._url) as client:
            r = client.get(
                f"{self._url}/rest/v1/agent_jobs",
                headers=self._headers(),
                params={"state": f"in.({states})", "select": "*",
                        "order": "created_at.asc"},
            )
        if r.status_code >= 400:
            raise RuntimeError(
                f"agent_jobs list_active failed: HTTP {r.status_code}"
            )
        return [
            _row_to_record(row, str(row["owner_id"])) for row in r.json()
        ]

    def transition(self, job_id, owner_key, from_state, to_state, patch=None):
        patch = dict(patch or {})
        _validate_transition(from_state, to_state, patch)
        sql_patch = {
            k: patch[k]
            for k in ("checkpoint", "final_result", "error", "evidence", "log_entry")
            if k in patch
        }
        rows = self._rpc(
            "transition_agent_job",
            {
                "p_id": _uuid_str(job_id),
                "p_owner_id": _uuid_str(owner_key),
                "p_from_state": from_state,
                "p_to_state": to_state,
                "p_patch": sql_patch,
            },
        )
        rows = [r for r in rows if r]
        return _row_to_record(rows[0], owner_key) if rows else None

    def update_snapshot(self, record: Dict[str, Any]) -> None:
        import httpx

        def _ts(epoch: Optional[float]) -> Optional[str]:
            if epoch is None:
                return None
            from datetime import datetime, timezone

            return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()

        patch = {
            "log": record.get("log") or [],
            "checkpoint": record.get("checkpoint"),
            "final_result": record.get("final_result"),
            "error": record.get("error"),
            "evidence": record.get("evidence"),
            "started_at": _ts(record.get("started_at")),
            "ended_at": _ts(record.get("ended_at")),
        }
        with _supabase_client(self._url) as client:
            r = client.patch(
                f"{self._url}/rest/v1/agent_jobs",
                headers=self._headers(),
                params={
                    "id": f"eq.{_uuid_str(record['job_id'])}",
                    "owner_id": f"eq.{_uuid_str(record['owner_key'])}",
                    # State equality guard: a snapshot never changes
                    # state and never touches a row whose state moved on.
                    "state": f"eq.{record['state']}",
                },
                json=patch,
            )
        if r.status_code >= 400:
            raise RuntimeError(
                f"agent_jobs snapshot update failed: HTTP {r.status_code}"
            )

    def reconcile_stale(self, stale_seconds: float) -> List[Dict[str, Any]]:
        rows = self._rpc(
            "reconcile_stale_agent_jobs",
            {"p_stale_seconds": int(stale_seconds)},
        )
        return [
            _row_to_record(r, str(r["owner_id"])) for r in rows if r
        ]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_task_store() -> TaskStore:
    """Select the task store from the environment. Fail-fast rules:

    - ETHIO_TASK_STORE=pg requires ETHIO_PG_DSN.
    - ETHIO_TASK_STORE=supabase (or ETHIO_USE_SUPABASE=1) requires
      SUPABASE_URL + SUPABASE_SERVICE_KEY.
    - Any durable store requires ETHIO_AUTH_MODE=jwt: durable per-user
      data must never sit behind the shared dev key.
    - No configuration silently falls back to memory when durability
      was requested.
    """
    mode = os.environ.get("ETHIO_TASK_STORE", "").strip().lower()
    if not mode and os.environ.get("ETHIO_USE_SUPABASE") == "1":
        mode = "supabase"
    if mode in ("", "memory"):
        return MemoryTaskStore()
    if mode not in ("pg", "supabase"):
        raise RuntimeError(f"unknown ETHIO_TASK_STORE value: {mode!r}")
    if os.environ.get("ETHIO_AUTH_MODE", "devkey") != "jwt":
        raise RuntimeError(
            "durable task storage (ETHIO_TASK_STORE="
            f"{mode}) requires ETHIO_AUTH_MODE=jwt: per-user data must "
            "not sit behind the shared development API key"
        )
    if mode == "pg":
        dsn = os.environ.get("ETHIO_PG_DSN", "")
        if not dsn:
            raise RuntimeError(
                "ETHIO_TASK_STORE=pg but ETHIO_PG_DSN is missing"
            )
        return PgTaskStore(dsn)
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "durable task storage requires SUPABASE_URL and "
            "SUPABASE_SERVICE_KEY"
        )
    return SupabaseTaskStore(url, key)

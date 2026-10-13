"""Phase 5 per-user authentication tests (Supabase JWT mode).

The gateway verifies Supabase-issued access tokens itself: HS256 with
the project JWT secret, ES256 against the project JWKS. These tests
mint tokens locally (stdlib + cryptography) — no Supabase account, no
network. They verify:
  - a valid token authenticates; identity comes from `sub`
  - missing / malformed / expired / wrong-audience / bad-signature
    tokens are rejected (401)
  - an alg=none token is rejected
  - ES256 via a locally generated JWKS works; tampering fails
  - cross-user isolation: user B cannot see, decide, or execute
    user A's jobs and approvals
  - /health stays public and secret-free
  - durable storage refuses the dev-key mode (fail-fast factory)

Run: ~/workspace/ethio-live-venv/bin/python -m pytest api/test_auth.py -q
"""

import asyncio
import base64
import hashlib
import hmac
import importlib
import json
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

TEST_SECRET = "test-jwt-secret-do-not-use-in-production"
USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint_hs256(sub=USER_A, secret=TEST_SECRET, exp_delta=3600, aud="authenticated",
               extra=None):
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {
        "sub": sub,
        "aud": aud,
        "iss": "https://example.supabase.co/auth/v1",
        "iat": int(time.time()),
        "exp": int(time.time()) + exp_delta,
        "role": "authenticated",
    }
    if extra:
        claims.update(extra)
    signing = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    sig = hmac.new(secret.encode(), signing.encode(), hashlib.sha256).digest()
    return f"{signing}.{_b64(sig)}"


class _FakeHistory:
    def is_successful(self):
        return False

    def final_result(self):
        return None


class _FakeAgent:
    """Blocks forever so the job stays RUNNING during the test."""

    _ethio_max_steps = 1

    def __init__(self):
        self._evt = asyncio.Event()

    async def run(self, max_steps=None):
        await self._evt.wait()
        return _FakeHistory()

    def pause(self):
        pass

    def resume(self):
        pass

    def stop(self):
        self._evt.set()


@pytest.fixture()
def jwt_client(monkeypatch):
    monkeypatch.setenv("ETHIO_AUTH_MODE", "jwt")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("ETHIO_JWT_JWKS_JSON", raising=False)
    monkeypatch.delenv("ETHIO_TASK_STORE", raising=False)
    monkeypatch.delenv("ETHIO_USE_SUPABASE", raising=False)
    import gateway

    importlib.reload(gateway)
    gateway._build_agent = lambda job, cb: _FakeAgent()
    from fastapi.testclient import TestClient

    return TestClient(gateway.app), gateway


def auth_headers(token, session="client-session-1"):
    return {"Authorization": f"Bearer {token}", "X-Ethio-Session": session}


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------


def test_auth_01_valid_token_authenticates(jwt_client):
    client, _ = jwt_client
    r = client.get("/approvals/pending", headers=auth_headers(mint_hs256()))
    assert r.status_code == 200
    assert r.json() == {"approvals": []}


def test_auth_02_missing_and_malformed_tokens_rejected(jwt_client):
    client, _ = jwt_client
    assert client.get("/approvals/pending").status_code == 401
    assert client.get(
        "/approvals/pending", headers={"Authorization": "Bearer not-a-jwt"}
    ).status_code == 401
    assert client.get(
        "/approvals/pending", headers={"Authorization": "Basic abc"}
    ).status_code == 401


def test_auth_03_expired_wrong_secret_wrong_audience_rejected(jwt_client):
    client, _ = jwt_client
    expired = mint_hs256(exp_delta=-60)
    assert client.get(
        "/approvals/pending", headers=auth_headers(expired)
    ).status_code == 401
    wrong_secret = mint_hs256(secret="a-different-secret")
    assert client.get(
        "/approvals/pending", headers=auth_headers(wrong_secret)
    ).status_code == 401
    wrong_aud = mint_hs256(aud="anon")
    assert client.get(
        "/approvals/pending", headers=auth_headers(wrong_aud)
    ).status_code == 401
    no_sub = mint_hs256(extra={"sub": ""})
    assert client.get(
        "/approvals/pending", headers=auth_headers(no_sub)
    ).status_code == 401


def test_auth_04_alg_none_rejected(jwt_client):
    client, _ = jwt_client
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({
        "sub": USER_A, "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }).encode())
    token = f"{header}.{claims}."
    assert client.get(
        "/approvals/pending", headers=auth_headers(token)
    ).status_code == 401


def test_auth_05_health_is_public(jwt_client):
    client, _ = jwt_client
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ---------------------------------------------------------------------------
# ES256 via JWKS
# ---------------------------------------------------------------------------


def _es256_keypair_and_jwks():
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    numbers = key.public_key().public_numbers()
    kid = "test-key-1"
    jwks = {
        "keys": [{
            "kty": "EC",
            "crv": "P-256",
            "kid": kid,
            "x": _b64(numbers.x.to_bytes(32, "big")),
            "y": _b64(numbers.y.to_bytes(32, "big")),
        }]
    }
    return key, kid, jwks


def _mint_es256(key, kid, sub=USER_A, exp_delta=3600):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import (
        decode_dss_signature,
    )

    header = {"alg": "ES256", "typ": "JWT", "kid": kid}
    claims = {
        "sub": sub, "aud": "authenticated",
        "iat": int(time.time()), "exp": int(time.time()) + exp_delta,
    }
    signing = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    der = key.sign(signing.encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{signing}.{_b64(raw)}"


def test_auth_06_es256_jwks(jwt_client, monkeypatch):
    client, _ = jwt_client
    key, kid, jwks = _es256_keypair_and_jwks()
    monkeypatch.setenv("ETHIO_JWT_JWKS_JSON", json.dumps(jwks))
    token = _mint_es256(key, kid)
    r = client.get("/approvals/pending", headers=auth_headers(token))
    assert r.status_code == 200
    # Tamper with the payload: signature no longer matches.
    head, _, sig = token.split(".")
    forged_claims = _b64(json.dumps({
        "sub": USER_B, "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }).encode())
    forged = f"{head}.{forged_claims}.{sig}"
    assert client.get(
        "/approvals/pending", headers=auth_headers(forged)
    ).status_code == 401


# ---------------------------------------------------------------------------
# Cross-user isolation (identity from the token, never the client)
# ---------------------------------------------------------------------------


def test_auth_07_cross_user_isolation(jwt_client):
    client, _ = jwt_client
    tok_a = mint_hs256(sub=USER_A)
    tok_b = mint_hs256(sub=USER_B)
    # A starts a job. The body session_id is a client label in JWT
    # mode; ownership comes from the token.
    r = client.post(
        "/tasks",
        json={"goal": "do the thing", "inputs": {}, "session_id": "anything"},
        headers=auth_headers(tok_a),
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    # B cannot see A's job; A can.
    assert client.get(
        f"/tasks/status/{job_id}", headers=auth_headers(tok_b)
    ).status_code == 404
    assert client.get(
        f"/tasks/status/{job_id}", headers=auth_headers(tok_a)
    ).status_code == 200
    # A prepares an approval; B cannot see, decide, or execute it.
    r = client.post(
        "/approvals",
        json={
            "job_id": job_id, "action_type": "payment",
            "action_label": "Pay", "consequence": "charge",
            "params": {"amount": "200"}, "params_summary": {},
        },
        headers=auth_headers(tok_a),
    )
    assert r.status_code == 201, r.text
    approval_id = r.json()["approval_id"]
    assert client.get(
        "/approvals/pending", headers=auth_headers(tok_b)
    ).json() == {"approvals": []}
    assert client.post(
        f"/approvals/{approval_id}/decide",
        json={"approve": True},
        headers=auth_headers(tok_b),
    ).status_code == 409
    # A decides; B still cannot execute against A's job.
    assert client.post(
        f"/approvals/{approval_id}/decide",
        json={"approve": True},
        headers=auth_headers(tok_a),
    ).status_code == 200
    assert client.post(
        f"/approvals/{approval_id}/execute",
        json={"job_id": job_id, "action_type": "payment",
              "params": {"amount": "200"}},
        headers=auth_headers(tok_b),
    ).status_code == 404
    # Cleanup: cancel A's job.
    client.post(
        f"/tasks/cancel/{job_id}", json={}, headers=auth_headers(tok_a)
    )


# ---------------------------------------------------------------------------
# Fail-fast configuration rules
# ---------------------------------------------------------------------------


def test_auth_08_durable_store_refuses_devkey(monkeypatch):
    monkeypatch.delenv("ETHIO_AUTH_MODE", raising=False)
    monkeypatch.setenv("ETHIO_TASK_STORE", "pg")
    monkeypatch.setenv("ETHIO_PG_DSN", "postgresql://unused")
    from task_store import build_task_store

    with pytest.raises(RuntimeError, match="ETHIO_AUTH_MODE=jwt"):
        build_task_store()


def test_auth_09_durable_store_requires_dsn(monkeypatch):
    monkeypatch.setenv("ETHIO_AUTH_MODE", "jwt")
    monkeypatch.setenv("ETHIO_TASK_STORE", "pg")
    monkeypatch.delenv("ETHIO_PG_DSN", raising=False)
    from task_store import build_task_store

    with pytest.raises(RuntimeError, match="ETHIO_PG_DSN"):
        build_task_store()


# ---------------------------------------------------------------------------
# JWKS-only deployment (ES256 project, no shared secret) — Phase 12
#
# Regression: _require_jwt keyed its 500 "misconfigured" branch off the
# TOKEN's alg, which is attacker-controlled. On a JWKS-only deployment
# (e.g. the live ethio project, whose JWKS is a single ES256 key) every
# forged HS256 or garbled token therefore produced a 500 instead of a
# 401. Misconfiguration is a property of the deployment: 500 only when
# NO verification material is configured at all.
# ---------------------------------------------------------------------------


def test_auth_10_jwks_only_deployment_token_handling(monkeypatch):
    key, kid, jwks = _es256_keypair_and_jwks()
    monkeypatch.setenv("ETHIO_AUTH_MODE", "jwt")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("ETHIO_JWT_JWKS_JSON", json.dumps(jwks))
    monkeypatch.delenv("ETHIO_TASK_STORE", raising=False)
    monkeypatch.delenv("ETHIO_USE_SUPABASE", raising=False)
    import gateway

    importlib.reload(gateway)
    gateway._build_agent = lambda job, cb: _FakeAgent()
    from fastapi.testclient import TestClient

    client = TestClient(gateway.app, raise_server_exceptions=False)
    url = "/approvals/pending"
    # A genuine ES256 token from the configured JWKS still works.
    good = _mint_es256(key, kid)
    assert client.get(url, headers=auth_headers(good)).status_code == 200
    # Forged HS256 (attacker-chosen alg, no secret on this deployment):
    # a client error, never a server error.
    assert client.get(
        url, headers=auth_headers(mint_hs256(secret="attacker-guess"))
    ).status_code == 401
    # Garbled and alg=none tokens likewise.
    assert client.get(
        url, headers={"Authorization": "Bearer garbage.token.here"}
    ).status_code == 401
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    claims = _b64(json.dumps({
        "sub": USER_A, "aud": "authenticated",
        "exp": int(time.time()) + 3600,
    }).encode())
    assert client.get(
        url, headers=auth_headers(f"{header}.{claims}.")
    ).status_code == 401
    # ES256 token from an UNKNOWN key: unknown kid -> 401.
    other_key, _, _ = _es256_keypair_and_jwks()
    unknown = _mint_es256(other_key, "no-such-kid")
    assert client.get(
        url, headers=auth_headers(unknown)
    ).status_code == 401


def test_auth_11_no_verification_material_is_misconfigured(monkeypatch):
    # No secret AND no JWKS source at all: a genuine deployment error,
    # reported as 500 regardless of what token arrives.
    monkeypatch.setenv("ETHIO_AUTH_MODE", "jwt")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("ETHIO_JWT_JWKS_JSON", raising=False)
    monkeypatch.delenv("ETHIO_TASK_STORE", raising=False)
    monkeypatch.delenv("ETHIO_USE_SUPABASE", raising=False)
    import gateway

    importlib.reload(gateway)
    from fastapi.testclient import TestClient

    client = TestClient(gateway.app, raise_server_exceptions=False)
    r = client.get(
        "/approvals/pending", headers=auth_headers(mint_hs256())
    )
    assert r.status_code == 500
    assert "misconfigured" in r.json()["detail"]

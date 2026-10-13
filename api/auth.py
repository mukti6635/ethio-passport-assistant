"""Per-user authentication for the ETHIO gateway (Phase 5).

Modes (ETHIO_AUTH_MODE):

- "devkey" (default; LOCAL DEVELOPMENT ONLY): shared GATEWAY_API_KEY
  bearer token + X-Ethio-Session header; the session id is the
  isolation key. Anyone holding the key can claim any session, so this
  mode is not acceptable beyond one developer's machine. Durable
  task-store modes refuse to start in devkey mode.

- "jwt" (pilot): Supabase-issued access tokens. The gateway verifies
  the token signature itself — HS256 with the project JWT secret, or
  ES256 against the project JWKS — then checks exp / aud / iss and
  derives the owner identity from the verified `sub` claim.
  Client-supplied user ids and session ids are never trusted for
  ownership in this mode.

No third-party JWT library is used: HS256 is stdlib HMAC; ES256 uses
the `cryptography` package when installed. Verification fails closed
on any anomaly: malformed token, unknown alg/kid, bad signature,
missing or expired exp, wrong audience or issuer, missing sub.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


class AuthError(Exception):
    """Any token problem. Always maps to HTTP 401 (never 500, never a
    partial identity)."""


@dataclass
class VerifiedIdentity:
    user_id: str
    claims: Dict[str, Any]


def _b64url_decode(segment: str) -> bytes:
    if not segment or any(c.isspace() for c in segment):
        raise AuthError("malformed token segment")
    pad = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + pad)
    except Exception:
        raise AuthError("malformed base64url segment")


def _b64url_json(segment: str) -> Dict[str, Any]:
    try:
        value = json.loads(_b64url_decode(segment))
    except AuthError:
        raise
    except Exception:
        raise AuthError("malformed JSON segment")
    if not isinstance(value, dict):
        raise AuthError("token segment is not a JSON object")
    return value


def _verify_hs256(signing_input: bytes, signature: bytes, secret: str) -> None:
    expected = hmac.new(
        secret.encode("utf-8"), signing_input, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, signature):
        raise AuthError("invalid token signature")


def _verify_es256(
    signing_input: bytes, signature: bytes, header: Dict[str, Any],
    jwks: Optional[Dict[str, Any]],
) -> None:
    if not jwks or "keys" not in jwks:
        raise AuthError("ES256 token but no JWKS configured")
    kid = header.get("kid")
    jwk = next(
        (k for k in jwks["keys"] if k.get("kid") == kid), None
    )
    if jwk is None or jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
        raise AuthError("unknown or unsupported signing key")
    if len(signature) != 64:
        raise AuthError("malformed ES256 signature")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import (
            encode_dss_signature,
        )
    except ImportError:
        raise AuthError("ES256 verification unavailable (cryptography missing)")
    try:
        x = int.from_bytes(_b64url_decode(jwk["x"]), "big")
        y = int.from_bytes(_b64url_decode(jwk["y"]), "big")
        public_key = ec.EllipticCurvePublicNumbers(
            x, y, ec.SECP256R1()
        ).public_key()
        r = int.from_bytes(signature[:32], "big")
        s = int.from_bytes(signature[32:], "big")
        public_key.verify(
            encode_dss_signature(r, s), signing_input, ec.ECDSA(hashes.SHA256())
        )
    except InvalidSignature:
        raise AuthError("invalid token signature")
    except AuthError:
        raise
    except Exception:
        raise AuthError("ES256 verification failed")


def verify_supabase_jwt(
    token: str,
    *,
    hs_secret: Optional[str] = None,
    jwks: Optional[Dict[str, Any]] = None,
    issuer: Optional[str] = None,
    now: Optional[float] = None,
    leeway_s: float = 5.0,
) -> VerifiedIdentity:
    """Verify a Supabase access token. Returns the verified identity
    (user id = `sub`) or raises AuthError. Pure function: all trust
    material is passed in, so tests exercise it without a network."""
    if not token or token.count(".") != 2:
        raise AuthError("malformed token")
    header_b64, payload_b64, signature_b64 = token.split(".")
    header = _b64url_json(header_b64)
    claims = _b64url_json(payload_b64)
    signature = _b64url_decode(signature_b64)
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")

    alg = header.get("alg")
    if alg == "HS256":
        if not hs_secret:
            raise AuthError("HS256 token but no JWT secret configured")
        _verify_hs256(signing_input, signature, hs_secret)
    elif alg == "ES256":
        _verify_es256(signing_input, signature, header, jwks)
    else:
        raise AuthError(f"unsupported alg: {alg!r}")

    now = time.time() if now is None else now
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or now > float(exp) + leeway_s:
        raise AuthError("token expired or missing exp")
    nbf = claims.get("nbf")
    if isinstance(nbf, (int, float)) and now + leeway_s < float(nbf):
        raise AuthError("token not yet valid")
    aud = claims.get("aud")
    if aud is not None:
        audiences = aud if isinstance(aud, list) else [aud]
        if "authenticated" not in audiences:
            raise AuthError("unexpected token audience")
    if issuer is not None and claims.get("iss") != issuer:
        raise AuthError("unexpected token issuer")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        raise AuthError("token has no subject")
    return VerifiedIdentity(user_id=sub, claims=claims)


def token_alg(token: str) -> Optional[str]:
    """The token's declared alg WITHOUT verifying anything. Used only
    to route verification (e.g. skip the JWKS fetch for HS256 tokens);
    never trust the result for an authorization decision."""
    try:
        if not token or token.count(".") != 2:
            return None
        return _b64url_json(token.split(".")[0]).get("alg")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# JWKS resolution for the gateway process (cached; network only here)
# ---------------------------------------------------------------------------

_JWKS_CACHE: Dict[str, Any] = {"jwks": None, "fetched_at": 0.0}
_JWKS_TTL_S = 600.0


def resolve_jwks() -> Optional[Dict[str, Any]]:
    """JWKS for ES256 verification, in priority order:

    1. ETHIO_JWT_JWKS_JSON — inline JWKS JSON (self-hosted Supabase or
       local tests; operator-supplied trust root, server-side only).
    2. Fetched from {SUPABASE_URL}/auth/v1/.well-known/jwks.json,
       cached for 10 minutes.
    Returns None when neither is available (ES256 tokens then fail
    closed; HS256 may still work if a secret is configured).
    """
    inline = os.environ.get("ETHIO_JWT_JWKS_JSON", "").strip()
    if inline:
        try:
            parsed = json.loads(inline)
            if isinstance(parsed, dict) and "keys" in parsed:
                return parsed
        except Exception:
            pass
        return None
    now = time.time()
    if _JWKS_CACHE["jwks"] is not None and now - _JWKS_CACHE["fetched_at"] < _JWKS_TTL_S:
        return _JWKS_CACHE["jwks"]
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    if not url:
        return None
    try:
        import httpx
        from urllib.parse import urlparse

        # Honor an egress proxy (HTTPS_PROXY/https_proxy) and a custom
        # CA bundle (SSL_CERT_FILE): plain trust_env=False ignores
        # both, which makes the JWKS endpoint unreachable from any
        # proxied network. Loopback targets are never proxied.
        host = urlparse(url).hostname or ""
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
        with httpx.Client(
            trust_env=False, proxy=proxy, verify=verify, timeout=5.0
        ) as client:
            r = client.get(f"{url}/auth/v1/.well-known/jwks.json")
        if r.status_code == 200:
            parsed = r.json()
            if isinstance(parsed, dict) and "keys" in parsed:
                _JWKS_CACHE["jwks"] = parsed
                _JWKS_CACHE["fetched_at"] = now
                return parsed
    except Exception:
        pass
    return None


def expected_issuer() -> Optional[str]:
    """Supabase issuer for the configured project, or None to skip the
    iss check (only when SUPABASE_URL is unset, e.g. HS256 local tests
    with a synthetic issuer — the signature is still fully verified)."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    return f"{url}/auth/v1" if url else None

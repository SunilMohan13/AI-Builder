"""HS256 JWT encode/decode and RBAC helpers.

Production should swap this module for OIDC validation without changing callers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Any

import jwt
from aeropulse_common.errors import AuthError
from aeropulse_common.settings import Settings, get_settings
from pydantic import BaseModel, Field


class Role(StrEnum):
    """Platform roles from LLD §35.1."""

    ADMIN = "ADMIN"
    SCIENTIST = "SCIENTIST"
    AUTHORITY = "AUTHORITY"
    OPERATOR = "OPERATOR"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"
    CITIZEN = "CITIZEN"


class TokenClaims(BaseModel):
    """Validated JWT claims."""

    sub: str
    roles: list[Role] = Field(default_factory=lambda: [Role.VIEWER])
    iss: str = "aeropulse"
    exp: datetime | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> TokenClaims:
        """Normalize raw JWT claims into the typed auth contract."""
        raw_roles = payload.get("roles")
        if raw_roles is None:
            raw_roles = payload.get("role")
        if isinstance(raw_roles, str):
            roles = [raw_roles]
        elif isinstance(raw_roles, list):
            roles = raw_roles
        else:
            roles = []

        resolved_roles: list[Role] = []
        for role in roles:
            try:
                resolved_roles.append(Role(str(role)))
            except ValueError:
                continue
        if not resolved_roles:
            resolved_roles = [Role.VIEWER]

        exp = payload.get("exp")
        exp_dt: datetime | None = None
        if isinstance(exp, (int, float)):
            exp_dt = datetime.fromtimestamp(exp, tz=UTC)
        elif isinstance(exp, str) and exp:
            try:
                exp_dt = datetime.fromtimestamp(float(exp), tz=UTC)
            except ValueError:
                exp_dt = None

        return cls(
            sub=str(payload.get("sub", "")),
            roles=resolved_roles,
            iss=str(payload.get("iss", "aeropulse")),
            exp=exp_dt,
        )


def encode_token(
    subject: str,
    roles: list[Role] | None = None,
    *,
    ttl_seconds: int = 3600,
    settings: Settings | None = None,
) -> str:
    """Mint a development HS256 JWT.

    Args:
        subject: User or service identifier.
        roles: Granted roles. Defaults to VIEWER.
        ttl_seconds: Token lifetime.
        settings: Optional settings override.

    Returns:
        Encoded JWT string.
    """
    cfg = settings or get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "roles": [r.value for r in (roles or [Role.VIEWER])],
        "iss": cfg.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(
        payload,
        cfg.jwt_secret.get_secret_value(),
        algorithm=cfg.jwt_algorithm,
    )


def decode_token(token: str, *, settings: Settings | None = None) -> TokenClaims:
    """Validate and decode a JWT.

    Args:
        token: Bearer token value (without the ``Bearer `` prefix).
        settings: Optional settings override.

    Returns:
        Parsed claims.

    Raises:
        AuthError: Token is missing, expired, or invalid.
    """
    if not token:
        raise AuthError("Missing bearer token", status_code=401)
    cfg = settings or get_settings()

    try:
        if cfg.oidc_jwks_url:
            signing_key = _jwks_client(cfg.oidc_jwks_url).get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=_oidc_algorithms(cfg),
                issuer=cfg.jwt_issuer,
                options={"verify_aud": False, "require": ["exp", "sub"]},
            )
        else:
            payload = jwt.decode(
                token,
                cfg.jwt_secret.get_secret_value(),
                algorithms=[cfg.jwt_algorithm],
                issuer=cfg.jwt_issuer,
                options={"require": ["exp", "sub"]},
            )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Token expired", status_code=401) from exc
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid token", status_code=401) from exc

    return TokenClaims.from_payload(payload)


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True)


def _oidc_algorithms(cfg: Settings) -> list[str]:
    algorithms = [a.strip() for a in cfg.oidc_algorithms.split(",") if a.strip()]
    if not algorithms or any(a.lower() == "none" or a.startswith("HS") for a in algorithms):
        raise AuthError("OIDC algorithms must be asymmetric and explicit", status_code=500)
    return algorithms


def require_roles(claims: TokenClaims, *allowed: Role) -> None:
    """Assert the caller has at least one of ``allowed`` roles.

    Args:
        claims: Authenticated token claims.
        *allowed: Roles that may access the resource.

    Raises:
        AuthError: Caller is authenticated but not authorized.
    """
    if any(role in claims.roles for role in allowed):
        return
    raise AuthError("Insufficient role", status_code=403)

"""FastAPI authentication dependencies."""

from __future__ import annotations

from collections.abc import Callable

from aeropulse_auth.jwt import Role, TokenClaims, decode_token, require_roles
from aeropulse_common.errors import AuthError
from aeropulse_common.settings import get_settings
from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(auto_error=False)

_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_claims(
    request: Request,
    authorization: str | None = Header(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenClaims:
    """Extract and validate a Bearer JWT from the Authorization header.

    Args:
        request: The request, for the read-only token check.
        authorization: Raw ``Authorization`` header.

    Returns:
        Validated token claims.

    Raises:
        HTTPException: 401 if the token is missing or invalid; 403 if a
            read-only token tries to write.
    """
    token = None
    if credentials is not None:
        token = credentials.credentials
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        claims = decode_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    if claims.read_only and request.method not in _READ_METHODS:
        allowed = {p.strip() for p in get_settings().read_only_allowed_posts.split(",")}
        if request.url.path not in allowed:
            raise HTTPException(status_code=403, detail="this demo token is read-only")
    return claims


def require(*roles: Role) -> Callable[..., TokenClaims]:
    """Build a dependency that requires at least one of ``roles``."""

    def _dep(claims: TokenClaims = Depends(get_claims)) -> TokenClaims:
        try:
            require_roles(claims, *roles)
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        return claims

    return _dep

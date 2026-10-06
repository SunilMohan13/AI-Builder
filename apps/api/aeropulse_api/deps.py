"""FastAPI authentication dependencies."""

from __future__ import annotations

from collections.abc import Callable

from aeropulse_auth.jwt import Role, TokenClaims, decode_token, require_roles
from aeropulse_common.errors import AuthError
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(auto_error=False)


def get_claims(
    authorization: str | None = Header(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenClaims:
    """Extract and validate a Bearer JWT from the Authorization header.

    Args:
        authorization: Raw ``Authorization`` header.

    Returns:
        Validated token claims.

    Raises:
        HTTPException: 401 if the token is missing or invalid.
    """
    token = None
    if credentials is not None:
        token = credentials.credentials
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        return decode_token(token)
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def require(*roles: Role) -> Callable[..., TokenClaims]:
    """Build a dependency that requires at least one of ``roles``."""

    def _dep(claims: TokenClaims = Depends(get_claims)) -> TokenClaims:
        try:
            require_roles(claims, *roles)
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        return claims

    return _dep

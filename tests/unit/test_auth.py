"""JWT encode/decode and RBAC tests."""

import jwt as pyjwt
import pytest
from aeropulse_auth.jwt import (
    Role,
    _jwks_client,
    _oidc_algorithms,
    decode_token,
    encode_token,
    require_roles,
)
from aeropulse_common.errors import AuthError
from aeropulse_common.settings import Settings
from pydantic import ValidationError


def test_round_trip_token() -> None:
    settings = Settings(jwt_secret="unit-test-secret-must-be-32bytes!")  # type: ignore[arg-type]
    token = encode_token("analyst-1", [Role.ANALYST], settings=settings)
    claims = decode_token(token, settings=settings)
    assert claims.sub == "analyst-1"
    assert Role.ANALYST in claims.roles


def test_invalid_token() -> None:
    settings = Settings(jwt_secret="unit-test-secret-must-be-32bytes!")  # type: ignore[arg-type]
    with pytest.raises(AuthError):
        decode_token("not-a-jwt", settings=settings)


def test_require_roles_forbids_viewer_admin() -> None:
    settings = Settings(jwt_secret="unit-test-secret-must-be-32bytes!")  # type: ignore[arg-type]
    token = encode_token("viewer", [Role.VIEWER], settings=settings)
    claims = decode_token(token, settings=settings)
    with pytest.raises(AuthError) as exc:
        require_roles(claims, Role.ADMIN)
    assert exc.value.status_code == 403


def test_decode_token_accepts_oidc_role_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        jwt_secret="unit-test-secret-must-be-32bytes!",  # type: ignore[arg-type]
        oidc_jwks_url="https://issuer.example.com/.well-known/jwks.json",
    )
    oidc_token = "header.payload.signature"

    class FakeSigningKey:
        key = "oidc-key"

    class FakeJwkClient:
        def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
            assert token == oidc_token
            return FakeSigningKey()

    def fake_decode(
        token: str, key: str, algorithms: list[str], issuer: str | None = None, **kwargs
    ):
        assert token == oidc_token
        assert key == "oidc-key"
        # Pinned from settings; the token header cannot choose (e.g. HS256).
        assert algorithms == ["RS256"]
        assert "exp" in kwargs["options"]["require"]
        return {
            "sub": "operator",
            "role": "OPERATOR",
            "iss": settings.jwt_issuer,
            "exp": 4102444800,
        }

    _jwks_client.cache_clear()
    monkeypatch.setattr("aeropulse_auth.jwt.jwt.PyJWKClient", lambda url, **_: FakeJwkClient())
    monkeypatch.setattr("aeropulse_auth.jwt.jwt.decode", fake_decode)

    claims = decode_token(oidc_token, settings=settings)
    _jwks_client.cache_clear()
    assert claims.sub == "operator"
    assert Role.OPERATOR in claims.roles
    assert require_roles(claims, Role.OPERATOR) is None


def test_oidc_rejects_symmetric_algorithms() -> None:
    settings = Settings(
        jwt_secret="unit-test-secret-must-be-32bytes!",  # type: ignore[arg-type]
        oidc_jwks_url="https://issuer.example.com/.well-known/jwks.json",
        oidc_algorithms="HS256",
    )
    with pytest.raises(AuthError):
        _oidc_algorithms(settings)


def test_token_without_exp_is_rejected() -> None:
    settings = Settings(jwt_secret="unit-test-secret-must-be-32bytes!")  # type: ignore[arg-type]
    token = pyjwt.encode(
        {"sub": "x", "iss": settings.jwt_issuer},
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(AuthError):
        decode_token(token, settings=settings)


@pytest.mark.parametrize("secret", [None, "short"])
def test_weak_jwt_secret_refused_outside_development(secret: str | None) -> None:
    kwargs = {"environment": "production"}
    if secret is not None:
        kwargs["jwt_secret"] = secret
    with pytest.raises(ValidationError, match="AEROPULSE_JWT_SECRET"):
        Settings(**kwargs)  # type: ignore[arg-type]


def test_strong_jwt_secret_accepted_in_production() -> None:
    Settings(environment="production", jwt_secret="x" * 48)  # type: ignore[arg-type]

"""JWT encode/decode and RBAC tests."""

import pytest
from aeropulse_auth.jwt import Role, decode_token, encode_token, require_roles
from aeropulse_common.errors import AuthError
from aeropulse_common.settings import Settings
from pydantic import ValidationError


def test_settings_refuse_missing_and_published_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AEROPULSE_JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings()
    with pytest.raises(ValidationError):
        Settings(jwt_secret="dev-only-change-me-use-32-bytes-min")  # type: ignore[arg-type]


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
        assert algorithms == ["RS256"]
        assert "none" not in algorithms
        return {
            "sub": "operator",
            "role": "OPERATOR",
            "iss": settings.jwt_issuer,
            "exp": 4102444800,
        }

    monkeypatch.setattr(
        "aeropulse_auth.jwt.jwt.get_unverified_header",
        lambda token: {"alg": "none"},
    )
    monkeypatch.setattr("aeropulse_auth.jwt.jwt.PyJWKClient", lambda url: FakeJwkClient())
    monkeypatch.setattr("aeropulse_auth.jwt.jwt.decode", fake_decode)

    claims = decode_token(oidc_token, settings=settings)
    assert claims.sub == "operator"
    assert Role.OPERATOR in claims.roles
    assert require_roles(claims, Role.OPERATOR) is None

"""Signed citizen-upload URLs on Cloud Run, where no key file exists (LLD APAC 13.1)."""

from __future__ import annotations

from typing import Any

import google.auth.credentials
from aeropulse_storage.objects import GcsObjectStore


class RuntimeIdentity(google.auth.credentials.Credentials):
    """Like Cloud Run's metadata-server credentials: a token, no private key."""

    service_account_email = "sa-api@demo-project.iam.gserviceaccount.com"

    def __init__(self) -> None:
        super().__init__()
        self.refreshed = 0

    def refresh(self, request: Any) -> None:
        self.refreshed += 1
        self.token = "runtime-access-token"
        self.expiry = None


class KeyFile(google.auth.credentials.Credentials, google.auth.credentials.Signing):
    def refresh(self, request: Any) -> None:
        raise AssertionError("a key signs locally; no token is needed")

    def sign_bytes(self, message: bytes) -> bytes:
        return b"signature"

    @property
    def signer_email(self) -> str:
        return "local@demo-project.iam.gserviceaccount.com"

    @property
    def signer(self) -> Any:
        return None


class FakeBlob:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_signed_url(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "https://storage.example/signed"


class FakeClient:
    def __init__(self, credentials: Any) -> None:
        self._credentials = credentials
        self.last_blob = FakeBlob()

    def bucket(self, name: str) -> Any:
        return self

    def blob(self, key: str) -> FakeBlob:
        return self.last_blob


def test_without_a_key_the_runtime_identity_signs_through_iam() -> None:
    identity = RuntimeIdentity()
    client = FakeClient(identity)
    store = GcsObjectStore("demo-citizen", client=client)

    store.signed_upload_url(
        "incoming/rep_1/abc", content_type="image/jpeg", max_bytes=1024, ttl_s=300
    )
    store.signed_download_url("sanitized/rep_1.jpg", ttl_s=300)

    assert identity.refreshed == 1, "the token is fetched once, then reused while valid"
    for call in client.last_blob.calls:
        assert call["service_account_email"] == RuntimeIdentity.service_account_email
        assert call["access_token"] == "runtime-access-token"


def test_a_key_file_signs_locally() -> None:
    client = FakeClient(KeyFile())
    store = GcsObjectStore("demo-citizen", client=client)

    store.signed_upload_url(
        "incoming/rep_1/abc", content_type="image/jpeg", max_bytes=1024, ttl_s=300
    )

    call = client.last_blob.calls[0]
    assert "access_token" not in call and "service_account_email" not in call
    assert call["headers"] == {"x-goog-content-length-range": "0,1024"}

"""HTTP client for the citizen analyzer, so the API never imports another app.

On Google Cloud, a sanitized upload reaches the analyzer through the GCS
notification and Pub/Sub push; the API only calls it for moderation. Locally
there is no notification, so after a multipart upload the API posts the
same push envelope the subscription would.

The analyzer's Cloud Run service is IAM-protected, and ``Authorization``
already carries the operator's own token, so on Google Cloud the API's
identity goes in ``X-Serverless-Authorization`` (Cloud Run checks that header
first and passes ``Authorization`` through untouched).
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated, Any

import httpx
from fastapi import Depends

from aeropulse_api.platform import ApiPlatform, get_platform

TIMEOUT_SECONDS = 60.0


class AnalyzerUnavailableError(RuntimeError):
    pass


def google_id_token(audience: str) -> str:
    """An ID token for ``audience`` from the runtime service account (ADC, no key file)."""
    import google.auth.exceptions
    import google.auth.transport.requests
    import google.oauth2.id_token

    try:
        request = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(request, audience)
    except google.auth.exceptions.GoogleAuthError as exc:
        raise AnalyzerUnavailableError(f"no identity token for the analyzer: {exc}") from exc
    if not token:
        raise AnalyzerUnavailableError("no identity token for the analyzer: empty token")
    return str(token)


class AnalyzerClient:
    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        id_token: Callable[[str], str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._id_token = id_token

    def _post(self, path: str, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        try:
            if self._id_token is not None:
                token = self._id_token(self.base_url)
                headers = {**headers, "X-Serverless-Authorization": f"Bearer {token}"}
            return self._client.post(f"{self.base_url}{path}", json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise AnalyzerUnavailableError(f"citizen analyzer unreachable: {exc}") from exc

    def notify_upload(self, object_key: str) -> dict[str, Any]:
        payload = json.dumps({"name": object_key}).encode()
        envelope = {
            "message": {
                "attributes": {"objectId": object_key, "eventType": "OBJECT_FINALIZE"},
                "data": base64.b64encode(payload).decode(),
                "messageId": uuid.uuid4().hex,
            },
            "subscription": "local-api-notify",
        }
        response = self._post("/pubsub/push", envelope, {})
        if response.status_code != 200:
            raise AnalyzerUnavailableError(
                f"citizen analyzer returned {response.status_code} for the upload"
            )
        return response.json()

    def moderate(
        self, report_id: str, body: dict[str, Any], *, authorization: str
    ) -> tuple[int, dict[str, Any]]:
        response = self._post(
            f"/reports/{report_id}/moderation", body, {"Authorization": authorization}
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": response.text[:200]}
        return response.status_code, payload


@lru_cache(maxsize=4)
def _client_for(base_url: str, on_gcp: bool) -> AnalyzerClient:
    return AnalyzerClient(base_url, id_token=google_id_token if on_gcp else None)


def get_analyzer_client(
    platform: Annotated[ApiPlatform, Depends(get_platform)],
) -> AnalyzerClient | None:
    url = platform.settings.citizen_analyzer_url
    return _client_for(url, platform.settings.platform == "gcp") if url else None

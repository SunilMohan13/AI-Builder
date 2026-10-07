"""One real in-north cycle over the replay fixtures, and an API platform over it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from aeropulse_api.app import create_app
from aeropulse_api.platform import ApiPlatform, get_platform
from aeropulse_auth import Role, encode_token
from aeropulse_common.settings import Settings, get_settings
from aeropulse_contracts import RegionSnapshot
from aeropulse_cycle import CycleRunner
from aeropulse_regions import load_catalog, load_citizen_settings
from aeropulse_storage import build_storage
from fastapi.testclient import TestClient
from replayed_registry import replayed_registry

T0 = datetime(2026, 9, 8, 6, tzinfo=UTC)
CONFIG = Path("config")


def run_cycle(root: Path) -> RegionSnapshot:
    runner = CycleRunner(
        load_catalog(CONFIG),
        build_storage(Settings(data_dir=root)),
        registry=replayed_registry(),
        fixtures_root=Path("fixtures"),
        clock=lambda: T0 + timedelta(minutes=5),
    )
    return runner.run("in-north", T0, "live").snapshot


def platform_for(root: Path, **overrides: object) -> ApiPlatform:
    settings = Settings(data_dir=root, **overrides)  # type: ignore[arg-type]
    return ApiPlatform(
        settings=settings,
        catalog=load_catalog(CONFIG),
        storage=build_storage(settings),
        citizen=load_citizen_settings(CONFIG),
        clock=lambda: T0 + timedelta(minutes=10),
    )


def client_for(platform: ApiPlatform) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_platform] = lambda: platform
    return TestClient(app)


def auth(*roles: Role, sub: str = "tester") -> dict[str, str]:
    token = encode_token(sub, list(roles) or [Role.VIEWER], settings=get_settings())
    return {"Authorization": f"Bearer {token}"}
